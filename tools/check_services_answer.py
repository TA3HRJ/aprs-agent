#!/usr/bin/env python3
"""Fail if the AI gateway leaves "which services are open?" to the model, or
answers it with a bridge that is off, or one the asker may not use.

Measured 2026-10-27: "hangi servisler acik", "what services are available",
"servisler" and "telegram var mi" all went to the model. The model does not
know which bridges this server carries (Telegram, Bluesky, e-mail ...), so
it could only guess, and HELP did not mention the bridges at all.

What must hold (no network, no provider):

  1. those four questions are answered by the code, not the model
  2. the answer names each enabled bridge with the alias to send to, and
     lists the disabled ones as off - read from the config, not written in
  3. a sender in a bridge's allowed_senders is told it is open to them;
     anyone else is told it is for listed calls only
  4. Telegram with allow_links is open to everyone, with /bagla
  5. "how do I send an e-mail from my radio" still goes to the model
  6. HELP points to SERVICES when a bridge is on, and not when none is
  7. the model (Anthropic request shape) is told it cannot pass messages to other networks and to
     point to SERVICES, when a bridge is on
  8. asking again within ten minutes is not answered again for free
  9. with links open the answer names the Telegram bot (@name) - a stranger
     told "/bagla" could not tell which bot to write to - and still arrives
     whole within the gateway's parts, in both languages
 10. the Telegram bridge learns that name from getMe, and the web GUI hands
     it to the gateway

Usage:  python tools/check_services_answer.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
       "api_keys": {"deepseek": "stub"}, "extra_sms": 2,
       "rate_burst": 50, "rate_refill_s": 1}

# The shape of the live server's bridges on 2026-10-27
BRIDGES = {
    "twitter": {"enabled": False, "allowed_recepients": ["twsend", "TWSEND"],
                "allowed_senders": ["TA3HX", "TA3OP"]},
    "bluesky": {"enabled": True, "allowed_recepients": ["BSKYSEND"],
                "allowed_senders": ["TA3HX", "TA3OP"]},
    "whatsapp": {"enabled": False, "allowed_recepients": ["WASEND"],
                 "allowed_senders": ["N0CALL"]},
    "telegram": {"enabled": True, "allowed_recepients": ["TGSEND"],
                 "allowed_senders": ["TA3HX", "TA3OP"]},
    "imap": {"enabled": False},
    "smtp": {"enabled": True, "allowed_recipients": ["EMAIL"],
             "allowed_senders": ["TA3HX"]},
}

SYSTEM: list = []


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
        SYSTEM.append((json or {}).get("system", ""))
        return _Resp()


httpx.Client = _Client


def line(sender: str, text: str, msg_id: str) -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s{%s" % (sender, text, msg_id)


def gateway(bridges):
    sent, asked = [], []

    class Q:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Q()
    setter = getattr(gw, "set_bridges", None)
    if setter and bridges is not None:
        setter(bridges)

    async def stub(question, sender="", history=None):
        asked.append(question)
        return "model answer"

    gw._ask_ai = stub
    return gw, sent, asked


def reply(sent: list, since: int, to_call: str) -> str:
    out = []
    for s in sent[since:]:
        if "::%-9s" % to_call not in s:
            continue
        body = s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            continue
        out.append(body.rsplit("{", 1)[0].replace(" --", "").strip())
    return " ".join(out)


async def ask(gw, sent, sender, text, n=[100]):
    n[0] += 1
    i = len(sent)
    await gw.handle(line(sender, text, str(n[0])))
    return reply(sent, i, sender)


async def run() -> list:
    p = []

    # 1-3: a stranger, in both languages
    for q in ("hangi servisler acik", "what services are available",
              "servisler", "telegram var mi"):
        gw, sent, asked = gateway(copy.deepcopy(BRIDGES))
        a = await ask(gw, sent, "TA1ABC-7", q)
        print(f"  1 {q!r:32} -> {a!r}")
        if asked:
            p.append(f"1: {q!r} went to the model")
            continue
        low = a.lower()
        for want in ("TGSEND", "BSKYSEND", "EMAIL"):
            if want not in a:
                p.append(f"2: {q!r}: {want} missing: {a!r}")
        if not any(w in low for w in ("kapali", "off:")) or "whatsapp" not in low:
            p.append(f"2: {q!r}: the bridges that are off are not listed: {a!r}")
        if any(w in low for w in ("sana acik", "open to you")):
            p.append(f"3: {q!r}: a stranger was told a bridge is open to them: {a!r}")

    # 3: an allowed sender
    gw, sent, asked = gateway(copy.deepcopy(BRIDGES))
    a = await ask(gw, sent, "TA3OP-9", "services")
    print(f"  3 allowed sender              -> {a!r}")
    if "Open to you" not in a or "TGSEND" not in a.split("Listed")[0] \
            or "EMAIL" not in a.split("Listed")[-1]:
        p.append(f"3: allowed sender: {a!r}")

    # 4: Telegram open to licensed amateurs
    b = copy.deepcopy(BRIDGES)
    b["telegram"]["allow_links"] = True
    gw, sent, asked = gateway(b)
    a = await ask(gw, sent, "TA1ABC-7", "servis")
    print(f"  4 allow_links                 -> {a!r}")
    if "TGSEND Telegram (/bagla)" not in a.split("izinli")[0]:
        p.append(f"4: {a!r}")

    # 5: a question that only mentions e-mail
    gw, sent, asked = gateway(copy.deepcopy(BRIDGES))
    await ask(gw, sent, "TA1ABC-7", "how do I send an email from my radio")
    print(f"  5 e-mail how-to -> model: {bool(asked)}")
    if not asked:
        p.append("5: an ordinary question was taken for SERVICES")

    # 6: HELP
    gw, sent, asked = gateway(copy.deepcopy(BRIDGES))
    a = await ask(gw, sent, "TA1ABC-7", "help")
    gw0, sent0, _ = gateway({k: dict(v, enabled=False) for k, v in BRIDGES.items()})
    a0 = await ask(gw0, sent0, "TA1ABC-7", "help")
    print(f"  6 help -> {a[-30:]!r} | no bridges -> {a0[-30:]!r}")
    if "SERVICES" not in a or "SERVICES" in a0 or "..." in a:
        p.append(f"6: help {a!r} / {a0!r}")

    # 7: the model's rules
    SYSTEM.clear()
    gw = AIGateway(dict(CFG, provider="anthropic", api_keys={"anthropic": "stub"}), "")
    getattr(gw, "set_bridges", lambda _b: None)(copy.deepcopy(BRIDGES))
    await gw._ask_ai("can you send this to telegram", sender="TA1ABC-7")
    s = SYSTEM[-1] if SYSTEM else ""
    print(f"  7 model told about SERVICES: {'SERVICES' in s}")
    if "SERVICES" not in s or "cannot pass messages" not in s:
        p.append("7: the model is not told it cannot reach other networks")

    # 8: again within ten minutes
    gw, sent, asked = gateway(copy.deepcopy(BRIDGES))
    await ask(gw, sent, "TA1ABC-7", "servisler")
    await ask(gw, sent, "TA1ABC-7", "hangi servisler acik")
    print(f"  8 second ask -> model: {bool(asked)}")
    if not asked:
        p.append("8: SERVICES answered twice in ten minutes without the limiter")

    # 9: the live shape, links open, the bot named
    b = copy.deepcopy(BRIDGES)
    b["telegram"]["allow_links"] = True
    b["smtp"]["allow_links"] = True
    for q, last in (("servis", "e-posta alma."), ("services", "e-mail in.")):
        gw, sent, asked = gateway(None)
        try:
            gw.set_bridges(b, lambda: "APRSAgent_bot")
        except TypeError:
            gw.set_bridges(b)
        a = await ask(gw, sent, "TA1ABC-7", q)
        print(f"  9 {q!r:10} -> {a!r}")
        if "Telegram @APRSAgent_bot (/" not in a:
            p.append(f"9: {q!r}: the bot is not named: {a!r}")
        if not a.endswith(last):
            p.append(f"9: {q!r}: the answer was cut: {a!r}")

    # 10: getMe, and the wiring
    import extensions.telegram_ext as tgm
    from extensions.telegram_ext import Telegram
    tg = Telegram({"enabled": True, "bot_token": "stub", "chat_id": "42"})
    tg.log = tg.warn = tg.error = lambda m: None
    orig = tgm._tg_api
    tgm._tg_api = lambda token, method, params=None, timeout=15: (
        {"ok": True, "result": {"username": "APRSAgent_bot"}} if method == "getMe" else {"ok": True})
    try:
        learn = getattr(tg, "_learn_username", None)
        if learn:
            await learn()
    finally:
        tgm._tg_api = orig
    got = getattr(tg, "bot_username", "")
    src = (Path(__file__).resolve().parent.parent / "web_gui.py").read_text(encoding="utf-8")
    wired = "bot_username" in src.split("ext.set_bridges(", 1)[-1].split("\n", 1)[0]
    print(f" 10 getMe -> {got!r}, web GUI hands it over: {wired}")
    if got != "APRSAgent_bot":
        p.append("10: the Telegram bridge does not learn its bot name")
    if not wired:
        p.append("10: web_gui does not give the gateway the bot name")
    return p


def main() -> int:
    p = asyncio.run(run())
    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
