#!/usr/bin/env python3
"""Fail if the page shows a stored timestamp as a bare clock time.

2026-10-04: the Messages tab, in its 14-day "Kept" view, showed rows from
2 and 3 October side by side as 20:44 and 00:34 with no date. Nobody could
tell which conversation came first, or that they were a day apart. The
station detail's "first seen" (often weeks ago) and the off-the-air list's
"last seen" had the same fault.

What must hold in static/index.html:

  1. toLocaleTimeString appears in exactly one place: fmtClock
  2. fmtClock also calls toLocaleDateString, so an older stamp carries its
     date - and it compares against today, so today's rows stay short
  3. the three stamps above go through fmtClock

Static on purpose: there is no JavaScript runtime on the build machine.

Usage:  python tools/check_timestamp_date.py
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
    src = PAGE.read_text(encoding="utf-8")
    fails = []
    fn = body_of(src, "fmtClock")
    if not fn:
        fails.append("fmtClock is gone")
    outside = src.replace(fn, "") if fn else src
    n = outside.count("toLocaleTimeString")
    if n:
        fails.append("toLocaleTimeString used outside fmtClock (%d place(s)) - "
                     "a clock time with no date" % n)
    if fn and "toLocaleDateString" not in fn:
        fails.append("fmtClock never shows a date")
    if fn and "toDateString" not in fn:
        fails.append("fmtClock does not compare with today")
    for label, pat in (("Messages row", r"fmtClock\(m\.ts\)"),
                       ("off-the-air last seen", r"fmtClock\(m\.last_seen\)"),
                       ("station first seen", r"fmtClock\(r\.first_seen\)")):
        if not re.search(pat, src):
            fails.append("%s does not go through fmtClock" % label)
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    every stored timestamp carries its date when it is not today")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
