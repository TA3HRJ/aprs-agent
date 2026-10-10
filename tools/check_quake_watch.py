#!/usr/bin/env python3
"""Fail if the quake-anchored watch stops measuring what it was built to.

2026-10-10 (F-2026-10-10-01, -02): the Panama M7.7 silenced 10 of 85 fixed
stations within 300 km in the hour after it, against 1.5 expected from the
rest of the world at the same moment (p = 3e-6), spread over four cells none
of which met the cell rule. Replayed over 300 random places and times, the
same test passed p < 1e-4 once. The watch counts it per quake; the map shows
it for USGS PAGER yellow and above (the operator's choice: map only).

What must hold:

  1. StationDB.quake_watch_scan() counts fixed stations within the radius
     that were on the air when the quake struck (heard within their own
     threshold before it, known before it) and, cumulatively over its scans,
     the ones that went quiet past their own threshold; the comparison is
     every such station farther than 1,000 km
  2. mobiles, stations silent before the quake and stations first heard after
     it are not counted
  3. a station that went quiet and came back stays counted, and is counted
     as back
  4. unusual = at least 5 quiet and binomial p < 1e-4; a quiet region is not
  5. a scan while the agent cannot hear judges nothing and marks the watch
     interrupted, and an interrupted watch is never called unusual
  6. /api/silence publishes watches for PAGER yellow, orange and red only;
     the radius is 150 km below M7, 300 km to M7.9, 500 km from M8
  7. the map draws them, in both languages, and HELP explains them in both

Usage:  python tools/check_quake_watch.py
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
T = NOW - 3600
P = (7.59, -80.77)


def put(db, call, lat, lon, last_ago, stype="digi", first_ago=30 * 86400):
    r = StationRecord(call)
    r.lat, r.lon = lat, lon
    r.locator = "EJ97"
    r.station_type = stype
    r.ema_interval_s = 600.0                     # threshold 30 min
    r.packet_count = 200
    r.first_seen = NOW - first_ago
    r.last_seen = NOW - last_ago
    db._stations[call] = r
    return r


def world(near_quiet, far_quiet=2):
    db = StationDB()
    db.started_ts = NOW - 86400
    db.last_ingest_ts = NOW - 5
    for i in range(20):                          # 20 on the air near P
        quiet = i < near_quiet
        put(db, "HP1N%02d" % i, P[0] + 0.01 * i, P[1], 3300 if quiet else 60)
    for i in range(200):                         # 200 far away, ~2000 km
        put(db, "XX1F%03d" % i, 25.0 + 0.01 * i, -100.0,
            3300 if i < far_quiet else 60)
    put(db, "HP1MOB", P[0], P[1] + 0.1, 3300, stype="car")
    put(db, "HP1DEAD", P[0], P[1] + 0.2, 3 * 3600)          # gone before it
    put(db, "HP1NEW", P[0], P[1] + 0.3, 3300, first_ago=1800)
    return db


def watch():
    return {"id": "t1", "lat": P[0], "lon": P[1], "ts": T, "radius_km": 300.0}


def main() -> int:
    fails = []
    db = StationDB()
    if not hasattr(db, "quake_watch_scan"):
        fails.append("1: StationDB has no quake_watch_scan()")
    else:
        db = world(near_quiet=8)
        w = watch()
        db.quake_watch_scan([w], NOW)
        r = w.get("result") or {}
        if r.get("n") != 20 or r.get("k") != 8:
            fails.append("1/2: n=%r k=%r, expected 20 and 8 (mobile, gone-before "
                         "and first-heard-after left out)" % (r.get("n"), r.get("k")))
        if not r.get("unusual"):
            fails.append("4: 8 of 20 quiet against 1 %% elsewhere is not unusual: %r" % r)
        if "HP1MOB" in (r.get("quiet_calls") or []):
            fails.append("2: a mobile is counted")

        # 3: one of the eight comes back; the next scan keeps it, as back
        db._stations["HP1N00"].last_seen = NOW - 10
        db.quake_watch_scan([w], NOW + 60)
        r = w.get("result") or {}
        if r.get("k") != 8 or r.get("back") != 1:
            fails.append("3: after one came back k=%r back=%r, expected 8 and 1"
                         % (r.get("k"), r.get("back")))

        db = world(near_quiet=0)
        w = watch()
        db.quake_watch_scan([w], NOW)
        if (w.get("result") or {}).get("unusual"):
            fails.append("4: a region where nobody went quiet is unusual")

        db = world(near_quiet=8)
        db.last_ingest_ts = NOW - 3600           # deaf for an hour
        w = watch()
        db.quake_watch_scan([w], NOW)
        if not w.get("interrupted"):
            fails.append("5: a deaf scan does not mark the watch interrupted")
        if (w.get("result") or {}).get("unusual"):
            fails.append("5: a scan while deaf called the region unusual")

    try:
        import web_gui as wg
        ws = [dict(watch(), id=a, alert=a, mag=7.7, place="x",
                   result={"n": 1, "k": 0, "unusual": False})
              for a in ("green", None, "yellow", "orange", "red")]
        pub = [x["id"] for x in wg._quake_watch_public(ws)]
        if pub != ["yellow", "orange", "red"]:
            fails.append("6: published %r, expected yellow, orange, red" % pub)
        radii = [wg._quake_watch_radius(m) for m in (6.0, 6.9, 7.0, 7.9, 8.0)]
        if radii != [150.0, 150.0, 300.0, 300.0, 500.0]:
            fails.append("6: radius by magnitude %r" % radii)
    except (ImportError, AttributeError) as e:
        fails.append("6: %s" % e)

    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if "function renderQuakeWatch" not in page:
        fails.append("7: the map has no renderQuakeWatch")
    if page.count("qw_title:") != 2:
        fails.append("7: qw_title is not in both languages (%d)" % page.count("qw_title:"))
    help_ = (ROOT / "HELP.html").read_text(encoding="utf-8")
    if 'id="quake-tr"' not in help_ or 'id="quake-en"' not in help_:
        fails.append("7: HELP does not explain the quake watch in both languages")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    counted around the quake, against the rest of the world, "
          "shown for PAGER yellow and above")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
