#!/usr/bin/env python3
"""Fail if a Telegram user other than the configured chat can put text on
APRS through the bridge.

Until 2026-10-26 every message the bot received was relayed to APRS-IS under
the operator's callsign (`from_callsign`): the poll never looked at which chat
it came from, and a Telegram bot can be found by its name.

What must hold (getUpdates replaced, no network):

  1. a message from the configured chat_id is relayed, from `from_callsign`
  2. the same message from another chat, or from a group, is not relayed and
     is logged as ignored
  3. a chat_id configured as a number or as a string matches alike

Usage:  python tools/check_telegram_inbound.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.telegram_ext as tg  # noqa: E402

OWN = 123456789


def update(uid, chat_id, text, chat_type="private"):
    return {"update_id": uid, "message": {
        "chat": {"id": chat_id, "type": chat_type},
        "from": {"id": chat_id, "first_name": "someone"}, "text": text}}


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def run(chat_id_cfg, updates):
    cfg = {"enabled": True, "bot_token": "stub", "chat_id": chat_id_cfg,
           "poll_enabled": True, "from_callsign": "TA3HX-6",
           "aprs_destination": "TA3HX-7", "allowed_recepients": ["TGSEND"],
           "allowed_senders": ["TA3HX"]}
    ext = tg.Telegram(cfg)
    q = Q()
    ext._queue = q
    logs = []
    ext.warn = lambda m: logs.append(m)
    ext.log = lambda m: logs.append(m)
    tg._tg_api = lambda *a, **k: {"ok": True, "result": updates}
    asyncio.run(ext._check_updates())
    return q.sent, logs


def main() -> int:
    p = []
    ups = [update(1, OWN, "TA1ABC-7 from the operator"),
           update(2, 987654321, "TA1ABC-7 from a stranger"),
           update(3, -100200300, "TA1ABC-7 from a group", "supergroup")]
    for cfg_id in (str(OWN), OWN):
        sent, logs = run(cfg_id, ups)
        print(f"  chat_id={cfg_id!r:<12} sent -> {sent}")
        if len(sent) != 1 or "from the operator" not in sent[0] \
                or not sent[0].startswith("TA3HX-6>"):
            p.append(f"chat_id {cfg_id!r}: relayed {sent}")
        ignored = [m for m in logs if "ignored" in m]
        if len(ignored) != 2:
            p.append(f"chat_id {cfg_id!r}: {len(ignored)} 'ignored' lines, want 2")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
