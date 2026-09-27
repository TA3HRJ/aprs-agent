#!/usr/bin/env python3
"""Fail if a question about the date or the time goes to the model, or comes
back wrong.

On 2026-09-27 TA3HX-7 sent "SAAT VE TARIH?" and the model answered "Yerel
saat dilimini bilemem, ama UTC su an 2026-09-27 16:02. --" then "Yoksa 27
Eylul 2026 Pazar. 73": two packets, a stray "Yoksa", and a claim not to know
the local zone of a station whose beacon puts it in Turkey, where the clock
is UTC+3 all year. "DATE?" the same afternoon came back three different
ways, once as two packets. The clock is the one thing the code knows exactly.

What must hold:

  1. "DATE?" and "SAAT VE TARİH?" (with a Turkish capital İ) are answered
     from the code, without a model call, in one packet
  2. a Turkish question gets a Turkish day name; an English one, English
  3. a station in Turkey gets its local time beside UTC; a station elsewhere
     gets UTC only - no zone is guessed
  4. after 21:00 UTC the Turkish date is the next day, and the answer says so
     rather than pairing a local time with yesterday's date
  5. a question that only mentions time ("what time does the ISS pass")
     still goes to the model - the weather shortcut once swallowed a joke

No network and no provider: the model, the registry and the clock are stubbed.

Usage:  python tools/check_time_answer.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import calendar
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as gwmod  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "rate_burst": 20,
    "rate_refill_s": 360,
    "extra_sms": 2,
}

POS = {
    "TA1ABC-7": (38.50, 27.00),     # Izmir
    "W1ABC-9": (40.60, -73.90),     # New York
}

# Sunday 2026-09-27 16:48:10 UTC, and 22:30:00 UTC the same day
T_DAY = calendar.timegm((2026, 9, 27, 16, 48, 10, 0, 0, 0))
T_LATE = calendar.timegm((2026, 9, 27, 22, 30, 0, 0, 0, 0))


class FakeDB:
    def get_one(self, call):
        p = POS.get(call.upper())
        return {"callsign": call, "lat": p[0], "lon": p[1]} if p else None

    def nearest_wx(self, lat, lon, radius):
        return None


def line(sender: str, text: str) -> str:
    return "%s>APAT89,WIDE1-1,qAR,TA1ABC-10::DMWGPT   :%s" % (sender, text)


async def ask(gw, sent, sender, text):
    before = len(sent)
    await gw.handle(line(sender, text))
    parts = []
    for s in sent[before:]:
        body = s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            continue
        parts.append(body.rsplit("{", 1)[0])
    return parts


def new_gateway(sent, calls):
    class Queue:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Queue()
    gw.set_station_db(FakeDB())

    async def stub(question, sender="", history=None):
        calls["n"] += 1
        return "Model answer."

    gw._ask_ai = stub
    return gw


async def run() -> int:
    problems = []
    real_clock = gwmod._clock

    async def case(sender, text, now):
        gwmod._clock = lambda: now
        sent, calls = [], {"n": 0}
        gw = new_gateway(sent, calls)
        parts = await ask(gw, sent, sender, text)
        return parts, calls["n"], " ".join(parts)

    try:
        # 1-3: English, from Turkey
        parts, n, a = await case("TA1ABC-7", "DATE?", T_DAY)
        print("  DATE? (TA1ABC-7):", parts)
        if n:
            problems.append("DATE? cost a model call")
        if len(parts) != 1:
            problems.append("DATE? went out as %d packets" % len(parts))
        for want in ("2026-09-27", "Sunday", "16:48 UTC", "TR 19:48"):
            if want not in a:
                problems.append("DATE? answer lacks %r: %r" % (want, a))

        # 1-3: Turkish, with a Turkish capital I, from Turkey
        parts, n, a = await case("TA1ABC-7", "SAAT VE TARİH?", T_DAY)
        print("  SAAT VE TARİH? (TA1ABC-7):", parts)
        if n:
            problems.append("SAAT VE TARİH? cost a model call")
        if len(parts) != 1:
            problems.append("SAAT VE TARİH? went out as %d packets" % len(parts))
        for want in ("2026-09-27", "Pazar", "16:48 UTC", "TR 19:48"):
            if want not in a:
                problems.append("Turkish answer lacks %r: %r" % (want, a))

        # 3: elsewhere - UTC only
        parts, n, a = await case("W1ABC-9", "what time is it", T_DAY)
        print("  what time is it (W1ABC-9):", parts)
        if n:
            problems.append("'what time is it' cost a model call")
        if "16:48 UTC" not in a:
            problems.append("no UTC time for a station outside Turkey: %r" % a)
        if "TR" in a:
            problems.append("a station in New York was given Turkish time: %r" % a)

        # 4: after 21:00 UTC Turkey is on the next day
        parts, n, a = await case("TA1ABC-7", "tarih", T_LATE)
        print("  tarih at 22:30 UTC (TA1ABC-7):", parts)
        if "2026-09-27" not in a or "22:30 UTC" not in a:
            problems.append("late answer lost the UTC date or time: %r" % a)
        if "28.09" not in a or "01:30" not in a:
            problems.append("late answer pairs Turkish 01:30 with the wrong "
                            "date: %r" % a)

        # 5: a question that only mentions time is still a question
        parts, n, a = await case("TA1ABC-7",
                                 "what time does the ISS pass over Izmir", T_DAY)
        if n != 1:
            problems.append("'what time does the ISS pass' did not reach the "
                            "model: %r" % a)
    finally:
        gwmod._clock = real_clock

    for p in problems:
        print("FAIL: " + p)
    print("checked 5 cases - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
