#!/usr/bin/env python3
"""Fail if the map can change size without Leaflet being told.

2026-10-07: on the admin page, with the settings column hidden by the gear
button, the right ~360 px of the map stayed black - markers drawn, no tiles.
Leaflet measures its box once and then listens only to the window's resize
event. The gear hides the column with a class on <body>, the window does not
change, and Leaflet went on believing the map was 900 px wide in a 1280 px
box. Reproduced in the browser: box 1280, map.getSize().x 900, tiles ending
at 905.

The gear is not the only thing that resizes the map without the window: the
alert and still-off-the-air lists open above it. So the fix is not a call in
toggleSidebar() but a ResizeObserver on the map's own box, which catches
every cause, present and future.

What must hold:

  1. initMap() observes the #map element with a ResizeObserver that calls
     map.invalidateSize()
  2. the observer is created once, with the map, not on every initMap() call

Usage:  python tools/check_map_resize.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    fails = []
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    i = page.find("function initMap(){")
    body = page[i:page.find("\nfunction ", i + 10)] if i >= 0 else ""
    if not body:
        fails.append("initMap() not found")
    obs = re.search(r"new ResizeObserver\(\s*\(\)\s*=>\s*map\.invalidateSize\(\)\s*\)"
                    r"\.observe\(\s*\$\('map'\)\s*\)", body)
    if not obs:
        fails.append("initMap() does not observe #map with a ResizeObserver "
                     "calling map.invalidateSize()")
    else:
        created = body.find("map=L.map(")
        early = body.find("if(map){")
        ret = body.find("return}", early) if early >= 0 else -1
        if created < 0 or obs.start() < created or (0 <= early < obs.start() < ret):
            fails.append("the observer is not created once, after the map")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    the map's own box is observed; Leaflet hears every resize")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
