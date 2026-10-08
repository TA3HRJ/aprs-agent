#!/usr/bin/env python3
"""Fail if a feed shaped like the real one breaks ingest or the opening rules.

AUDIT-2026-10-08 F5. The checks fed synthetic packets that missed real
branches: check_unheard_time ingested packets only from gates nobody had
heard, so the propagation branch that v3.2.158's reused `prev` broke never
ran, and the agent processed nothing for twelve hours (F-2026-10-07-04).
This one replays a small feed through tools/replay_feed.py - the live
ingest() on the lines' own clock, and the live opening watch - with the
shapes that matter:

  - an igate that beacons its position, and enough short RF links through
    it to establish its baseline
  - two senders 300+ km away within ten minutes: one opening
  - a station that moves 500 km in a minute: a suspect jump, kept out of
    grouping - and the code path where `prev` is a position
  - twenty minutes with no packet: a break in the feed

What must hold: no ingest error; the far links flagged, the jump among
them as `jump`; exactly one opening (KN) with suspects out; one break.

Usage:  python tools/check_feed_replay.py
Exit code 1 on failure.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import station_db as station_db_module  # noqa: E402
import replay_feed  # noqa: E402

T0 = dt.datetime(2026, 10, 1, 12, 0, 0)
GATE = "TA1GAT-10"


def ddmm(v: float, pos: str, neg: str, width: int) -> str:
    h = pos if v >= 0 else neg
    v = abs(v)
    d = int(v)
    return "%0*d%05.2f%s" % (width, d, (v - d) * 60, h)


def pkt(t: float, call: str, lat: float, lon: float, path: str,
        sym: str = "#", text: str = "") -> str:
    ts = (T0 + dt.timedelta(seconds=t)).strftime("%Y-%m-%dT%H:%M:%S")
    return "%s %s>APRS,%s:!%s/%s%s%s\n" % (
        ts, call, path, ddmm(lat, "N", "S", 2), ddmm(lon, "E", "W", 3), sym, text)


def feed() -> list:
    rf = "qAR," + GATE
    out = [pkt(0, GATE, 41.00, 29.00, "TCPIP*,qAC,T2TEST", "&", "igate")]
    # 25 local stations ~10 km out: the gate's baseline
    for i in range(25):
        out.append(pkt(30 + 20 * i, "TA1L%02d" % i, 41.08, 29.02 + 0.01 * i, rf))
    t = 540
    # a mover, first at home, then 500 km away a minute later
    out.append(pkt(t, "TA4MOV-9", 38.42, 27.14, "TCPIP*,qAC,T2TEST", ">"))
    out.append(pkt(t + 60, "TA4MOV-9", 39.92, 32.85, rf, ">"))
    # two far senders through the gate, minutes apart: an opening
    out.append(pkt(t + 120, "TA2AAA", 39.93, 32.86, rf))
    out.append(pkt(t + 300, "TA3BBB", 39.90, 32.70, rf))
    # twenty minutes of nothing, then the feed again
    out.append(pkt(t + 300 + 1200, "TA1L01", 41.08, 29.03, rf))
    out.append(pkt(t + 300 + 1260, "TA1L02", 41.08, 29.04, rf))
    return out


def main() -> int:
    fails = []
    db = station_db_module.StationDB()
    r = replay_feed.replay(feed(), db, utc_offset_h=0.0)
    if r["errors"]:
        fails.append("ingest raised: %r" % r["errors"])
    far = [l for l in r["links"] if l["call"].split("-")[0] in ("TA2AAA", "TA3BBB", "TA4MOV")]
    calls = sorted(l["call"] for l in far)
    if calls != ["TA2AAA", "TA3BBB", "TA4MOV-9"]:
        fails.append("far links flagged: %r, expected the two senders and the mover"
                     % calls)
    mover = [l for l in far if l["call"] == "TA4MOV-9"]
    if not mover or mover[0].get("suspect") != "jump":
        fails.append("the 500 km jump in a minute is not suspect: %r"
                     % [l.get("suspect") for l in mover])
    ev = replay_feed.openings(r["links"], r["t_start"], r["t_end"])
    if [e[1] for e in ev] != ["KN"]:
        fails.append("openings %r, expected one in KN" % ev)
    if len(db._breaks) != 1:
        fails.append("breaks %r, expected the twenty minutes" % list(db._breaks))

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    a real-shaped feed ingests cleanly: gate baseline, an opening, "
          "a jump kept out, a break")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
