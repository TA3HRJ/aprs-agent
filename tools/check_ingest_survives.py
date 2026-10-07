#!/usr/bin/env python3
"""Fail if one packet can stop the agent from hearing the rest.

F-2026-10-07-04: v3.2.158 reused the name `prev` in StationDB.ingest() for a
timestamp, where it already held the station's previous position for the
propagation check. The first packet gated over RF by a gate with a known
position raised TypeError, and the exception ended broadcast_logs, the task
that feeds every packet to the registry, the map and the stats. Live from
11:02 to ~15:30 on 2026-10-07 the agent stayed connected and counted 0
packets. check_unheard_time.py ingested packets too - from gates nobody had
heard, so the propagation path never ran.

What must hold:

  1. ingest() of qAR-gated packets from a station that moves, through a gate
     with a known position, raises nothing and records the link's sender
  2. AgentManager._ingest_line() keeps a failing packet to itself: no
     exception escapes, and the failure is counted by type
  3. broadcast_logs() calls the trackers inside a try, so the log stream
     outlives a tracking failure

Usage:  python tools/check_ingest_survives.py
Exit code 1 on failure.
"""
from __future__ import annotations

import inspect
import io
import sys
import types
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402


def main() -> int:
    fails = []

    # 1 · the propagation path, with a previous position to compare against
    db = station_db_module.StationDB()
    try:
        db.ingest("TA1GAT-10>APRS,TCPIP*,qAC,T2TEST:!3900.00N/03200.00E&gate")
        for lat in ("3910.00N", "3920.00N", "3930.00N"):
            db.ingest("TA2MOV-9>APRS,WIDE1-1,qAR,TA1GAT-10:!%s/03300.00E>moving"
                      % lat)
        db.ingest("TA3FAR>APRS,qAR,TA1GAT-10:!4100.00N/03600.00E#far")
    except Exception as e:
        fails.append("ingest raised on a gated packet: %s: %s"
                     % (type(e).__name__, e))
    if db._stations.get("TA2MOV-9") is None or \
            db._stations["TA2MOV-9"].packet_count != 3:
        fails.append("the moving station was not recorded three times")

    # 2 · a failing packet stays with that packet
    class Boom:
        def ingest(self, raw, own=False):
            raise TypeError("boom")
    m = types.SimpleNamespace(_station_db=Boom(), _ingest_errors={})
    if not hasattr(web_gui.AgentManager, "_ingest_line"):
        fails.append("no AgentManager._ingest_line")
    else:
        try:
            with redirect_stderr(io.StringIO()):
                web_gui.AgentManager._ingest_line(m, "X>Y:z")
                web_gui.AgentManager._ingest_line(m, "X>Y:z")
            if m._ingest_errors.get("TypeError") != 2:
                fails.append("failures not counted: %r" % m._ingest_errors)
        except Exception as e:
            fails.append("_ingest_line let %s escape" % type(e).__name__)

    # 3 · the log task survives a tracking failure
    src = inspect.getsource(web_gui.AgentManager.broadcast_logs)
    i = src.find("self._track_stations(text)")
    if i < 0 or "try:" not in src[max(0, i - 200):i]:
        fails.append("broadcast_logs calls _track_stations outside a try")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    a gated packet ingests; one bad packet cannot stop the log task")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
