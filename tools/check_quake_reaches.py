#!/usr/bin/env python3
"""Fail if a strong quake near an alerting cell stops reaching the operator.

2026-10-09 (F-2026-10-10-01): an M7.7 struck Panama at 17:56 UTC. EJ88
alerted 2 h later, 266 km away, and the quake was matched to it - the map
popup showed it. Neither thing the operator actually reads did:

  - the hourly Telegram digest the host sends (silence_digest_mins) is built
    by _format_silence_digest, which had no quake line; only the single-alert
    message did
  - the AI note answered "[unknown/low]" with a timing-only sentence. The
    quake was in its prompt, after the onset block's "answer unknown rather
    than choose from timing alone", and nothing asked for it to be weighed
    or named

What must hold:

  1. a digest line for a cell with a quake candidate carries the quake;
     one without carries none
  2. the prompt's quake block says, per quake, how many of the silent
     stations had already stopped before it (those it cannot explain)
  3. for a strong quake (M6+, or within 100 km) the prompt asks for the
     quake to be named in the summary; for a weak, distant one it does not
  4. a quake is matched up to the LAST silent station's last packet, not
     only up to 10 min after the FIRST one crossed its threshold. The M7.7
     reached EJ88 by four minutes; two stations a little earlier and it
     would have reached nothing. One after every station stopped is not
     matched

Usage:  python tools/check_quake_reaches.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from station_db import StationDB, StationRecord  # noqa: E402
import web_gui as wg  # noqa: E402

NOW = time.time()
PANAMA = {"mag": 7.7, "place": "12 km WSW of Pitaloza Arriba, Panama",
          "ts": NOW - 3 * 3600, "depth_km": 13, "lat": 7.5868, "lon": -80.769}
WEAK = {"mag": 4.6, "place": "far off", "ts": NOW - 3 * 3600, "depth_km": 10,
        "lat": 11.5, "lon": -84.0}           # about 400 km from EJ88's centre


def alert(cell):
    return {"cell": cell, "silent": 3, "baseline": 12, "ratio": 0.5,
            "cause": "outage", "silent_calls": ["HP0AA", "HP0AB", "HP0AC"],
            "since": NOW - 2 * 3600}


def context(quakes):
    wg._quake_cache = (NOW, quakes)
    db = StationDB()
    # two stopped before the quake (silent already), one after it
    for call, ago in (("HP0AA", 5 * 3600), ("HP0AB", 4 * 3600),
                      ("HP0AC", 2.5 * 3600)):
        r = StationRecord(call)
        r.last_seen = NOW - ago
        r.ema_interval_s = 600
        db._stations[call] = r
    m = types.SimpleNamespace(_station_db=db)
    return wg.AgentManager._quake_context(m, alert("EJ88"))


def main() -> int:
    fails = []

    wg._quake_cache = (NOW, [PANAMA])
    d = wg.AgentManager._format_silence_digest(
        [(NOW, alert("EJ88"), "[unknown/low] x"),
         (NOW, alert("KM38"), "[unknown/low] y")], 60)
    ej, km = d.split("EJ88", 1)[1].split("KM38", 1)
    if "M7.7" not in ej:
        fails.append("1: the digest line for EJ88 does not carry the M7.7")
    if "🌍" in km:
        fails.append("1: a cell with no quake candidate got a quake line")

    try:
        strong = context([PANAMA])
        weak = context([WEAK])
    except Exception as e:                      # noqa: BLE001
        fails.append("2: _quake_context could not be built: %s" % e)
        strong = weak = ""
    if strong:
        if "2 of 3" not in strong:
            fails.append("2: the quake block does not say 2 of 3 stopped before "
                         "it: %r" % strong[-200:])
        if "name the quake" not in strong:
            fails.append("3: an M7.7 at 266 km is not required in the summary")
    if weak and "name the quake" in weak:
        fails.append("3: an M4.6 400 km away is required in the summary")
    if not weak:
        fails.append("3: the M4.6 is no longer offered as a candidate at all")

    wg._quake_cache = (NOW, [dict(PANAMA, ts=NOW - 3 * 3600)])
    late = {"cell": "EJ88", "since": NOW - 4.5 * 3600, "last_stop": NOW - 2.6 * 3600}
    try:
        if not wg._alert_quakes(late):
            fails.append("4: a quake between the first and the last stop is not matched")
        wg._quake_cache = (NOW, [dict(PANAMA, ts=NOW - 1 * 3600)])
        if wg._alert_quakes(late):
            fails.append("4: a quake after every station stopped is matched")
    except AttributeError as e:
        fails.append("4: %s" % e)

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    the digest carries the quake; the prompt counts who stopped "
          "before it and asks for a strong one by name")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
