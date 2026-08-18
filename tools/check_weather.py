#!/usr/bin/env python3
"""Fail if a weather answer arrives without the two facts that qualify it.

The gateway holds live readings from thousands of APRS weather stations and
refused every weather question for two nights. The template that fixes that
is only safe because it always says how far away the reading was taken and
how old it is - a 26C from 90 km away six hours ago is not the weather here,
and a model asked to summarise will drop exactly those two numbers.

Five things it holds:

  1. a weather question from a station with a known position is answered from
     the registry, with no model call at all
  2. the answer carries the distance
  3. the answer carries the age
  4. a station outside the radius is not reported as local weather
  5. a city name is refused rather than guessed - there is no geocoder here,
     and the wrong Izmir is worse than no answer
  6. a non-weather question still reaches the model

No network and no provider: the registry and the answer are both stubbed.

Usage:  python tools/check_weather.py
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
    "extra_sms": 3,
    "rate_burst": 0,
    "rate_refill_s": 0,
    "wx_radius_km": 100,        # pinned: the default is an operator's choice
}

# The sender, with a position. Anonymised, as every fixture here is.
ME = {
    "callsign": "TA1ABC-7", "lat": 38.4276, "lon": 27.1043,
    "locator": "KM38ok", "last_seen_ago_s": 300,
}

# A weather station 12 km away, read four minutes ago.
NEAR = {
    "callsign": "TA1ABC-13", "lat": 38.5276, "lon": 27.1543,
    "wx_temp_c": 26.1, "wx_humidity": 47, "wx_pressure_mb": 1009.8,
    "wx_wind_gust_ms": 6.3, "last_seen_ago_s": 240,
}


class FakeDB:
    """Registry with one weather station, placed by the test that calls it."""

    def __init__(self, wx=NEAR, reach_km=12.0):
        self._wx, self._reach = wx, reach_km

    def get_one(self, call):
        return dict(ME) if call in ("TA1ABC-7", "TA1ABC") else None

    def nearest_wx(self, lat, lon, max_km=100.0):
        if self._wx is None or self._reach > max_km:
            return None
        return dict(self._wx), self._reach


def line(sender: str, text: str) -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s" % (sender, text)


async def run() -> int:
    problems: list[str] = []

    CASES = [
        # label            sender      question                     db          expect
        ("nearby",        "TA1ABC-7", "what is the weather?",       FakeDB(),   "template"),
        ("turkish",       "TA1ABC-7", "hava durumu nasil?",         FakeDB(),   "template"),
        ("by grid",       "TA9XYZ-9", "weather in KM38ok?",         FakeDB(),   "template"),
        ("too far",       "TA1ABC-7", "weather?",                   FakeDB(NEAR, 180.0), "refused"),
        ("no position",   "TA9XYZ-9", "what is the weather here?",  FakeDB(),   "refused"),
        ("not weather",   "TA1ABC-7", "What is SWR?",               FakeDB(),   "model"),
    ]

    for label, sender, question, db, expect in CASES:
        sent: list[str] = []

        class Queue:
            async def put(self, b: bytes) -> None:
                sent.append(b.decode("utf-8").strip())

        gw = AIGateway(dict(CFG), "")
        gw.set_station_db(db)
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
                problems.append("%s: model not consulted (%d calls)"
                                % (label, asked["n"]))
        elif asked["n"] != 0:
            problems.append("%s: model was consulted, template should have "
                            "answered" % label)

        if expect == "template":
            if "26.1C" not in body:
                problems.append("%s: no reading in the answer -> %r"
                                % (label, body[:80]))
            if "km away" not in body:
                problems.append("%s: reading without a distance -> %r"
                                % (label, body[:80]))
            if "ago" not in body:
                problems.append("%s: reading without an age -> %r"
                                % (label, body[:80]))
        if expect == "refused":
            if "26.1C" in body:
                problems.append("%s: reported a reading it should not have "
                                "-> %r" % (label, body[:80]))

        print("  %-13s %-28s -> %s" % (label, question, body[:74]))

    # A city name must not be geocoded into somebody else's weather.
    sent2: list[str] = []

    class Q2:
        async def put(self, b: bytes) -> None:
            sent2.append(b.decode("utf-8").strip())

    gw = AIGateway(dict(CFG), "")
    gw.set_station_db(FakeDB())
    gw._own_writer = Q2()
    asked2 = {"n": 0}

    async def stub2(q: str, s: str = "") -> str:
        asked2["n"] += 1
        return "It is 30C and sunny in Ankara."

    gw._ask_ai = stub2
    await gw.handle(line("TA9XYZ-9", "what is the weather in Ankara?"))
    body2 = " ".join(s.split(":", 2)[-1] for s in sent2 if ":ack" not in s)
    if "30C" in body2:
        problems.append("city name: invented a reading for a place it cannot "
                        "locate -> %r" % body2[:80])
    print("  %-13s %-28s -> %s" % ("city name", "weather in Ankara?", body2[:74]))

    # The daily ceiling caps the provider bill. A template answer sends no
    # bill, so an exhausted ceiling must not silence one.
    sent3 = []

    class Q3:
        async def put(self, b):
            sent3.append(b.decode("utf-8").strip())

    gw = AIGateway(dict(CFG, daily_limit=1), "")
    gw.set_station_db(FakeDB())
    gw._own_writer = Q3()
    gw._day_count = 99          # ceiling already reached today
    import time as _t
    gw._day = _t.strftime("%Y-%m-%d", _t.gmtime())

    async def stub3(q, s=""):
        return "MODEL ANSWER"

    gw._ask_ai = stub3
    await gw.handle(line("TA1ABC-7", "what is the weather?"))
    body3 = " ".join(s.split(":", 2)[-1] for s in sent3 if ":ack" not in s)
    if "26.1C" not in body3:
        problems.append("daily ceiling: silenced a free template answer -> %r"
                        % body3[:80])
    print("  %-13s %-28s -> %s" % ("quota spent", "what is the weather?", body3[:74]))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
