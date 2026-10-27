#!/usr/bin/env python3
"""Fail if an APRS message this program sends carries a "{" in its text.

APRS 1.2 (wb2osz/aprsspec, APRS12c, "Messages"): the message text "may
contain any printable ASCII or UTF-8 characters except { which indicates
start of Message Identifier". Until v3.2.195 a model's answer or a bridged
user's text was put on air as written: "hi {1} there" from Telegram went out
as ":hi {1} there{7", and a receiver takes what follows the first "{" for
the message number (F-2026-10-27-02).

Every builder of a message packet is driven with such a text:

  1. the AI gateway's reply (_send_reply), and a model answer through handle()
  2. Telegram, WhatsApp and IMAP bridged messages (_send_aprs)
  3. the e-mail bridge's short replies (_reply)

and each packet must hold exactly one "{", the one before its message number,
with the text otherwise intact ("(" and ")" in place of the braces).

Usage:  python tools/check_message_brace.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import AIGateway  # noqa: E402
from extensions.imap_ext import ImapReceiver  # noqa: E402
from extensions.smtp_ext import SmtpEmailer  # noqa: E402
from extensions.telegram_ext import Telegram  # noqa: E402
from extensions.whatsapp_ext import WhatsApp  # noqa: E402

TEXT = "hi {1} there {x"
_MSG = re.compile(r"^[^:]+::.{9}:(?P<text>[^{]*)\{(?P<id>[A-Za-z0-9]{1,5})$")


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def quiet(ext):
    ext.log = ext.warn = ext.error = lambda m: None
    return ext


def judge(label: str, pkts: list, want_text: str, p: list) -> None:
    msgs = [x for x in pkts if "::" in x and ":ack" not in x.split("::", 1)[1][9:12]]
    print(f"  {label:22} -> {msgs[-1] if msgs else None!r}")
    if not msgs:
        p.append(f"{label}: nothing sent")
        return
    pkt = msgs[-1]
    m = _MSG.match(pkt)
    if pkt.count("{") != 1 or not m:
        p.append(f"{label}: {pkt!r} has {pkt.count('{')} braces")
    elif want_text and m.group("text").strip() != want_text:
        p.append(f"{label}: text {m.group('text')!r}, wanted {want_text!r}")


async def run() -> list:
    p = []
    want = TEXT.replace("{", "(").replace("}", ")")

    # 1 - the gateway
    gw = quiet(AIGateway({"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
                          "api_keys": {"deepseek": "stub"}, "extra_sms": 2}, ""))
    q = Q()
    gw._own_writer = q
    await gw._send_reply("DMWGPT", "TA1ABC-7", TEXT)
    judge("gateway _send_reply", q.sent, want, p)

    gw2 = quiet(AIGateway({"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
                           "api_keys": {"deepseek": "stub"}, "extra_sms": 2}, ""))
    q2 = Q()
    gw2._own_writer = q2

    async def stub(question, sender="", history=None):
        return "Use {braces} sparingly"

    gw2._ask_ai = stub
    await gw2.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :how do I write a set{5")
    judge("gateway model answer", q2.sent, "Use (braces) sparingly", p)

    # 2 - the bridges
    for label, ext in (
        ("telegram _send_aprs", Telegram({"enabled": True, "bot_token": "stub", "chat_id": "42",
                                          "allowed_recepients": ["TGSEND"],
                                          "allowed_senders": ["TA3HX"]})),
        ("whatsapp _send_aprs", WhatsApp({"enabled": True, "phone_number_id": "1",
                                          "access_token": "stub", "verify_token": "v",
                                          "recipient_phone": "1", "allowed_recepients": ["WASEND"],
                                          "allowed_senders": ["TA3HX"]})),
        ("imap _send_aprs", ImapReceiver({"enabled": True, "imap_server": "imap.invalid:993",
                                          "imap_username": "u", "imap_password": "p",
                                          "from_callsign": "EMAIL-5", "allowed_senders": ["a@b.c"]})),
    ):
        quiet(ext)
        qb = Q()
        ext.set_own_writer(qb)
        await ext._send_aprs("TA3HX-6", "TA2XYZ-9", TEXT)
        judge(label, qb.sent, want, p)

    # 3 - the e-mail bridge's replies
    sm = quiet(SmtpEmailer({"enabled": True, "smtp_server": "x:1", "smtp_username": "u",
                            "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"]}))
    qs = Q()
    sm.set_own_writer(qs)
    reply = getattr(sm, "_reply", None)
    if reply:
        await reply("EMAIL", "TA1ABC-7", TEXT)
    judge("smtp _reply", qs.sent, want, p)
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
