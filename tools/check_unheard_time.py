#!/usr/bin/env python3
"""Fail if time the agent did not listen is counted as a station's silence.

F-2026-10-07-02: on 2026-10-07 the host came up without a network for 5 h
40 min. `last_ingest_ts` is 0 until the first packet, and the deaf guard
read 0 as "not deaf", so a process that never heard anything judged
everyone: 776 `[silence] ALERT` lines, ~8,000 false missing-list entries,
26 history snapshots of alerts that never happened. When the feed returned,
every station was judged against a packet from before the outage - 1,355
cells met the rule at 09:16.

What must hold (StationDB and web_gui._heard_again, on a fake clock):

  1. a process up longer than _DEAF_AFTER_S that has heard nothing is deaf,
     dated from its start, and silence_cells() refuses; one up 100 s is not
     (the offline checks build a registry and judge it at once)
  2. after a break - the newest stored packet, or this process's own last
     one, more than _DEAF_AFTER_S before the next packet - a station's
     silence clock starts at the end of the break: right after it nothing
     is silent, after the station's threshold of listening it is, dated
     from the end of the break plus the threshold; and across two breaks
     the stretch between them is not enough on its own
  3. a station that had crossed its threshold before the break began keeps
     its silence; one heard after the break is judged as always
  4. started after a break and no packet yet: nobody is silent
  5. a quick restart (no break) changes nothing
  6. silence_state() calls a station not yet listened for since a break, or
     anything while deaf, `unknown`, and _heard_again() keeps it on the
     missing list; heard again it leaves
  7. the agent's own beacon does not make a deaf agent hear
  8. what a deaf process recorded leaves the record and nothing else does:
     missing-list entries flagged inside a _DEAF_PERIODS window (kept under
     `missing_voided`), episodes started in it, and history snapshots in it
     (moved to `silence_history_void`); a second start moves nothing

Usage:  python tools/check_unheard_time.py
Exit code 1 on failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402
from packet_parser import _latlon_to_locator  # noqa: E402

LAT, LON = 39.0, 32.0
T0 = 1_800_000_000.0
_real_time = time.time
clock = [T0]


def fake_time() -> float:
    return clock[0]


def rec(call: str, last_seen: float) -> "station_db_module.StationRecord":
    r = station_db_module.StationRecord(call)
    r.lat, r.lon = LAT, LON
    r.locator = _latlon_to_locator(LAT, LON)
    r.ema_interval_s = 600.0            # threshold 1,800 s
    r.packet_count = 50
    r.station_type = "digipeater"
    r.first_seen = last_seen - 86400
    r.last_seen = last_seen
    return r


def packet(call: str) -> str:
    return "%s>APRS,TCPIP*,qAC,T2TEST:!3900.00N/03200.00E#test" % call


def hear(db, t: float) -> None:
    """Move the clock and keep the feed alive: one unrelated packet."""
    clock[0] = t
    db.ingest(packet("TA9ZZZ-1"))


def silent_calls(db) -> set:
    out = set()
    for c in db.silence_cells(min_history=5, min_silent=1, min_ratio=0.0):
        out.update(c["silent_calls"])
    return out


def main() -> int:
    fails = []
    time.time = fake_time
    tmp = tempfile.mkdtemp()
    try:
        D = station_db_module.StationDB._DEAF_AFTER_S

        # 1 · never heard a packet
        clock[0] = T0
        db = station_db_module.StationDB()
        db._stations["TA1AAA-1"] = rec("TA1AAA-1", T0 - 5000)
        clock[0] = T0 + 100
        if db.deaf_since():
            fails.append("deaf 100 s after start - the offline checks would stop judging")
        clock[0] = T0 + D + 60
        if db.deaf_since() != T0:
            fails.append("up %d s, nothing heard, deaf_since()=%r - expected its start"
                         % (D + 60, db.deaf_since()))
        if db.silence_cells():
            fails.append("judged silence with nothing heard since start")

        # 2-4 · a break between the stored registry and the first packet
        clock[0] = T0
        old = station_db_module.StationDB()
        old._stations["TA1AAA-1"] = rec("TA1AAA-1", T0 - 60)     # fine before
        old._stations["TA2BBB-1"] = rec("TA2BBB-1", T0 - 60)     # fine before
        old._stations["TA3CCC-1"] = rec("TA3CCC-1", T0 - 4000)   # silent before
        old._stations["TA4DDD-1"] = rec("TA4DDD-1", T0)          # newest stored
        path = os.path.join(tmp, "a.db")
        old.save_sqlite(path)

        gap_end = T0 + 6 * 3600
        clock[0] = gap_end
        db = station_db_module.StationDB()
        db.load_sqlite(path)
        # 4 · up, nothing heard yet, after a 6 h break
        s = silent_calls(db) - {"TA3CCC-1"}
        if s:
            fails.append("before the first packet after a break, judged silent: %s"
                         % sorted(s))
        db.ingest(packet("TA9ZZZ-1"))
        hear(db, gap_end + 120)
        s = silent_calls(db)
        if s - {"TA3CCC-1"}:
            fails.append("2 min after a 6 h break, judged silent on time nobody "
                         "listened: %s" % sorted(s - {"TA3CCC-1"}))
        if "TA3CCC-1" not in s:
            fails.append("a station silent before the break lost its silence")
        st = db.silence_state(["TA1AAA-1", "TA3CCC-1"])
        a = st.get("TA1AAA-1") or {}
        if a.get("silent") or not a.get("unknown"):
            fails.append("not yet listened for since the break, silence_state "
                         "gave silent=%r unknown=%r - expected unknown"
                         % (a.get("silent"), a.get("unknown")))
        if not web_gui._heard_again(None) or web_gui._heard_again(a or None):
            fails.append("_heard_again() let an unknown station off the missing list")
        c3 = st.get("TA3CCC-1") or {}
        if not c3.get("silent") or c3.get("since") != int(T0 - 4000 + 1800):
            fails.append("silent before the break: silent=%r since=%r"
                         % (c3.get("silent"), c3.get("since")))

        # 3 · heard after the break: judged as always
        db.ingest(packet("TA2BBB-1"))
        hear(db, gap_end + 600)
        hear(db, gap_end + 1200)
        hear(db, gap_end + 1750)
        hear(db, gap_end + 1900)
        s = silent_calls(db)
        st = db.silence_state(["TA1AAA-1", "TA2BBB-1"])
        a, b = st.get("TA1AAA-1") or {}, st.get("TA2BBB-1") or {}
        if "TA1AAA-1" not in s or not a.get("silent") or a.get("unknown"):
            fails.append("listened for longer than its threshold and not heard, "
                         "still not silent")
        elif a.get("since") != int(gap_end + 1800):
            fails.append("silence dated %r - expected the end of the break plus "
                         "the threshold, %r" % (a.get("since"), int(gap_end + 1800)))
        if b.get("silent") or b.get("unknown") or not web_gui._heard_again(b):
            fails.append("heard after the break, yet silent=%r unknown=%r"
                         % (b.get("silent"), b.get("unknown")))

        # 2 · a deaf spell inside one process
        clock[0] = T0
        db = station_db_module.StationDB()
        db._stations["TA1AAA-1"] = rec("TA1AAA-1", T0 - 60)
        db.ingest(packet("TA9ZZZ-1"))
        clock[0] = T0 + 3 * 3600
        if not db.deaf_since():
            fails.append("3 h without a packet, not deaf")
        st = db.silence_state(["TA1AAA-1"]).get("TA1AAA-1") or {}
        if st.get("silent") or not st.get("unknown"):
            fails.append("while deaf, silence_state gave silent=%r unknown=%r"
                         % (st.get("silent"), st.get("unknown")))
        db.ingest(packet("TA9ZZZ-1"))
        hear(db, T0 + 3 * 3600 + 60)
        if "TA1AAA-1" in silent_calls(db):
            fails.append("a minute after a 3 h deaf spell, judged silent on it")

        # 2 · two breaks, a short stretch of listening between them
        clock[0] = T0
        db = station_db_module.StationDB()
        db._stations["TA1AAA-1"] = rec("TA1AAA-1", T0 - 60)
        db.ingest(packet("TA9ZZZ-1"))
        hear(db, T0 + 3600)                  # break 1 ends
        hear(db, T0 + 3600 + 600)
        hear(db, T0 + 3600 + 1200)           # 1,200 s listened, then
        hear(db, T0 + 7200)                  # break 2 ends
        hear(db, T0 + 7200 + 60)
        st = db.silence_state(["TA1AAA-1"]).get("TA1AAA-1") or {}
        if "TA1AAA-1" in silent_calls(db) or st.get("silent"):
            fails.append("listened 1,200 s between two breaks against a 1,800 s "
                         "threshold, judged silent (dated %r)" % st.get("since"))

        # 5 · a quick restart is no break
        clock[0] = T0
        old = station_db_module.StationDB()
        old._stations["TA1AAA-1"] = rec("TA1AAA-1", T0 - 5000)
        old._stations["TA4DDD-1"] = rec("TA4DDD-1", T0)
        path = os.path.join(tmp, "b.db")
        old.save_sqlite(path)
        clock[0] = T0 + 45
        db = station_db_module.StationDB()
        db.load_sqlite(path)
        db.ingest(packet("TA9ZZZ-1"))
        st = db.silence_state(["TA1AAA-1"]).get("TA1AAA-1") or {}
        if "TA1AAA-1" not in silent_calls(db) or not st.get("silent") \
                or st.get("unknown"):
            fails.append("a 45 s restart changed a silent station's verdict")

        # 7 · the own beacon is not hearing
        clock[0] = T0
        db = station_db_module.StationDB()
        clock[0] = T0 + D + 60
        db.ingest(packet("TA0OWN-1"), own=True)
        if not db.deaf_since():
            fails.append("our own beacon, fed in from the outbound log, made a "
                         "deaf agent count as hearing")

        # 8 · voiding a deaf period
        import json
        import types
        time.time = _real_time
        path = os.path.join(tmp, "c.db")
        a0, a1, why = 1000, 2000, "TEST"
        con = station_db_module._connect(path)
        con.execute("CREATE TABLE silence_history (ts INTEGER, cell TEXT, "
                    "baseline INTEGER, silent INTEGER, ratio REAL, alert INTEGER,"
                    " cause TEXT, silent_calls TEXT, since INTEGER, ai_note TEXT,"
                    " PRIMARY KEY (ts, cell))")
        con.executemany("INSERT INTO silence_history VALUES (?,?,0,0,0,1,'',"
                        "'[]',0,'')", [(900, "AA00"), (1500, "BB11"),
                                       (1500, "CC22"), (2100, "DD33")])
        con.commit()
        con.close()
        old_periods = web_gui._DEAF_PERIODS
        web_gui._DEAF_PERIODS = [(a0, a1, why)]
        m = types.SimpleNamespace(
            _sta_db_path=path,
            _missing={"IN-1": {"cell": "BB11", "flagged": 1500},
                      "OUT-1": {"cell": "AA00", "flagged": 900}},
            _silence_active={"BB11": 1200.0, "DD33": 2100.0},
            _silence_ai_notes={"BB11": "x", "DD33": "y"})
        try:
            web_gui.AgentManager._void_deaf_periods(m)
            web_gui.AgentManager._void_deaf_periods(m)
        finally:
            web_gui._DEAF_PERIODS = old_periods
        con = station_db_module._connect(path)
        left = sorted(r[0] for r in con.execute("SELECT cell FROM silence_history"))
        moved = sorted(con.execute("SELECT cell, void_reason FROM "
                                   "silence_history_void").fetchall())
        con.close()
        kept = json.loads(station_db_module.load_meta(path, "missing_voided", "{}"))
        stored = json.loads(station_db_module.load_meta(path, "missing_stations", "{}"))
        if left != ["AA00", "DD33"] or moved != [("BB11", why), ("CC22", why)]:
            fails.append("history void: left %r, moved %r" % (left, moved))
        if set(m._missing) != {"OUT-1"} or set(stored) != {"OUT-1"}                 or set(kept) != {"IN-1"}:
            fails.append("missing void: in memory %r, stored %r, kept %r"
                         % (sorted(m._missing), sorted(stored), sorted(kept)))
        if set(m._silence_active) != {"DD33"} or set(m._silence_ai_notes) != {"DD33"}:
            fails.append("episodes void: %r" % sorted(m._silence_active))
    except Exception as e:                      # a missing attribute is a fail
        fails.append("%s: %s" % (type(e).__name__, e))
    finally:
        time.time = _real_time

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    deaf from the start; silence counted only over time listened; "
          "unknown stays on the missing list")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
