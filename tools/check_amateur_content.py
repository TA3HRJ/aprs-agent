#!/usr/bin/env python3
"""Fail if the model is not told that its answer may go out on amateur radio,
or if an operator's own system_prompt can remove that.

DMWGPT's answers reach radios through other stations' IS->RF igates, so
they are transmitted under those operators' licences. The amateur service
does not carry advertising, profanity, propaganda, music or content hidden
by encoding. Nothing in the prompt said so until 2026-09-30: the rules
covered length, ASCII, language and callsigns, and content was left to the
model's defaults.

What must hold:

  1. the system prompt names amateur radio as where the answer may be sent
     and lists what does not belong there
  2. it says what to do when asked for such content
  3. an operator's system_prompt in the config is added to the rules, it
     does not replace them (the lesson of the length limit, which an
     operator prompt once discarded)

No network: the HTTP client is replaced and the prompt is captured.

Usage:  python tools/check_amateur_content.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

SEEN: list[str] = []


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"content": [{"type": "text", "text": "OK."}]}


class _Client:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        SEEN.append((json or {}).get("system", ""))
        return _Resp()


httpx.Client = _Client

MUST = {
    "names amateur radio": ("amateur radio",),
    "igates and licences": ("igate", "licence"),
    "no advertising": ("advertising",),
    "no profanity": ("profanity",),
    "no propaganda": ("propaganda",),
    "no music": ("music",),
    "nothing encoded": ("encoded",),
    "what to do when asked": ("if asked for such content",),
}


def prompt_for(operator: str) -> str:
    cfg = {"enabled": True, "callsign": "DMWGPT", "provider": "anthropic",
           "api_keys": {"anthropic": "stub"}, "extra_sms": 2}
    if operator:
        cfg["system_prompt"] = operator
    gw = AIGateway(cfg, "")
    SEEN.clear()
    asyncio.run(gw._ask_ai("hello", sender="TA1ABC-7"))
    return SEEN[-1] if SEEN else ""


def main() -> int:
    fails = 0
    for label, operator in (("default prompt", ""),
                            ("operator prompt set",
                             "You are a friendly helper for hams in Turkey.")):
        p = prompt_for(operator).lower()
        if not p:
            print(f"  FAIL  {label}: no request captured")
            fails += 1
            continue
        for what, words in MUST.items():
            if not all(w in p for w in words):
                print(f"  FAIL  {label}: {what} missing")
                fails += 1
        if operator and operator.lower() not in p:
            print(f"  FAIL  {label}: the operator's prompt was dropped")
            fails += 1
        if not fails:
            print(f"  ok    {label}")
    if fails:
        print(f"\n{fails} failure(s)")
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
