#!/usr/bin/env python3
"""Fail if the repeater database is matched to stations that are not the
repeater, or overwrites what a station says about itself; or if the station
analysis keeps the text "null" or a bare callsign as an organisation.

F-2026-10-20-03: a listing was matched by callsign without SSID, so a
club's weather station, igate and digis took the repeater's record - its
position, frequency and the type "repeater" - and the monitor would have
reported them as the repeater going quiet. Of 71 stations matched on the
live registry, 9 were repeaters.
F-2026-10-21-01: 38 stored analyses read "null"; 16 % of the organisations
found were only a callsign.

What must hold:

  1. a listing with an SSID (TA6ATA-L) matches that callsign only
  2. a listing without one (YM2KA) matches only a station whose own symbol
     is a repeater; the club's weather station and igate stay unmatched,
     keep their type and position
  3. a matched repeater that beacons keeps its own position and gets the
     listing's frequency and tone; one without a position takes the DB's
  4. the same rule applies to stations already in memory when the DB loads
  5. the monitor's transitions only ever name matched stations
  6. "null"/"none" and a bare callsign are not kept as an organisation, for
     a new answer and for rows already stored (cleaned on load)

Usage:  python tools/check_repeater_match.py
Exit code 1 on failure.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db  # noqa: E402
from station_db import StationDB  # noqa: E402

DB = [
    {"callsign": "YM2KA", "city": "Istanbul", "frequency": 145.6, "tone": "88.5",
     "lat": 41.10, "lon": 29.00, "mode": "FM", "band": "2m"},
    {"callsign": "TA6ATA-L", "city": "Antalya", "frequency": 439.1, "tone": "79.7",
     "lat": 36.90, "lon": 30.70, "mode": "FM", "band": "70cm"},
]


def line(call, table, sym, lat="4058.00N", lon="02855.00E", comment="test"):
    return f"{call}>APRS,TCPIP*,qAC,T2TEST:!{lat}{table}{lon}{sym}{comment}"


def main() -> int:
    p = []
    tmp = Path(tempfile.mkdtemp())
    dbfile = tmp / "repeaters.json"
    dbfile.write_text(json.dumps(DB), encoding="utf-8")

    # stations heard before the DB loads (item 4) and after (items 1-3)
    sdb = StationDB()
    sdb.ingest(line("YM2KA-13", "/", "_"))            # club weather station
    sdb.load_repeater_db(str(dbfile))
    sdb.ingest(line("YM2KA-1", "/", "I"))             # club igate
    sdb.ingest(line("YM2KA-5", "/", "r", lat="4106.00N", lon="02901.00E"))
    sdb.ingest(line("TA6ATA-L", "/", "r", lat="3654.00N", lon="03042.00E"))
    sdb.ingest(line("TA6ATA", "/", "r"))              # listing is -L only
    st = sdb._stations

    for call in ("YM2KA-13", "YM2KA-1", "TA6ATA"):
        r = st[call]
        print(f"  {call:<9} matched={r.db_record is not None} type={r.station_type} "
              f"pos=({r.lat:.3f},{r.lon:.3f})")
        if r.db_record is not None:
            p.append(f"{call} matched the repeater listing")
    if st["YM2KA-13"].station_type != "weather" or abs(st["YM2KA-13"].lat - 40.967) > 0.01:
        p.append("the club weather station lost its type or position")
    for call, lat in (("YM2KA-5", 41.10), ("TA6ATA-L", 36.90)):
        r = st[call]
        print(f"  {call:<9} matched={r.db_record is not None} freq={r.freq_mhz} "
              f"pos=({r.lat:.3f},{r.lon:.3f})")
        if r.db_record is None:
            p.append(f"{call} (repeater symbol / exact listing) not matched")
        elif r.freq_mhz is None or abs(r.lat - lat) > 0.01:
            p.append(f"{call}: frequency missing or own position replaced")

    # a repeater heard before it sent any position takes the DB's
    nopos = StationDB()
    nopos.load_repeater_db(str(dbfile))
    nopos.ingest("YM2KA-9>APRS,TCPIP*,qAC,T2TEST:>status only")
    r = nopos._stations["YM2KA-9"]
    r.station_type = "repeater"
    e = getattr(nopos, "_db_entry", lambda _r: None)(r)
    if e:
        r.update_from_db(e)
    if r.lat is None or abs(r.lat - 41.10) > 0.001:
        p.append(f"a matched repeater without a position did not take the DB's: {r.lat}")

    # 5: transitions name matched stations only
    sdb.check_transitions()
    for r in st.values():
        r.last_seen = time.time() - 30 * 86400
    names = [r.callsign for r, _ in sdb.check_transitions()]
    print(f"  transitions -> {sorted(names)}")
    if set(names) - {"YM2KA-5", "TA6ATA-L"}:
        p.append(f"the monitor would report unmatched stations: {names}")

    # 6: the analysis cleaners, and rows already stored (before the rule
    # existed, whatever the model said was kept as it was)
    keep = lambda v: str(v or "").strip()  # noqa: E731
    clean_org = getattr(station_db, "clean_ai_org", keep)
    clean_desc = getattr(station_db, "clean_ai_description", keep)
    for v, want in (("null", ""), ("None", ""), ("HS5AC", ""), ("YM2KA-1", ""),
                    ("Radio Club Region de Murcia", "Radio Club Region de Murcia"),
                    ("ORARI", "ORARI")):
        got = clean_org(v)
        if got != want:
            p.append(f"clean_ai_org({v!r}) = {got!r}")
    if clean_desc("null") != "":
        p.append("a 'null' description is kept")
    path = str(tmp / "s.db")
    st["YM2KA-1"].ai_org, st["YM2KA-1"].ai_description = "null", "null"
    st["YM2KA-13"].ai_org = "BG6STN"
    sdb.save_sqlite(path)
    back = StationDB()
    back.load_sqlite(path)
    stored = sqlite3.connect(path).execute(
        "select callsign, ai_org, ai_description from stations "
        "where callsign in ('YM2KA-1','YM2KA-13')").fetchall()
    print(f"  stored before the rule -> {stored}")
    loaded = {c: (back._stations[c].ai_org, back._stations[c].ai_description)
              for c in ("YM2KA-1", "YM2KA-13")}
    print(f"  after load             -> {loaded}")
    if any(v for pair in loaded.values() for v in pair):
        p.append(f"stored 'null' / callsign rows survive a load: {loaded}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
