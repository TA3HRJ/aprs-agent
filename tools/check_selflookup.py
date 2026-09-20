#!/usr/bin/env python3
"""Fail if the self-lookup answers about anyone but the sender, or drops the age.

TA3HRJ-10 asked "Where is the last location of TA3HRJ-7 station?" and was told
to check aprs.fi, by a process holding 180,000 station records. The lookup that
fixes that is deliberately narrow, and this check is what keeps it narrow.

Four things it holds:

  1. the sender's own callsign is answered from the registry, with no model
     call at all
  2. another operator's callsign is answered from the registry as well -
     the same one observation the map already draws, and no more. Until
     2026-09-20 it was refused; the refusal protected nobody while aprs.fi
     served the same beacon, and it is now bounded by what the answer may
     contain (no name, no licence record, no history) and by a station's own
     NOLOOKUP, which tools/check_lookup.py holds
  3. an answer that carries a position also carries its age, because a
     three-hour-old fix stated in the present tense is worse than no answer
  4. a question that names no callsign still reaches the model

No network and no provider: the registry and the answer are both stubbed.

Usage:  python tools/check_selflookup.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 0,
    "rate_refill_s": 0,
}

RECORDS = {
    "TA3HRJ-7": {
        "callsign": "TA3HRJ-7", "lat": 38.4276, "lon": 27.1043,
        "locator": "KM38ok", "last_seen_ago_s": 840, "last_gate": "TA3HRJ-5",
    },
    "W1AW-1": {
        "callsign": "W1AW-1", "lat": 41.714, "lon": -72.727,
        "locator": "FN31pr", "last_seen_ago_s": 600, "last_gate": "W1AW-10",
    },
    "TA3HRJ-10": {
        "callsign": "TA3HRJ-10", "lat": 38.42, "lon": 27.10,
        "locator": "KM38ok", "last_seen_ago_s": 60, "last_gate": "TA3HRJ-5",
    },
}


class FakeDB:
    def get_one(self, call):
        return RECORDS.get(call)

    def nearest_of_type(self, lat, lon, kinds, max_km=250.0, limit=3):
        return [(dict(RECORDS["TA3HRJ-7"]), 12.0)]

    def has_gated(self, call):
        return False

    def prop_summary(self, max_links=200):
        return {"links": []}


def line(sender: str, text: str) -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s" % (sender, text)


async def run() -> int:
    problems: list[str] = []

    for label, sender, question, expect in [
        ("own callsign",   "TA3HRJ-10", "Where is TA3HRJ-7?",   "registry"),
        ("own, no record", "TA3HRJ-10", "Where is TA3HRJ-9?",   "registry"),
        # Policy changed 2026-09-20: answered, not refused. See the head
        # of this file and tools/check_lookup.py for the boundary.
        ("someone else",   "TA3HRJ-10", "Where is W1AW-1?",     "registry"),
        ("no callsign",    "TA3HRJ-10", "What is SWR?",         "model"),
        ("not a location", "TA3HRJ-10", "TA3HRJ-7 antenna tips", "model"),
        # Asking about yourself without naming yourself. On 2026-09-10 a
        # station asked "Time, date and my location?" and was told its
        # position was unavailable, while its own beacon from four minutes
        # earlier sat in the registry (F-2026-09-10-02).
        ("my location",    "TA3HRJ-7",  "Time, date and my location?", "registry"),
        ("where am i",     "TA3HRJ-7",  "Where am I?",          "registry"),
        ("turkish self",   "TA3HRJ-7",  "Konumum nerede?",      "registry"),
        # First person only: a location question about something else must
        # still reach the model, or every "where is the nearest digi" would
        # be answered with the asker's own coordinates.
        # Infrastructure, answered from the registry since 2026-09-20.
        ("nearest digi",   "TA3HRJ-7",  "Where is the nearest digi?", "registry"),
        ("my antenna",     "TA3HRJ-7",  "My antenna is broken",  "model"),
    ]:
        sent: list[str] = []

        class Queue:
            async def put(self, b: bytes) -> None:
                sent.append(b.decode("utf-8").strip())

        gw = AIGateway(dict(CFG), "")
        gw.set_station_db(FakeDB())
        gw._own_writer = Queue()

        asked = {"n": 0}

        async def stub(q: str, s: str = "", history=None) -> str:
            asked["n"] += 1
            return "MODEL ANSWER"

        gw._ask_ai = stub
        await gw.handle(line(sender, question))

        body = " ".join(s.split(":", 2)[-1] for s in sent if ":ack" not in s)

        if expect == "model":
            if asked["n"] != 1:
                problems.append("%s: model not consulted (%d calls)" % (label, asked["n"]))
        else:
            if asked["n"] != 0:
                problems.append("%s: model was consulted, template should have "
                                "answered" % label)

        if expect == "registry" and "TA3HRJ-9" not in question:
            if "W1AW" in question:
                if "41.7" not in body:
                    problems.append("%s: another station's public position "
                                    "was not answered -> %r" % (label, body[:70]))
                if "ago" not in body:
                    problems.append("%s: position without an age -> %r"
                                    % (label, body[:70]))
                print("  %-15s %-24s -> %s" % (label, question, body[:78]))
                continue
            if "nearest digi" == label:
                if "12km" not in body.replace(" ", "") and "12" not in body:
                    problems.append("%s: no igate/digi distance -> %r"
                                    % (label, body[:70]))
                print("  %-15s %-24s -> %s" % (label, question, body[:78]))
                continue
            if "38.428" not in body and "38.4" not in body:
                problems.append("%s: no position in the answer -> %r" % (label, body[:70]))
            if "ago" not in body:
                problems.append("%s: position without an age -> %r" % (label, body[:70]))
        print("  %-15s %-24s -> %s" % (label, question, body[:78]))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
