#!/usr/bin/env python3
"""Fail if a station's position stops following its packets.

Since v2.7.0 the registry kept the first position a station was ever heard
at. On 2026-11-19 the operator's LoRa tracker TA3HX-8 sent 92 positions in
18 h, all 31 km west of where the map drew it - at home, where it was first
heard on 2026-09-24. Measured on the live feed the same day: 493 of 28,804
silence sensors sat in the wrong square, 147 of them more than 1,000 km from
where they transmit from (F-2026-11-19-01).

What must hold (no network):

  1. a station not in the repeater database is where its latest position
     packet says, lat, lon and locator together
  2. a packet without a position (status, telemetry) leaves it where it is
  3. a station matched to the repeater database keeps its position
  4. the propagation check's "previous position" is the last one heard, so a
     station that moved once is not a position jump on every packet after
  5. the latest position is what a save and a load restore

Usage:  python tools/check_position_update.py
Exit code 1 on failure.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from station_db import StationDB  # noqa: E402

GATE = "APLRT1,WIDE1-1,qAR,TA3HX-11"


def pos(call, lat, lon, sym="s", table="/", comment=""):
    return f"{call}>{GATE}:!{lat}{table}{lon}{sym}{comment}"


def main() -> int:
    p = []
    db = StationDB()

    # 1-2: the tracker, first heard at home, then at the boat
    db.ingest(pos("TA3HX-8", "3827.16N", "02706.46E"))
    r = db._stations["TA3HX-8"]
    home = (r.lat, r.lon, r.locator)
    db.ingest(pos("TA3HX-8", "3823.76N", "02644.95E"))
    now = (r.lat, r.lon, r.locator)
    print(f"  tracker: first {home}, after it moved {now}")
    if abs((r.lat or 0) - 38.396) > 0.01 or abs((r.lon or 0) - 26.749) > 0.01:
        p.append(f"the tracker stayed at its first position {now[:2]}")
    if not r.locator.upper().startswith("KM38IJ"):
        p.append(f"the locator did not move with the position ({r.locator})")
    db.ingest(f"TA3HX-8>{GATE}:>status text, no position")
    if (r.lat, r.lon, r.locator) != now:
        p.append("a packet without a position moved the station")

    # 3: a station matched to the repeater database keeps its position
    tmp = Path(tempfile.mkdtemp())
    rep = tmp / "repeaters.json"
    rep.write_text(json.dumps([{"callsign": "YM2KA", "city": "Istanbul",
                                "frequency": 145.6, "lat": 41.10, "lon": 29.00,
                                "mode": "FM", "band": "2m"}]), encoding="utf-8")
    db.load_repeater_db(str(rep))
    db.ingest(pos("YM2KA", "4106.00N", "02900.00E", sym="r"))
    rr = db._stations["YM2KA"]
    before = (rr.lat, rr.lon)
    db.ingest(pos("YM2KA", "3900.00N", "03500.00E", sym="r"))
    print(f"  matched repeater: matched={rr.db_record is not None} "
          f"{before} -> {(rr.lat, rr.lon)}")
    if rr.db_record is None:
        p.append("the repeater was not matched (fixture)")
    elif (rr.lat, rr.lon) != before:
        p.append("a station matched to the repeater database moved")

    # 4: the previous position handed to the propagation check
    seen = []
    orig = db._ingest_prop_link

    def spy(parsed, rec, prev=None):
        if rec.callsign == "TA3HX-8":
            seen.append(prev)
        return orig(parsed, rec, prev)

    db._ingest_prop_link = spy
    db.ingest(pos("TA3HX-8", "3823.77N", "02644.96E"))
    prev = seen[-1] if seen else None
    print(f"  previous position for the propagation check: {prev and prev[:2]}")
    if not prev or abs(prev[0] - 38.396) > 0.01:
        p.append(f"the propagation check compared against {prev and prev[:2]}, "
                 f"not the last position heard")

    # 5: persisted
    path = str(tmp / "s.db")
    db.save_sqlite(path)
    back = StationDB()
    back.load_sqlite(path)
    b = back._stations["TA3HX-8"]
    if abs((b.lat or 0) - 38.396) > 0.01:
        p.append(f"a load restored {(b.lat, b.lon)}, not the latest position")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
