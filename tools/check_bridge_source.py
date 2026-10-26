#!/usr/bin/env python3
"""Fail if a bridged message can go on air without naming its originator,
or if the operator cannot choose how it is named.

KEGM Amatör Telsizcilik Sınav ve Belgelendirme Yönetmeliği Md.23/1-f and
1-g (F-2026-10-26-01): a message from Telegram, WhatsApp or e-mail sent to an
APRS station carries its originator's callsign - either as the packet's
source ("own") or, from the bridge's gateway callsign, at the head of the
text ("gateway"). Chosen per bridge with `aprs_source`.

What must hold:

  1. "own": the packet's source is from_callsign, the text as written
  2. "gateway": the source is gateway_callsign, else the first trigger
     alias; the text opens with "<from_callsign>: "
  3. an unknown mode reads as "own"; a text past 64 characters is cut
  4. e-mail (IMAP) has no callsign for its sender: the source is the bridge's
     callsign and the text opens with the sender's address, in either mode
  5. config defaults, the template and the web panel carry aprs_source and
     gateway_callsign for Telegram and WhatsApp

Usage:  python tools/check_bridge_source.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import extensions.telegram_ext as tg  # noqa: E402
import extensions.imap_ext as im  # noqa: E402


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def telegram(extra: dict, text="TA1ABC-7 hello from telegram"):
    cfg = {"enabled": True, "bot_token": "stub", "chat_id": "42",
           "poll_enabled": True, "from_callsign": "TA3HX-6",
           "allowed_recepients": ["TGSEND"], "allowed_senders": ["TA3HX"]}
    cfg.update(extra)
    ext = tg.Telegram(cfg)
    q = Q()
    ext._queue = q
    ext.log = ext.warn = lambda m: None
    tg._tg_api = lambda *a, **k: {"ok": True, "result": [{"update_id": 1, "message": {
        "chat": {"id": 42}, "from": {"first_name": "op"}, "text": text}}]}
    asyncio.run(ext._check_updates())
    return q.sent[0] if q.sent else ""


def imap(extra: dict):
    cfg = {"enabled": True, "imap_server": "x:993", "imap_username": "u",
           "imap_password": "p", "from_callsign": "EMAIL-5"}
    cfg.update(extra)
    ext = im.IMAPReceiver(cfg) if hasattr(im, "IMAPReceiver") else next(
        v for v in vars(im).values() if isinstance(v, type) and v.__module__ == im.__name__
        and hasattr(v, "_check_inbox"))(cfg)
    q = Q()
    ext._queue = q
    ext.log = ext.warn = lambda m: None
    ext._fetch_emails = lambda: [("TA1ABC-7", "hello from mail", "friend@example.org")]
    asyncio.run(ext._check_inbox())
    return q.sent[0] if q.sent else ""


def main() -> int:
    p = []
    cases = [
        ("own", {}, "TA3HX-6>", ":hello from telegram{"),
        ("own (explicit)", {"aprs_source": "own"}, "TA3HX-6>", ":hello from telegram{"),
        ("gateway, alias", {"aprs_source": "gateway"}, "TGSEND>", ":TA3HX-6: hello from telegram{"),
        ("gateway, set", {"aprs_source": "gateway", "gateway_callsign": "TGATE"}, "TGATE>",
         ":TA3HX-6: hello from telegram{"),
        ("unknown mode", {"aprs_source": "nonsense"}, "TA3HX-6>", ":hello from telegram{"),
    ]
    for name, extra, src, body in cases:
        pkt = telegram(extra)
        print(f"  telegram {name:<16} -> {pkt}")
        if not pkt.startswith(src) or body not in pkt:
            p.append(f"telegram {name}: {pkt!r}")
    long_pkt = telegram({"aprs_source": "gateway"}, "TA1ABC-7 " + "x" * 80)
    text = long_pkt.split("::", 1)[1].split(":", 1)[1].rsplit("{", 1)[0]
    print(f"  telegram long gateway  -> {len(text)} chars")
    if len(text) > 64 or not text.startswith("TA3HX-6: "):
        p.append(f"long gateway text {len(text)} chars: {text!r}")

    for mode in ("own", "gateway"):
        pkt = imap({"aprs_source": mode})
        print(f"  imap {mode:<20} -> {pkt}")
        if not pkt.startswith("EMAIL-5>") or "friend@example.org: hello from mail" not in pkt:
            p.append(f"imap {mode}: {pkt!r}")

    tpl = (ROOT / "aprsconfig.toml.template").read_text(encoding="utf-8")
    t = config.tomllib.loads(tpl)
    ui = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for s, pre in (("telegram", "tg"), ("whatsapp", "wa")):
        d = config.DEFAULTS["extensions"][s]
        if d.get("aprs_source") != "own" or "gateway_callsign" not in d:
            p.append(f"config defaults for {s} lack aprs_source/gateway_callsign")
        if t["extensions"][s].get("aprs_source") != "own" or "gateway_callsign" not in t["extensions"][s]:
            p.append(f"template for {s} lacks aprs_source/gateway_callsign")
        if f'id="f-{pre}-src"' not in ui or f"aprs_source:$('f-{pre}-src')" not in ui:
            p.append(f"web panel lacks the {s} source choice")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
