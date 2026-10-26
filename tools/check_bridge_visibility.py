#!/usr/bin/env python3
"""Fail if a bridge's state or traffic is hidden from the operator.

2026-10-26: WhatsApp was off and the status row said nothing about it - the
row drew only modules that were on, so "off" and "not part of this software"
looked the same; the landing page meanwhile listed WhatsApp as a working
bridge. And bridge traffic reached the stored message history only when one
side matched the station filter, so a Telegram or e-mail exchange with a
station outside it was gone after twelve minutes.

What must hold:

  1. the status row draws all six bridges (Telegram, WhatsApp, Twitter,
     Bluesky, SMTP, IMAP) whether on or off, with an "off" / "allowed list
     only" title in both languages
  2. a message on a bridge channel is kept whatever its callsigns
  3. world APRS traffic outside the station filter is still not kept

Usage:  python tools/check_bridge_visibility.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_gui  # noqa: E402


def main() -> int:
    p = []
    ui = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for k in ("telegram", "whatsapp", "twitter", "bluesky", "smtp", "imap"):
        m = re.search(r"\['%s',a\.%s,([^,\]]*),(true|false)\]" % (k, k), ui)
        print(f"  badge {k:<9} -> {m.group(0) if m else 'missing'}")
        if not m or m.group(2) != "true" or "bt(" not in m.group(1):
            p.append(f"badge {k} is not drawn when off")
    for key in ("mod_off", "mod_bridge_on"):
        if ui.count(key + ':"') != 2:
            p.append(f"{key} is not in both languages")

    mgr = types.SimpleNamespace(_msg_scope=lambda: ({"DMWGPT"}, [("TA", True)]))
    kept = lambda m: web_gui.AgentManager._msg_kept(mgr, m)  # noqa: E731
    cases = [
        ({"from": "DL1ABC", "to": "TGSEND", "channel": "Telegram"}, True),
        ({"from": "W1AW", "to": "EMAIL", "channel": "Email"}, True),
        ({"from": "TGSEND", "to": "K1ABC", "channel": "Telegram"}, True),
        ({"from": "MYANET", "to": "PU2XYZ", "channel": "APRS"}, False),
        ({"from": "TA1ABC", "to": "TA2XYZ", "channel": "APRS"}, True),
    ]
    for m, want in cases:
        got = kept(m)
        print(f"  kept {m['channel']:<8} {m['from']:>7}->{m['to']:<7} -> {got}")
        if got != want:
            p.append(f"{m}: kept={got}, want {want}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
