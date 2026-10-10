#!/usr/bin/env python3
"""Fail if the map's cluster badges stop counting the area, or count it two ways.

2026-10-10: over Europe the badges summed to about 3,000 where 29,014
stations had been heard in the last 24 h (104,699 in the registry). Below
zoom 9 the badges were bucketed in the browser from `/api/stations?limit=3000
&bbox=`, most recently heard first - the last two minutes of the area. Under
3,000 stations the same request returned the whole registry of the area, dead
stations included. One badge, two meanings, neither of them "stations here".
v3.2.42 had moved the clusters onto that request and noted "zoomed right out
both are capped and it is a wash"; it was not measured at that scale.

What must hold:

  1. StationDB.slim_clusters() buckets every station of the box heard within
     the window - no cap - and returns a count and a mean position per
     bucket, a single station as its own row
  2. stations heard longer ago than the window are not counted; stations
     without a position are not counted
  3. from zoom 9 every station is drawn, as before - a station heard ten
     days ago, or a boat whose radio came ashore four weeks ago, is part of
     what this map shows close up (the operator, 2026-10-10) - but by age:
     heard in the last 24 h full, 1-10 days half, older faint. The full ones
     are what the badge one zoom out counted
  4. /api/clusters is served on the admin and the public page, under its own
     path - /api/stations/{callsign} would take "clusters" for a callsign
  5. the map clusters from /api/clusters below zoom 9 with that 24 h window,
     and the legend says what each zoom shows

Usage:  python tools/check_map_clusters.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from station_db import StationDB, StationRecord  # noqa: E402

NOW = time.time()
DAY = 86400


def put(db, call, lat, lon, ago):
    r = StationRecord(call)
    r.lat, r.lon = lat, lon
    r.first_seen = NOW - 30 * DAY
    r.last_seen = NOW - ago
    r.packet_count = 10
    db._stations[call] = r


def main() -> int:
    fails = []
    db = StationDB()
    # 5,000 heard in the last hour in one 1-degree square, 40 heard two days
    # ago in the same square, 1 heard 3 h ago alone in another, 1 without
    # a position, 7 outside the box
    for i in range(5000):
        put(db, "AA%04d" % i, 48.1 + (i % 50) * 0.01, 11.1 + (i // 50) * 0.008, 60 + i % 3000)
    for i in range(40):
        put(db, "BB%02d" % i, 48.5, 11.5, 2 * DAY)
    put(db, "CC1", 50.5, 14.5, 3 * 3600)
    r = StationRecord("DD1")
    r.last_seen = NOW - 10
    db._stations["DD1"] = r
    for i in range(7):
        put(db, "EE%d" % i, 10.0, 10.0, 60)
    box = (45.0, 5.0, 55.0, 20.0)

    if not hasattr(db, "slim_clusters"):
        fails.append("1: StationDB has no slim_clusters()")
    else:
        clusters, total = db.slim_clusters(box, 1.0, DAY)
        if total != 5001:
            fails.append("1/2: %r counted, expected 5001 (5000 + CC1; not the 40 "
                         "two days old, not the positionless, not outside)" % total)
        big = [c for c in clusters if c.get("n", 0) > 1]
        if len(big) != 1 or big[0]["n"] != 5000:
            fails.append("1: expected one bucket of 5000, got %r" % [c.get("n") for c in big])
        elif not (48.1 <= big[0]["lat"] <= 48.6 and 11.1 <= big[0]["lon"] <= 11.9):
            fails.append("1: the bucket's position is not its stations' mean")
        single = [c for c in clusters if c.get("n") == 1]
        if len(single) != 1 or single[0].get("callsign") != "CC1":
            fails.append("1: a lone station is not returned as its own row: %r" % single)


    src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    pub = src[src.find("papp.add_routes(["):]
    if '@routes.get("/api/clusters")' not in src:
        fails.append("4: no /api/clusters route on the admin page")
    if 'web.get("/api/clusters"' not in pub:
        fails.append("4: /api/clusters is not on the public page")

    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if "/api/clusters?" not in page:
        fails.append("5: the map does not cluster from /api/clusters")
    if "max_age" in page[page.find("async function fetchViewport"):page.find("function drawViewport")]:
        fails.append("3: the zoom-9 markers are fetched with a window - close up shows every station")
    m = re.search(r"function staAgeOpacity\(r\)\{([^}]*)\}", page)
    if not m:
        fails.append("3: no staAgeOpacity() - markers are not drawn by age")
    else:
        body = m.group(1)
        if "MAP_WINDOW_S" not in body or "MAP_FADE_S" not in body:
            fails.append("3: staAgeOpacity does not use the 24 h and 10 d bounds")
        if "opacity:staAgeOpacity(r)" not in page:
            fails.append("3: addStaMarker does not set the age opacity")
    if not re.search(r"MAP_WINDOW_S=86400\b", page) or not re.search(r"MAP_FADE_S=10\*86400\b", page):
        fails.append("3: the bounds are not 24 h and 10 days")
    if page.count("leg_window:") != 2:
        fails.append("5: the legend does not say what is counted, in both languages")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    badges count every station of the area heard in the window, "
          "and the markers are the same set")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
