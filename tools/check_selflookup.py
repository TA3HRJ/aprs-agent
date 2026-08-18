#!/usr/bin/env python3
"""Fail if the self-lookup answers about anyone but the sender, or drops the age.

TA3HRJ-10 asked "Where is the last location of TA3HRJ-7 station?" and was told
to check aprs.fi, by a process holding 180,000 station records. The lookup that
fixes that is deliberately narrow, and this check is what keeps it narrow.

Four things it holds:

  1. the sender's own callsign is answered from the registry, with no model
     call at all
  2. another operator's callsign is refused - the whole risk in this feature
     is third-party lookup
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
}


class FakeDB:
    def get_one(self, call):
        return RECORDS.get(call)


def line(sender: str, text: str) -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s" % (sender, text)


async def run() -> int:
    problems: list[str] = []

    for label, sender, question, expect in [
        ("own callsign",   "TA3HRJ-10", "Where is TA3HRJ-7?",   "registry"),
        ("own, no record", "TA3HRJ-10", "Where is TA3HRJ-9?",   "registry"),
        ("someone else",   "TA3HRJ-10", "Where is W1AW-1?",     "refused"),
        ("no callsign",    "TA3HRJ-10", "What is SWR?",         "model"),
        ("not a location", "TA3HRJ-10", "TA3HRJ-7 antenna tips", "model"),
    ]:
        sent: list[str] = []

        class Queue:
            async def put(self, b: bytes) -> None:
                sent.append(b.decode("utf-8").strip())

        gw = AIGateway(dict(CFG), "")
        gw.set_station_db(FakeDB())
        gw._own_writer = Queue()

        asked = {"n": 0}

        async def stub(q: str, s: str = "") -> str:
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
            if "38.428" not in body and "38.4" not in body:
                problems.append("%s: no position in the answer -> %r" % (label, body[:70]))
            if "ago" not in body:
                problems.append("%s: position without an age -> %r" % (label, body[:70]))
        if expect == "refused":
            if "W1AW" in body and "only look up your own" not in body:
                problems.append("%s: leaked another station -> %r" % (label, body[:70]))

        print("  %-15s %-24s -> %s" % (label, question, body[:78]))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
