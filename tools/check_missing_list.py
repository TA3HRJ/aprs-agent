#!/usr/bin/env python3
"""Fail if the still-off-the-air list is a wall of unlinked text again.

2026-10-05: the list held 1,692 stations - median 10 days on it, 709 over
14 days, 300 over 30 (ZS1OA at 56 days) - as plain text with nothing that
led to the map. Entries leave only when the station is heard again, on
purpose: v3.1.0 built it from the Colombia M7.4 case, where the stations
that never came back were the only ones worth looking at. So nothing is
dropped; the operator chose to keep the data and narrow the default view.

What must hold in static/index.html:

  1. the default view is the stations added in the last 7 days
     (MISS_RECENT_S), with a control to show them all, remembered per
     browser
  2. the summary line counts the recent ones and states the total
  3. a callsign leads to the station on the map and its detail
     (mapSearchGo), a cell code to its square (mapLocGo)
  4. nothing in the server changes: /api/missing still returns every entry

Usage:  python tools/check_missing_list.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    fails = []
    if not re.search(r"const MISS_RECENT_S\s*=\s*7\s*\*\s*86400", page):
        fails.append("no 7-day default window (MISS_RECENT_S)")
    rm = body_of(page, "renderMissing")
    if "MISS_RECENT_S" not in rm or "missAll" not in rm:
        fails.append("renderMissing does not narrow to recent with a show-all switch")
    if "miss_total" not in rm:
        fails.append("the summary does not state the total")
    if "localStorage" not in page[page.find("let missAll"):page.find("let missAll") + 200]:
        fails.append("the show-all choice is not remembered")
    if 'data-miss="' not in rm or 'data-loc="' not in rm:
        fails.append("rows carry no link to the station or the square")
    go = body_of(page, "missGo")
    if "mapSearchGo" not in go or "mapLocGo" not in go:
        fails.append("missGo does not lead to the station and the square")
    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    gm = web[web.find("async def get_missing"):web.find("async def get_missing") + 1500]
    if re.search(r"86400|7\s*\*\s*24", gm):
        fails.append("the server started filtering /api/missing")
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    still-off-the-air: last 7 days by default, linked, nothing dropped")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
