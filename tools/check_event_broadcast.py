#!/usr/bin/env python3
"""Fail if a weather warning can be counted as a silent radio station.

Born from F-2026-08-26-07. The NWS APRS gateway broadcasts severe-weather
products as ORDINARY STATIONS - one per weather-service office per product,
~200 of them - and their traffic is a message addressed to NWS-WARN:

    TBWSVR  :NWS-WARN :171915z,SVR_STORM,FLC053{R00AA
    ABRSVS  :NWS-WARN :182230z,SEVERE_WX,SDC013{s20AA

Silence detection rests entirely on cadence: a station is silent when the gap
since its last packet exceeds 3x its own smoothed beacon interval. These have
no such interval to exceed. They transmit while a warning is in force and say
nothing for the days between, so their silence is fair weather - reported to
an operator as a regional radio outage.

Measured over 14 days: 3,250 of 21,886 cell-snapshots held at least one, and
503 consisted of nothing else. EN03 - the cell F-25 was written from - is one
of those: six silent "stations", all expired warnings from three offices, and
the "two pairs a hundred metres apart" are each office's SVR and SVS sharing
one position.

Assertions:

  1. an NWS-WARN broadcaster is excluded
  2. a real station is NOT excluded, however its callsign looks. TA8SVS ends
     in SVS and is an operator in Turkey
  3. a tactical-named transmitter is NOT excluded. This is the direction the
     rule fails if someone replaces it with the tempting "no digit in the
     callsign" test - SADDLE, HOGBAK-10, EUGENE and KYIV-1 are real
     transmitters and a mountain digipeater going quiet is the news this
     detector exists for
  4. the match is on the addressee, not on a substring of the callsign
  5. an empty or missing comment never matches

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402


class _Rec:
    def __init__(self, callsign, comment=""):
        self.callsign = callsign
        self.comment = comment


# Live shapes, verbatim except the callsigns of real operators.
BROADCASTS = [
    ("TBWSVR", ":NWS-WARN :171915z,SVR_STORM,FLC053{R00AA"),
    ("CTPSVR", ":NWS-WARN :182230z,SVR_STORM,PAC023,PAC047,PAC083{G30AA"),
    ("CLESVS", ":NWS-WARN :182215z,SEVERE_WX,OHC099{x30AA"),
    ("INDFLS", ":NWS-WARN :130200z,FLOOD,INC015,INC181{D20AA"),
    ("ABRSVR", ":NWS-WARN :182230z,SVR_STORM,SDC013{s20AA"),
]

# Real transmitters. The first ends in SVS and would be caught by a callsign
# match; the rest carry no digit and would be caught by the digit rule.
REAL = [
    ("TA1ABC-9", "@015857h3736.02N/03654.16E%000/000Op.Volkan 2864463"),
    ("SADDLE", "@182224z4532.71NI12322.93W#South Saddle Mountain Digipeater"),
    ("HOGBAK-10", "!4214.45NL12142.43W&Hogback Mountain LoRa-APRS 433."),
    ("EUGENE", "@182159z4406.48NS12308.95W#PHG7380/W2,ORn-N,EUGENE 13.7V"),
    ("KYIV-1", "=5026.00N/03022.60ErFree radio repeater 446.225/434.850"),
    ("OTISMA", "@182218z4211.86N/07308.17W#Digi I-Gate WX3in1v1"),
]


def main() -> int:
    problems: list[str] = []
    f = station_db_module.is_event_broadcast

    # 1 - the broadcasts
    for call, comment in BROADCASTS:
        if not f(_Rec(call, comment)):
            problems.append(
                "%s carries an NWS-WARN product and is not excluded. It has no "
                "beacon cadence to fall silent against, so counting it makes "
                "fair weather look like a regional outage" % call)

    # 2 and 3 - everything that must survive
    for call, comment in REAL:
        if f(_Rec(call, comment)):
            problems.append(
                "%s is excluded. It is a real transmitter at a real place, and "
                "its going quiet is the news this detector exists for" % call)

    # 4 - the match is on the addressee, not the callsign
    if f(_Rec("TBWSVR", "!4210.00N/07100.00W#ordinary digipeater comment")):
        problems.append(
            "a station is excluded on its callsign alone. The rule has to read "
            "the traffic: TBWSVR sending an ordinary beacon is an ordinary "
            "station")
    if not f(_Rec("N0CALL-1", ":NWS-WARN :182230z,SVR_STORM,XXC001{A00AA")):
        problems.append(
            "an NWS-WARN product from a callsign-shaped identifier is not "
            "excluded, so the rule is keying on the callsign after all")

    # 5 - nothing to read
    for comment in ("", None):
        if f(_Rec("TA1ABC-1", comment)):
            problems.append("a station with comment %r is excluded" % comment)

    print("checked %d broadcast shapes and %d real transmitters"
          % (len(BROADCASTS), len(REAL)))
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
