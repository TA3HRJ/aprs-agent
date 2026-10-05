#!/usr/bin/env python3
"""Fail if a silence alert cannot be found on the map from its own name.

2026-10-05: the alert list read "GF25 7 of 9 stations silent ...", "OK12 ...",
"ON70 ..." - plain text. Nobody can place GF25 by eye, and nothing on the
row led to the map, where the same cell is drawn with its popup. The
operator asked for a locator search and for the rows to lead to the map.

What must hold in static/index.html:

  1. locBounds() turns a Maidenhead field, square or subsquare into the
     rectangle it covers - checked here against the same arithmetic in
     Python for a spread of locators, by extracting the constants the
     function uses (20/10 degrees, 2/1, 2/24 and 1/24)
  2. the map search recognises a locator (AA, AA00, AA00aa) and offers it
     as a row of its own before any server call, so a two-letter field
     works although the callsign search wants three characters
  3. going to a locator opens the silence cell drawn there, when there is
     one (silRects), so GF25 typed in the box lands on GF25's popup
  4. every alert row leads to its cell: a click handler that calls cellGo,
     which fits the map to the cell's bounds and opens its popup

Static: there is no JavaScript runtime on the build machine. The arithmetic
is verified in the browser at release time as well.

Usage:  python tools/check_map_locator.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PAGE = Path(__file__).resolve().parent.parent / "static" / "index.html"


def py_bounds(loc: str):
    """Reference Maidenhead arithmetic: [[south, west], [north, east]]."""
    loc = loc.upper()
    lon = (ord(loc[0]) - 65) * 20 - 180
    lat = (ord(loc[1]) - 65) * 10 - 90
    w, h = 20.0, 10.0
    if len(loc) >= 4:
        lon += int(loc[2]) * 2
        lat += int(loc[3]) * 1
        w, h = 2.0, 1.0
    if len(loc) >= 6:
        lon += (ord(loc[4]) - 65) * (2 / 24)
        lat += (ord(loc[5]) - 65) * (1 / 24)
        w, h = 2 / 24, 1 / 24
    return [[lat, lon], [lat + h, lon + w]]


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
    lb = body_of(page, "locBounds")
    if not lb:
        fails.append("no locBounds()")
    else:
        for const in ("*20-180", "*10-90", "2/24", "1/24"):
            if const not in lb.replace(" ", ""):
                fails.append("locBounds() lacks the Maidenhead constant %s" % const)
    # sanity of the reference itself against known squares
    for loc, want in (("KM38", [[38, 26], [39, 28]]), ("GF25", [[-35, -56], [-34, -54]]),
                      ("OK12", [[12, 102], [13, 104]])):
        if py_bounds(loc) != want:
            fails.append("reference arithmetic wrong for %s" % loc)
    run = body_of(page, "mapSearchRun")
    if "LOC_RE" not in run or "locRow" not in run:
        fails.append("the map search does not offer a locator row")
    elif run.find("LOC_RE") > run.find("/api/search"):
        fails.append("the locator is tested after the server call, so a field "
                     "of two letters never gets there")
    if not re.search(r"const LOC_RE\s*=\s*/\^\[A-R\]\{2\}", page):
        fails.append("no LOC_RE for field/square/subsquare")
    go = body_of(page, "mapLocGo")
    if "silRects" not in go or "openPopup" not in go:
        fails.append("going to a locator does not open the cell drawn there")
    cg = body_of(page, "cellGo")
    if "fitBounds" not in cg or "openPopup" not in cg:
        fails.append("cellGo does not fit the cell and open its popup")
    ra = body_of(page, "renderAlerts")
    if "cellGo(" not in ra:
        fails.append("alert rows do not lead to their cell")
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    locators searchable, alert rows lead to their cells")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
