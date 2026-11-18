#!/usr/bin/env python3
"""Fail if the minute flush rewrites the whole station registry, or loses data.

Once a minute the agent persists the registry to SQLite. It rewrote every
row: 252,427 took 10-18 s with the write lock held in September
(F-2026-09-15-01), and the registry held 419,192 rows on 2026-11-18, while
only the stations heard that minute had changed (F-2026-11-18-02).

What must hold (no network):

  1. an incremental flush writes only the stations heard since the last
     flush; a second one with nothing heard writes nothing
  2. what it writes is on disk: a fresh load sees the new packet count
  3. a change made outside a packet (an AI note) goes on the next full
     flush, and a full flush writes every station
  4. records loaded from disk are not rewritten by the first incremental
     flush after a start
  5. the persist loop asks for a full flush once an hour, not every minute

Usage:  python tools/check_registry_flush.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from station_db import StationDB  # noqa: E402


def line(call: str, n: int) -> str:
    return (f"{call}>APRS,TCPIP*,qAC,T2TEST:!41{n % 60:02d}.00N/029"
            f"{n % 60:02d}.00E-test {n}")


def save(db: StationDB, path: str, full: bool) -> int:
    try:
        return db.save_sqlite(path, full)
    except TypeError:                       # no incremental flush at all
        return db.save_sqlite(path)


def main() -> int:
    p = []
    path = str(Path(tempfile.mkdtemp()) / "s.db")
    db = StationDB()
    for i in range(300):
        db.ingest(line(f"TA{i:04d}", i))
    n_all = save(db, path, True)

    db.ingest(line("TA0007", 7))
    db.ingest(line("TA0042", 42))
    db.ingest(line("TA0042", 43))
    n_inc = save(db, path, False)
    n_idle = save(db, path, False)
    print(f"  full flush {n_all} rows; after 3 packets from 2 stations "
          f"{n_inc}; with nothing heard {n_idle}")
    if n_all != 300:
        p.append(f"a full flush wrote {n_all} of 300 stations")
    if n_inc != 2:
        p.append(f"an incremental flush wrote {n_inc} rows, expected 2")
    if n_idle != 0:
        p.append(f"a flush with nothing heard wrote {n_idle} rows")

    back = StationDB()
    back.load_sqlite(path)
    pc = back._stations["TA0042"].packet_count
    if pc != 3:
        p.append(f"the incremental flush did not reach disk (TA0042 "
                 f"packet_count {pc}, expected 3)")

    db._stations["TA0100"].ai_org = "Test Radio Club"
    save(db, path, False)
    org = sqlite3.connect(path).execute(
        "select ai_org from stations where callsign='TA0100'").fetchone()[0]
    n_full = save(db, path, True)
    org2 = sqlite3.connect(path).execute(
        "select ai_org from stations where callsign='TA0100'").fetchone()[0]
    print(f"  AI note without a packet: after incremental {org!r}, after "
          f"full {org2!r} ({n_full} rows)")
    if org2 != "Test Radio Club" or n_full != 300:
        p.append("a full flush did not write every station")

    n_first = save(back, path, False)
    print(f"  first incremental flush after a load: {n_first} rows")
    if n_first != 0:
        p.append(f"a load marks {n_first} stations as unsaved")

    src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    m = re.search(r"save_sqlite, mgr\._sta_db_path,\s*\n?\s*tick % (\d+) == 0",
                  src)
    if not m or m.group(1) != "60":
        p.append("the persist loop does not flush in full hourly and "
                 "incrementally in between")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
