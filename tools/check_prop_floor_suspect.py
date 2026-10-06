#!/usr/bin/env python3
"""Fail if the propagation floor drifts from 250 km, or a bad packet reaches
a gate's baseline or an opening.

2026-10-06 (F-2026-10-06-01, -02): against dxview's paths of 250 km or more
the map caught 13 % of 250-299 km; the 300 km floor had been set by
judgement and never calibrated (F-2026-08-12-03). Replaying 29 h of the raw
feed, a 250 km floor doubled the openings (44 -> 90 a day), and a fifth of
the flags were bad packets - a station's position jumping hundreds of km in
minutes, or a balloon whose packets carry no altitude - which also pushed
gates' bars up until four could not see below 1,000 km. The operator chose
both: floor 250, and suspect links kept out of the baseline and the
openings while staying on the map.

What must hold:

  1. StationDB.PROP_MIN_KM is 250, and no stored or displayed text says
     "300 km floor" any more (it is built from the constant)
  2. a 270 km link at a young gate is flagged and updates the gate's
     baseline
  3. a link whose sender's position jumped from its previous one at an
     impossible speed is flagged with suspect "jump" and does NOT touch the
     gate's baseline
  4. the same for a balloon (station type) - suspect "balloon"
  5. the opening grouping leaves suspect links out

Usage:  python tools/check_prop_floor_suspect.py
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


def gate_db():
    db = StationDB()
    g = StationRecord("GA1TE-10")
    g.lat, g.lon = 40.0, 30.0
    db._stations["GA1TE-10"] = g
    return db


def sender(db, call, lat, lon, prev=None, stype="house"):
    r = StationRecord(call)
    r.station_type = stype
    if prev:
        r.lat, r.lon, r.last_seen = prev
    db._stations[call] = r
    return r


def link(db, rec, lat, lon, prev):
    parsed = {"rf_direct": True, "lat": lat, "lon": lon, "gate": "GA1TE-10",
              "ts": int(NOW)}
    rec.lat, rec.lon, rec.last_seen = lat, lon, NOW
    db._ingest_prop_link(parsed, rec, prev)
    return db._prop_links[-1] if db._prop_links else None


def main() -> int:
    fails = []
    if StationDB.PROP_MIN_KM != 250.0:
        fails.append("PROP_MIN_KM is %r, expected 250" % StationDB.PROP_MIN_KM)
    for path in ("station_db.py", "static/index.html"):
        if "300 km floor" in (ROOT / path).read_text(encoding="utf-8"):
            fails.append("%s still says '300 km floor'" % path)

    # 2: 270 km north of the gate (2.43 deg of latitude), young gate
    db = gate_db()
    r = sender(db, "TA1ABC-9", 0, 0, prev=(42.4, 30.0, NOW - 600))
    try:
        l = link(db, r, 42.43, 30.0, (42.4, 30.0, NOW - 600))
    except TypeError as e:
        print("  FAIL  _ingest_prop_link does not take the previous position: %s" % e)
        print("\n1 failure(s)")
        return 1
    if not l or not (250 < l["km"] < 300):
        fails.append("a 270 km link at a young gate was not flagged: %r" % l)
    elif l.get("suspect"):
        fails.append("an ordinary link was marked suspect: %r" % l.get("suspect"))
    if db._gate_stats.get("GA1TE-10", [0])[0] != 1:
        fails.append("an ordinary link did not update the gate baseline")

    # 3: sender was 2,000 km away five minutes ago
    db = gate_db()
    r = sender(db, "TA1ABD-9", 0, 0)
    l = link(db, r, 42.43, 30.0, (60.0, 10.0, NOW - 300))
    if not l or l.get("suspect") != "jump":
        fails.append("an impossible jump was not marked: %r" % (l and l.get("suspect")))
    if "GA1TE-10" in db._gate_stats:
        fails.append("a jumped position reached the gate baseline")

    # 4: a balloon, no altitude in the packet
    db = gate_db()
    r = sender(db, "SP0BAL-9", 0, 0, stype="balloon")
    l = link(db, r, 42.43, 30.0, (42.4, 30.0, NOW - 600))
    if not l or l.get("suspect") != "balloon":
        fails.append("a balloon was not marked: %r" % (l and l.get("suspect")))
    if "GA1TE-10" in db._gate_stats:
        fails.append("a balloon reached the gate baseline")

    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    i = web.find("excluded \"\n                    f\"from opening grouping")
    grp = web[web.find("kept = []"):web.find("recent = kept")]
    if 'l.get("suspect")' not in grp:
        fails.append("the opening grouping does not leave suspect links out")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    floor 250 km; jumps and balloons flagged but kept out of baselines and openings")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
