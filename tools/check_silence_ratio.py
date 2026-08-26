#!/usr/bin/env python3
"""Fail if the silence ratio counts callsigns where the alert counts operators.

Born from F-2026-08-26-08. `few_sites` has qualified alerts on OPERATORS since
v3.2.25 - three SSIDs of one base callsign are three radios in one shack on
one power strip and cannot fail independently - while the ratio beside it went
on dividing callsigns by callsigns. Two units in one cell.

A reader was told "80% of this square fell silent" about two operators, one of
whom was still transmitting.

Measured over 20,423 stored cell-snapshots before the change: 44.3% held more
callsigns than operators, and on those the silent count falls from a mean of
5.96 to 4.24.

Assertions:

  1. one operator's three radios do not make a majority of a cell
  2. the callsign ratio is still published, because fourteen days of stored
     history were computed with it and mean what they were computed with
  3. the denominator is published too - a ratio without what it divided by is
     how F-2026-08-16-01b happened on the propagation side
  4. the ratio can go UP as well as down. Two operators in a cell, both
     silent, is 100% of that cell's operators however many callsigns sit
     around them. Any rewrite that only ever lowers the number has replaced
     the measure with a discount
  5. threshold_met keeps its raw callsign count, so the narrower definition
     still hides nothing

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402
from packet_parser import _latlon_to_locator  # noqa: E402

LAT, LON = 39.0, 32.0


def build(spec):
    """spec: (callsign, silent) — one cell, everything else held constant."""
    db = station_db_module.StationDB()
    now = time.time()
    for call, silent in spec:
        r = station_db_module.StationRecord(call)
        r.lat, r.lon = LAT, LON
        r.locator = _latlon_to_locator(LAT, LON)
        r.ema_interval_s = 600.0
        r.packet_count = 50
        r.last_seen = now - (5000 if silent else 60)
        db._stations[call] = r
    cells = db.silence_cells(min_history=5, min_silent=3, min_ratio=0.5)
    return cells[0] if cells else None


def main() -> int:
    problems: list[str] = []

    # ── 1 · one shack is not a region ──────────────────────────────────────
    c = build([("TA1ABC-1", True), ("TA1ABC-7", True), ("TA1ABC-9", True),
               ("TA2ABC-1", False), ("TA3ABC-1", False)])
    if c is None:
        print("FAIL  no cell was produced at all")
        print("1 problem")
        return 1
    if c["ratio"] > 0.4:
        problems.append(
            "three radios of ONE operator, in a cell of three operators, "
            "produce a ratio of %.2f. That is one shack losing power reported "
            "as most of a square falling silent" % c["ratio"])
    if c["threshold_met"]:
        problems.append(
            "the same cell meets the threshold. min_ratio is 0.5 and one "
            "operator of three is 0.33")

    # ── 2 and 3 · nothing is hidden, and the denominator is named ──────────
    if c.get("ratio_callsigns") is None:
        problems.append(
            "ratio_callsigns is absent. Fourteen days of stored snapshots "
            "were computed with the callsign figure and mean what they were "
            "computed with")
    elif abs(c["ratio_callsigns"] - 0.6) > 0.01:
        problems.append(
            "ratio_callsigns is %.2f, expected 0.60 — 3 silent callsigns of 5"
            % c["ratio_callsigns"])
    if c.get("baseline_sites") != 3:
        problems.append(
            "baseline_sites is %r, expected 3. A ratio published without what "
            "it divided by is the defect F-2026-08-16-01b names"
            % c.get("baseline_sites"))

    # ── 4 · it must be able to rise ────────────────────────────────────────
    # Two operators, both silent, among callsigns that mostly belong to them.
    c2 = build([("TA1ABC-1", True), ("TA1ABC-7", False), ("TA1ABC-9", False),
                ("TA2ABC-1", True), ("TA2ABC-2", False)])
    if c2 is None:
        problems.append("the second fixture produced no cell")
    else:
        if c2["ratio"] <= c2["ratio_callsigns"]:
            problems.append(
                "both operators in this cell are silent, so the operator "
                "ratio is 1.00 against a callsign ratio of %.2f — and it came "
                "back %.2f. A rewrite that can only lower the number has "
                "replaced the measure with a discount"
                % (c2["ratio_callsigns"], c2["ratio"]))
        if abs(c2["ratio"] - 1.0) > 0.01:
            problems.append(
                "two operators of two are silent and the ratio is %.2f, not "
                "1.00" % c2["ratio"])

    # ── 5 · the raw result survives ────────────────────────────────────────
    if c["silent"] != 3 or c["baseline"] != 5:
        problems.append(
            "the callsign counts changed: silent=%r baseline=%r, expected 3 "
            "and 5. threshold_met reads these and is deliberately the raw "
            "figure" % (c["silent"], c["baseline"]))

    print("checked two planted cells against min_silent=3, min_ratio=0.5")
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
