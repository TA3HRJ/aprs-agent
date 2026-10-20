#!/usr/bin/env python3
"""Fail if an AI provider is sent a model it no longer serves, or a request
a reasoning model answers with nothing.

2026-10-20, checked against each provider's own documentation: Groq shut its
Llama models (the gateway's and the notes' defaults) for free and developer
accounts on 2026-08-16; Anthropic retired Claude 3.5 Haiku on 2026-02-19;
OpenRouter's free Llama 3.3 is gone; OpenAI shuts gpt-4o-mini on
2027-01-14; Puter's OpenAI-compatible endpoint needs a paid plan, while the
docs called it free. The replacements think before they answer, and the
thinking counts against the same output limit: 40 tokens for a one-part
answer, 120 for a note.

What must hold (a local OpenAI-compatible server records what is sent):

  1. the gateway and the station notes send each provider's current default
     model when none is configured; no retired model is a default
  2. Gemini and Groq's gpt-oss get reasoning_effort "low" and room for it on
     top of the answer's budget; OpenAI gets max_completion_tokens and
     reasoning_effort "none"; DeepSeek keeps thinking disabled
  3. a model the operator names is sent as named
  4. Gemini is the default provider in config, the template and the web UI,
     and the user docs no longer call Puter free

No network beyond 127.0.0.1.

Usage:  python tools/check_ai_providers.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
import tempfile
import tomllib
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestServer  # noqa: E402

import config  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402
import web_gui  # noqa: E402

RETIRED = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant",
           "meta-llama/llama-3.3-70b-instruct:free", "claude-3-5-haiku-20241022")
# each provider's current model, from its own documentation on 2026-10-20
EXPECTED = {
    "gemini":     "gemini-flash-latest",
    "groq":       "openai/gpt-oss-120b",
    "openrouter": "google/gemma-4-31b-it:free",
    "openai":     "gpt-6-luna",
    "deepseek":   "deepseek-v4-flash",
    "anthropic":  "claude-haiku-5-5",
}
seen: list[dict] = []


async def chat(request: web.Request) -> web.Response:
    body = await request.json()
    seen.append(body)
    content = '{"org": null, "description": null}' if "JSON" in str(body) else "An answer."
    if request.path.endswith("/v1/messages"):
        return web.json_response({"content": [{"type": "text", "text": content}]})
    return web.json_response({"choices": [{"message": {"role": "assistant",
                                                       "content": content}}]})


async def gateway_body(base: str, provider: str, model: str = "") -> dict:
    cfg = {"enabled": True, "callsign": "DMWGPT", "provider": provider,
           "base_url": base, "model": model, "api_keys": {provider: "stub"},
           "extra_sms": 0}
    gw = AIGateway(cfg, str(Path(tempfile.mkdtemp()) / "aprsconfig.toml"))
    seen.clear()
    answer = await gw._ask_ai("What is a dipole?")
    return seen[-1] if seen and answer else {}


async def notes_body(base: str, provider: str) -> dict:
    mgr = types.SimpleNamespace(_ai_calls=0)
    seen.clear()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, lambda: web_gui.AgentManager._call_ai_api(
        mgr, provider, base, "stub", "", "Return ONLY valid JSON: {}"))
    return seen[-1] if seen else {}


async def main() -> int:
    p = []
    app = web.Application()
    app.router.add_post("/v1/chat/completions", chat)
    app.router.add_post("/v1/messages", chat)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("/v1")).rstrip("/") + "/"
    host = str(server.make_url("")).rstrip("/")
    try:
        defaults = EXPECTED
        for prov in ("gemini", "groq", "openrouter", "openai", "deepseek"):
            for where, body in (("gateway", await gateway_body(base, prov)),
                                ("notes", await notes_body(base.rstrip("/"), prov))):
                shown = {k: v for k, v in body.items() if k not in ("messages",)}
                print(f"  {prov:<10} {where:<8} {shown}")
                if body.get("model") != defaults[prov]:
                    p.append(f"{prov} {where}: model {body.get('model')!r}, "
                             f"default is {defaults[prov]!r}")
                budget = 40 if where == "gateway" else 120
                if prov in ("gemini", "groq"):
                    if body.get("reasoning_effort") != "low" or \
                            (body.get("max_tokens") or 0) < budget + 512:
                        p.append(f"{prov} {where}: no reasoning room {shown}")
                elif prov == "openai":
                    if body.get("max_completion_tokens") != budget or \
                            body.get("reasoning_effort") != "none" or "max_tokens" in body:
                        p.append(f"openai {where}: {shown}")
                elif prov == "deepseek":
                    if body.get("thinking") != {"type": "disabled"}:
                        p.append(f"deepseek {where}: thinking not disabled")
                elif body.get("max_tokens") != budget:
                    p.append(f"{prov} {where}: max_tokens {body.get('max_tokens')}")

        named = await gateway_body(base, "groq", "qwen/qwen3.8-27b")
        if named.get("model") != "qwen/qwen3.8-27b" or "reasoning_effort" in named:
            p.append(f"a named non-gpt-oss Groq model: {named}")

        body = await gateway_body(host, "anthropic")
        print(f"  anthropic  gateway  model={body.get('model')!r}")
        if body.get("model") != defaults["anthropic"]:
            p.append(f"anthropic gateway model {body.get('model')!r}")
        seen.clear()
        mgr = types.SimpleNamespace(_ai_calls=0)
        await asyncio.get_running_loop().run_in_executor(
            None, lambda: web_gui.AgentManager._call_ai_api(
                mgr, "anthropic", host, "stub", "", "Return ONLY valid JSON: {}"))
        if not seen or seen[-1].get("model") != defaults["anthropic"] \
                or "temperature" in seen[-1]:
            p.append(f"anthropic notes: {seen[-1] if seen else 'no request'}")
    finally:
        await server.close()

    stale = [m for m in getattr(config, "AI_PROVIDER_MODELS", {}).values() if m in RETIRED]
    if stale:
        p.append(f"retired models still defaults: {stale}")
    if getattr(config, "AI_DEFAULT_PROVIDER", "") != "gemini" or \
            config.DEFAULTS["extensions"]["ai_gateway"]["provider"] != "gemini":
        p.append("config default provider is not gemini")
    tpl = tomllib.loads((ROOT / "aprsconfig.toml.template").read_text(encoding="utf-8"))
    if tpl["extensions"]["ai_gateway"]["provider"] != "gemini" or \
            "gemini" not in tpl["extensions"]["ai_gateway"]["api_keys"]:
        p.append("template does not default to gemini with a gemini key")
    ui = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if '<option value="gemini">' not in ui or "aiPrevProvider='gemini'" not in ui:
        p.append("web UI lacks gemini as the default choice")
    for doc in ("HELP.html", "README.md", "aprsconfig.toml.template", "static/index.html"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        # the old wording: "Puter (free)", "Puter is a completely free AI provider"
        if re.search(r"Puter\s*\((free|ücretsiz)\)"
                     r"|Puter (is a completely|tamamen) (free|ücretsiz)", text, re.I):
            p.append(f"{doc} still calls Puter free")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
