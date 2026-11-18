#!/usr/bin/env python3
"""Fail if a registry walk can be broken by the agent thread adding a station.

The agent runs its own event loop in a thread and adds stations to
StationDB._stations as packets arrive; the web loop walks the same dict
for the monitor, the map and the gateway's lookups. Iterating the live
dict ended the monitor loop eight times between 2026-11-05 and 2026-11-18
with "dictionary changed size during iteration" (F-2026-11-18-01); the
same class was fixed for /api/missing in F-2026-10-31-04.

What must hold (no network): each walk below iterates a snapshot, so a
station added while it runs does not raise. The test makes it
deterministic - every record touched adds a new one, as the agent thread
would between two steps.

Usage:  python tools/check_registry_snapshot.py
Exit code 1 on failure.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from station_db import StationDB  # noqa: E402


class Growing:
    """A record that, when read, makes the registry grow by one."""

    def __init__(self, db: StationDB, name: str):
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_name", name)

    def __getattr__(self, attr):
        db = object.__getattribute__(self, "_db")
        if len(db._stations) < 200:
            k = "NEW%d" % len(db._stations)
            db._stations[k] = Growing(db, k)
        if attr == "comment":
            return "x"
        if attr in ("callsign", "base_call", "ssid_call"):
            return object.__getattribute__(self, "_name")
        if attr == "to_dict":
            return lambda: {"last_seen": 0}
        if attr in ("lat", "lon", "wx_temp_c", "packet_count"):
            return 1.0
        if attr == "station_type":
            return "wx"
        return None

    def __setattr__(self, attr, value):
        pass


def fresh() -> StationDB:
    db = StationDB()
    for i in range(5):
        db._stations["SEED%d" % i] = Growing(db, "SEED%d" % i)
    return db


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "rep.json"
    tmp.write_text(json.dumps([{"callsign": "TA0XYZ"}]), encoding="utf-8")
    walks = {
        "check_transitions": lambda db: db.check_transitions(),
        "get_unanalyzed": lambda db: db.get_unanalyzed(5),
        "get_all": lambda db: db.get_all(),
        "nearest_wx": lambda db: db.nearest_wx(1.0, 1.0),
        "nearest_of_type": lambda db: db.nearest_of_type(1.0, 1.0, ("wx",)),
        "load_repeater_db": lambda db: db.load_repeater_db(str(tmp)),
    }
    bad = []
    for name, walk in walks.items():
        db = fresh()
        try:
            walk(db)
            print(f"  {name}: ok")
        except RuntimeError as e:
            print(f"  {name}: {e}")
            bad.append(name)
        except Exception as e:      # the fake record is not the point
            print(f"  {name}: {type(e).__name__} {e} (not the race; ignored)")
    if bad:
        print("\nFAIL - iterates the live registry: " + ", ".join(bad))
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
