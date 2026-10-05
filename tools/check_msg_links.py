#!/usr/bin/env python3
"""Fail if the Messages tab's callsigns lead nowhere.

2026-10-05: the operator, reading the kept Messages view, could see who
wrote to whom but not where they were. The FROM and TO columns were plain
text, coloured like links. A message packet carries no position, so what
can be shown is the station's last known position from the registry -
which for a fixed station is where it sent from, and for a mobile one is
where it was last heard (the detail says when).

What must hold in static/index.html:

  1. FROM and TO are wrapped as links only when they look like a callsign:
     bulletin addresses (BLN0, BLN1LOCAL), services (DMWGPT, MYANET) and
     Telegram names stay plain text
  2. a click asks the registry for the station (/api/stations/<call>) and,
     when it is known, goes to it on the map with its detail (mapSearchGo)
  3. a callsign the registry does not hold says so instead of doing nothing

Usage:  python tools/check_msg_links.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "static" / "index.html"


def body_of(src: str, name: str) -> str:
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % re.escape(name), src)
    if not m:
        return ""
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.start():i]


def main() -> int:
    page = PAGE.read_text(encoding="utf-8")
    fails = []
    m = re.search(r"const MSG_CS_RE\s*=\s*/(.+?)/;", page)
    if not m:
        fails.append("no MSG_CS_RE deciding what is a callsign")
    else:
        rx = re.compile(m.group(1))
        for ok in ("TA3HX-7", "YM2VGT", "CX2JO-10", "9W2KEY", "TA5LVC-12", "EA1062RCU"):
            if not rx.search(ok):
                fails.append("%s is not linked" % ok)
        for no in ("BLN0", "BLN1LOCAL", "BLN3 SKYR", "DMWGPT", "MYANET", "TU_CALL", ""):
            if rx.search(no):
                fails.append("%r is linked as a callsign" % no)
    rm = body_of(page, "renderMsgs")
    if "msgCs(m.from" not in rm or "msgCs(m.to" not in rm:
        fails.append("FROM and TO are not passed through msgCs")
    go = body_of(page, "msgGo")
    if "/api/stations/" not in go or "mapSearchGo" not in go:
        fails.append("msgGo does not look the station up and go to it")
    if "msg_cs_unknown" not in go:
        fails.append("an unknown callsign gives no answer")
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    message callsigns lead to the station's last known position")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
