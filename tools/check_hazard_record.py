#!/usr/bin/env python3
"""Fail if the hazard table cannot answer the question it exists for.

Born from F-2026-08-26-10. Silence cells are correlated against USGS
earthquakes only, and an earthquake is a rare reason for a region to go quiet.
Severe weather is not — and 557 weather-service products already arrive over
this feed, carrying a timestamp, a product type and FIPS county codes:

    CTPSVR  :NWS-WARN :182230z,SVR_STORM,PAC023,PAC047,PAC083{G30AA

v3.2.93 removed those from the silence SENSOR set, because a warning has no
beacon cadence to fall silent against. The same data is signal in the
correlation role. But the question - was a warning ACTIVE while this cell was
silent - cannot be asked from the registry: an NWS callsign is reused for
every new product from that office, so it holds one timestamp and no history
at all. This table is fourteen days of the history that was missing.

It decides nothing and nothing reads it yet. What this check defends is that
when something does read it, the rows are worth reading.

Assertions:

  1. a warning is parsed into its parts - issued time, product, FIPS areas
  2. the CONTENT comes from the live packet and the POSITION from the station
     record, because a warning is a message and carries no coordinates.
     Content cannot come from the record either: update_from_parsed sets
     `comment` only while the field is empty, so a record's comment is its
     FIRST warning and a table fed from there records history that has
     already scrolled past
  3. a warning that beacons for an hour is noted ONCE, on (callsign, issued)
  4. a new product from the same office IS a new row - the callsign repeats
     and only `issued` separates them
  5. an ordinary station never enters the table, however it is positioned
  6. taking the pending rows clears the buffer, so ingest cannot grow without
     bound between flushes
  7. rows carry the Maidenhead cell, because joining against silence cells is
     the only thing this table is for

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402

WARN = ("CTPSVR>APRS,TCPIP*,qAC,T2SERVER::NWS-WARN :"
        "182230z,SVR_STORM,PAC023,PAC047,PAC083{G30AA")
WARN2 = ("CTPSVR>APRS,TCPIP*,qAC,T2SERVER::NWS-WARN :"
         "190115z,TORNADO,PAC023{H31AA")
# An ordinary station, anonymised.
PLAIN = "TA1ABC-9>APRS,TCPIP*,qAC,T2SERVER:!3900.00N/03200.00E-Test station"


def main() -> int:
    problems: list[str] = []
    db = station_db_module.StationDB()

    # ── 1 and 2 · parsed from the live packet, into its parts ──────────────
    from packet_parser import parse_packet
    h = station_db_module.parse_hazard(parse_packet(WARN))
    if not h:
        print("FAIL  an NWS product is not recognised at all")
        print("1 problem")
        return 1
    for field, want in (("callsign", "CTPSVR"), ("issued", "182230"),
                        ("product", "SVR_STORM"),
                        ("areas", "PAC023,PAC047,PAC083")):
        if h.get(field) != want:
            problems.append("parse_hazard %s is %r, expected %r"
                            % (field, h.get(field), want))

    # The office beacons its position separately, which is the only place a
    # warning's coordinates can come from.
    db.ingest("CTPSVR>APRS,TCPIP*,qAC,T2SERVER:!4048.00N/07754.00W&NWS")

    # ── 3 · a warning that beacons for an hour is one row ──────────────────
    for _ in range(50):
        db.ingest(WARN)
    if len(db._hazards_pending) != 1:
        problems.append(
            "fifty beacons of one warning left %d pending entries. A warning "
            "transmits for as long as it is in force; a row per packet would "
            "store it hundreds of times" % len(db._hazards_pending))

    # ── 4 · a new product from the same office is a new row ────────────────
    db.ingest(WARN2)
    if len(db._hazards_pending) != 2:
        problems.append(
            "a second product from the same office did not create a second "
            "entry (%d pending). The callsign repeats — only `issued` "
            "separates one warning from the next" % len(db._hazards_pending))

    # ── 5 · an ordinary station is never in it ─────────────────────────────
    db.ingest(PLAIN)
    calls = {k[0] for k in db._hazards_pending}
    if "TA1ABC-9" in calls:
        problems.append("an ordinary station entered the hazard buffer")

    # ── 6 · taking clears ──────────────────────────────────────────────────
    rows = db.take_hazards()
    if len(rows) != 2:
        problems.append("take_hazards returned %d rows, expected 2"
                        % len(rows))
    if db._hazards_pending:
        problems.append(
            "take_hazards left %d entries behind. Ingest runs on every packet "
            "and the buffer must not grow between flushes"
            % len(db._hazards_pending))

    # ── 7 · what gets written, and the cell that makes it joinable ─────────
    # The positions are NOT planted here. A warning arrives as a message and
    # carries none; it has to reach the row from the station's own beacon, via
    # the record. The first four live rows landed with an empty cell precisely
    # because this fixture used to plant them by hand — a check asked an easy
    # question and passed (F-2026-08-26-11).
    with tempfile.TemporaryDirectory() as d:
        p = str(Path(d) / "t.sqlite")
        for r in rows:
            if r.get("lat") is None:
                problems.append(
                    "%s reached the writer with no position, so its row will "
                    "carry an empty cell and the join this table exists for "
                    "will match nothing" % r.get("callsign"))
        n = station_db_module.record_hazards(p, rows)
        if n != 2:
            problems.append("record_hazards wrote %d rows, expected 2" % n)
        # the same rows again must not duplicate
        again = station_db_module.record_hazards(p, rows)
        if again != 0:
            problems.append(
                "re-recording the same warnings wrote %d more rows. The "
                "primary key is (callsign, issued) precisely so a restart or "
                "an overlapping flush cannot double-count" % again)
        con = sqlite3.connect(p)
        got = con.execute(
            "SELECT callsign, issued, product, areas, cell FROM hazard_history "
            "ORDER BY issued").fetchall()
        con.close()
        if len(got) != 2:
            problems.append("table holds %d rows after two writes" % len(got))
        else:
            if not got[0][4]:
                problems.append(
                    "rows carry no Maidenhead cell. Joining against silence "
                    "cells is the only thing this table is for")
            if got[0][2] != "SVR_STORM" or got[1][2] != "TORNADO":
                problems.append("products stored as %r"
                                % [g[2] for g in got])

    print("checked a warning beaconed 50 times, a second product from the "
          "same office, and one ordinary station")
    for p_ in problems:
        print("FAIL  " + p_)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
