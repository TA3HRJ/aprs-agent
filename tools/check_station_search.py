#!/usr/bin/env python3
"""Fail if the map's callsign search finds the wrong stations, or finds one
that asked not to be found.

2026-10-05: the operator asked for a search line on the map that works the
way aprs.fi's does - TA3HX* for every SSID of a call. The registry holds
~300,000 callsigns in memory; the search runs over it, not over the few
thousand the map has loaded.

What must hold:

  1. "*" is any run of characters and "?" exactly one; matching ignores case;
     a query without a wildcard is an exact callsign
  2. a query needs at least three literal characters - "*" or "TA*" would
     walk the whole registry for every keystroke of every visitor
  3. results are the newest-heard first, at most the limit, with the total
     count of matches beside them
  4. a station with no position is still found, marked has_position false
  5. a station that sent NOLOOKUP to the gateway is left out: the Data note
     promises it is left out of other people's lookups, and a search is one
  6. /api/search is served by the admin and the public app alike, the page
     has the search box and calls it, and the route is not under
     /api/stations/ where {callsign} would swallow it

Usage:  python tools/check_station_search.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from station_db import StationDB, StationRecord  # noqa: E402

NOW = time.time()


def rec(db, call, ago, pos=True):
    r = StationRecord(call)
    if pos:
        r.lat, r.lon = 38.4, 27.1
    r.last_seen = NOW - ago
    db._stations[call] = r


def main() -> int:
    fails = []
    import station_db
    q = getattr(station_db, "callsign_query", None)
    db = StationDB()
    if q is None or not hasattr(db, "search"):
        fails.append("station_db has no callsign_query() / StationDB.search()")
    else:
        for call, ago, pos in (("TA3HX", 50, True), ("TA3HX-7", 10, True),
                               ("TA3HX-10", 30, False), ("TA3HXA", 20, True),
                               ("TA3HRJ-5", 5, True), ("XTA3HX", 1, True),
                               ("TA1ABC-9", 2, True)):
            try:
                rec(db, call, ago, pos)
            except Exception as e:
                fails.append("could not build a fixture station %s: %s" % (call, e))
        cases = (
            ("TA3HX*", {"TA3HX", "TA3HX-7", "TA3HX-10", "TA3HXA"}),
            ("ta3hx-7", {"TA3HX-7"}),
            ("TA3HX", {"TA3HX"}),
            ("TA3HX-?", {"TA3HX-7"}),
            ("*TA3HX", {"TA3HX", "XTA3HX"}),
        )
        for query, want in cases:
            total, res = db.search(query, set(), 20)
            got = {r["callsign"] for r in res}
            if got != want:
                fails.append("%r found %s, expected %s" % (query, sorted(got), sorted(want)))
            elif total != len(want):
                fails.append("%r total %d, expected %d" % (query, total, len(want)))
        for bad in ("*", "TA*", "??*", ""):
            if q(bad) is not None:
                fails.append("%r accepted: fewer than three literal characters" % bad)
        total, res = db.search("TA3HX*", set(), 20)
        order = [r["callsign"] for r in res]
        if order[:1] != ["TA3HX-7"]:
            fails.append("not newest first: %s" % order)
        total, res = db.search("TA3HX*", set(), 2)
        if len(res) != 2 or total != 4:
            fails.append("limit 2: got %d results, total %d" % (len(res), total))
        total, res = db.search("TA3HX-10", set(), 20)
        if not res or res[0].get("has_position") is not False:
            fails.append("a station with no position is not marked: %r" % res)
        total, res = db.search("TA3HX*", {"TA3HX"}, 20)
        if any(r["callsign"].split("-")[0] == "TA3HX" for r in res):
            fails.append("a NOLOOKUP callsign was found: %s" % [r["callsign"] for r in res])

    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    if '@routes.get("/api/search")' not in web:
        fails.append("admin app does not serve /api/search")
    if 'web.get("/api/search", search_stations)' not in web:
        fails.append("public app does not serve /api/search")
    if "/api/stations/search" in web:
        fails.append("search sits under /api/stations/, where {callsign} catches it")
    if "_OPTOUT_FILE" not in web:
        fails.append("the search does not read the NOLOOKUP list")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if 'id="map-search"' not in page or "/api/search?q=" not in page:
        fails.append("the map has no search box calling /api/search")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    wildcard search: aprs.fi semantics, newest first, NOLOOKUP honoured")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
