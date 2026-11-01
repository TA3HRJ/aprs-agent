#!/usr/bin/env python3
"""Fail if a silence cell cannot name the weather warnings beside it.

Born from F-2026-11-01-02. Measured over 33 days, 13 of 130 silence episodes
in squares that also carry US weather-service warnings had one within 2 h,
against 4-7 with the window shifted by one to seven days. Above chance, so
the map popup, the evidence file, the AI note and Telegram now name such a
warning the way they name a quake - as a candidate, not a cause.

The annotation is only worth what the measurement was worth, so this check
defends that it joins the same way: same square, same window.

Assertions:

  1. a warning is filed under the square of its office's own beacon - the
     same function the table uses, so live and measured joins agree
  2. a warning up to 2 h before the silence began is named; one earlier is not
  3. a warning in another square is not named
  4. a past snapshot is bounded by its own time: a later warning is not named
  5. one warning beaconed many times keeps the time it was FIRST seen
  6. after a restart the warnings come back from the table, or a cell
     alerting in the first minutes would name none
  7. warnings older than the kept week are aged out on the writer's timer
  8. the Telegram alert, the digest and the AI-note prompt carry the warning

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402

# An office beacon (anonymised) and one of its products.
OFFICE = "CTPSVR>APRS,TCPIP*,qAC,T2SERVER:!4048.00N/07754.00W&NWS"
WARN = ("CTPSVR>APRS,TCPIP*,qAC,T2SERVER::NWS-WARN :"
        "182230z,SVR_STORM,PAC023,PAC047,PAC083{G30AA")


def main() -> int:
    problems: list[str] = []
    SDB = station_db_module.StationDB
    db = SDB()
    db.ingest(OFFICE)
    t0 = time.time()
    for _ in range(20):
        db.ingest(WARN)
    square = station_db_module._hazard_cell(40.8, -77.9)

    # ── 1 · filed under the office's square ────────────────────────────────
    if not square or square not in db._hazards_recent:
        problems.append(
            "the warning is not filed under its office's square %r (have %r). "
            "The silence readers cannot name it" % (square,
                                                    list(db._hazards_recent)))

    # ── 2 · the window: from 2 h before the silence began ──────────────────
    w = SDB.HAZARD_WINDOW_S
    if not db.hazards_in(square, t0 + w - 60):
        problems.append(
            "a warning %d min before the silence began is not named. The "
            "measured window is %d h either side" % ((w - 60) // 60, w // 3600))
    if db.hazards_in(square, t0 + w + 600):
        problems.append(
            "a warning more than %d h before the silence began is named. The "
            "measurement supports nothing wider" % (w // 3600))

    # ── 3 · another square ─────────────────────────────────────────────────
    other = station_db_module._hazard_cell(38.4, 27.1)
    if db.hazards_in(other, t0):
        problems.append("a warning from %s is named in %s" % (square, other))

    # ── 4 · a past snapshot ends at its own time ───────────────────────────
    if db.hazards_in(square, t0 - 3600, until_ts=t0 - 600):
        problems.append(
            "a snapshot from before the warning names it. Reading a past "
            "moment must not borrow what came after")

    # ── 5 · first seen, not last ───────────────────────────────────────────
    got = db.hazards_in(square, t0)
    if len(got) != 1:
        problems.append("20 beacons of one warning gave %d entries"
                        % len(got))
    elif got[0]["ts"] > t0 + 5:
        problems.append("the entry carries the last beacon's time, not the "
                        "first")
    elif got[0]["product"] != "SVR_STORM" or got[0]["callsign"] != "CTPSVR":
        problems.append("entry read back as %r" % got[0])

    # ── 6 · back after a restart ───────────────────────────────────────────
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "t.sqlite")
        db.save_sqlite(p)
        station_db_module.record_hazards(p, db.take_hazards())
        fresh = SDB()
        fresh.load_sqlite(p)
        if not fresh.hazards_in(square, t0):
            problems.append(
                "after a restart the warning is gone from memory although the "
                "table holds it. A cell alerting in the first minutes would "
                "name nothing")

    # ── 7 · aged out on the writer's timer ─────────────────────────────────
    old_key = ("OLDSVR", "010000")
    db._hazards_recent.setdefault(square, {})[old_key] = (
        t0 - SDB.HAZARD_RECENT_S - 60, "FLOOD")
    db.take_hazards()
    if old_key in db._hazards_recent.get(square, {}):
        problems.append(
            "a warning older than the kept week was not aged out. The "
            "in-memory copy would grow with every warning the feed carries")
    if not db.hazards_in(square, t0):
        problems.append("ageing out removed the current warning as well")

    # ── 8 · the readers that leave this server ─────────────────────────────
    import web_gui
    AM = web_gui.AgentManager
    c = {"cell": square, "silent": 3, "baseline": 4, "ratio": 0.75,
         "cause": "outage", "silent_calls": ["A1AAA", "B1BBB", "C1CCC"],
         "since": int(t0 + 1800), "last_stop": int(t0 + 1200),
         "hazards": db.hazards_in(square, t0 + 1800)}
    msg = AM._format_silence_msg(c, "")
    if "SVR_STORM" not in msg:
        # Not the message itself: its emoji cannot be printed on a Windows
        # console, and the failure line would crash instead of reporting.
        problems.append("the Telegram alert does not name the warning")
    dig = AM._format_silence_digest([(t0, c, "")], 15)
    if "SVR_STORM" not in dig:
        problems.append("the Telegram digest does not name the warning")
    ctx = AM._hazard_context(c)
    if "SVR_STORM" not in ctx or "coincidence" not in ctx:
        problems.append(
            "the AI-note prompt does not carry the warning with its caveat: "
            "%r" % ctx)
    if "30 min before" not in msg:
        problems.append("the offset is missing or wrong in the Telegram alert")

    print("checked one office's warning beaconed 20 times against the window, "
          "another square, a past snapshot, a restart and ageing")
    for p_ in problems:
        print("FAIL  " + p_)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
