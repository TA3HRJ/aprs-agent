#!/usr/bin/env python3
"""Fail if the gateway mistakes what it was asked, or has nothing to say to
a newcomer who asks what it can do.

Both halves come from one afternoon on 2026-09-20, the first time strangers
from a Facebook APRS group put questions to DMWGPT.

WB2EHG-5 opened with "hello can you help me?", asked four questions, then
"what else can you do for me?" - and that one arrived as his sixth message,
so the rate limiter refused it. He asked the same thing again two minutes
later and got silence, which is what the limiter does after it has warned
someone once. The capability question is the one a newcomer always sends, it
costs nothing to answer, and it was the only question of the day that went
unanswered.

KR4MVP-5 asked "Tell me a joke about the weather" and was sent a temperature
reading from a station 28 km away. The weather shortcut matched the word
"weather" anywhere in the text and never let the question reach the model.

So: a capability question is answered from the code, once per sender per
window and without spending a token; and a question that merely mentions the
weather while asking for something else goes to the model like any other.

No network and no provider: the model and the registry are stubbed.

Usage:  python tools/check_gateway_intent.py
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
    "rate_burst": 5,
    "rate_refill_s": 360,
    "extra_sms": 2,           # what the live gateway allows: three parts
}

MODEL_ANSWER = "Model answer."
WX_REC = {
    "callsign": "KM6YFK-13",
    "wx_temp_c": 23.3,
    "wx_humidity": 92,
    "wx_pressure_mb": 1013,
    "wx_wind_gust_ms": 0.9,
    "wx_at": "3min ago",
    "last_heard": "3min ago",
}


class FakeDB:
    """Enough registry for the weather shortcut to fire if it wants to."""

    def get_one(self, call):
        return {"callsign": call, "lat": 40.6, "lon": -73.9}

    def nearest_wx(self, lat, lon, radius):
        return (dict(WX_REC), 28.0)


def line(sender: str, text: str) -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s" % (sender, text)


async def ask(gw, sent: list, sender: str, text: str) -> str:
    before = len(sent)
    await gw.handle(line(sender, text))
    replies = [s for s in sent[before:] if "::%s" % sender[:9] in s
               or "::%-9s" % sender in s]
    body = []
    for s in replies:
        if ":ack" in s.rsplit(":", 1)[-1]:
            continue
        part = s.split("::", 1)[1][9:].lstrip(":")
        body.append(part.rsplit("{", 1)[0].replace(" --", "").strip())
    return " ".join(body).strip()


def new_gateway(sent: list, calls: dict):
    class Queue:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Queue()
    gw.set_station_db(FakeDB())

    async def stub(question: str, sender: str = "", history=None) -> str:
        calls["n"] += 1
        calls["last"] = question
        return MODEL_ANSWER

    gw._ask_ai = stub
    return gw


async def run() -> int:
    problems = []

    # 1 - the capability question is answered, from the code, and for free
    sent, calls = [], {"n": 0, "last": ""}
    gw = new_gateway(sent, calls)
    answer = await ask(gw, sent, "WB2EHG-5", "what else can you do for me?")
    if not answer:
        problems.append("a capability question was met with silence")
    elif answer == MODEL_ANSWER:
        problems.append("a capability question went to the model - it has a "
                        "fixed answer and must not cost a call")
    if gw._buckets.get("WB2EHG"):
        problems.append("answering what-can-you-do spent a rate token; a "
                        "newcomer's first question must not use up the burst")
    if answer and not answer.isascii():
        problems.append("help text is not ASCII: %r" % answer)
    if answer and len(answer) > 200:
        problems.append("help text is %d chars, too many APRS parts"
                        % len(answer))

    # 2 - but it cannot be used to make the gateway transmit on demand
    second = await ask(gw, sent, "WB2EHG-5", "what else can you do for me?")
    third = await ask(gw, sent, "WB2EHG-5", "so what can you do")
    if third and third != MODEL_ANSWER:
        problems.append("the fixed help text came back twice in a row; after "
                        "the first it must follow the ordinary rules")
    del second

    # 2b - a Turkish sender is answered in Turkish, and APRS still carries
    # ASCII: the source text has its own letters, the packet must not
    sent, calls = [], {"n": 0, "last": ""}
    gw = new_gateway(sent, calls)
    answer = await ask(gw, sent, "TA3HX-7", "neler yapabilirsin?")
    if calls["n"]:
        problems.append("a Turkish capability question went to the model")
    if not answer.isascii():
        problems.append("Turkish help text went out unfolded: %r" % answer[:60])
    if answer.endswith("...") or "..." in answer:
        problems.append("help text was truncated at the part limit: %r"
                        % answer[-40:])
    if "APRS" not in answer.upper():
        problems.append("Turkish help text missing: %r" % answer[:60])

    # 2c - the same question asked sideways. Both of these were sent by real
    # stations on 2026-09-20 and both were answered by the model inventing a
    # description of the service.
    for phrasing in ("I wonder what you can help me with.",
                     "what can you help me with?"):
        sent, calls = [], {"n": 0, "last": ""}
        gw = new_gateway(sent, calls)
        answer = await ask(gw, sent, "DL5XL-9", phrasing)
        if calls["n"]:
            problems.append("%r went to the model" % phrasing)
        del answer

    # 2d - but a question that only begins like one is still a question
    sent, calls = [], {"n": 0, "last": ""}
    gw = new_gateway(sent, calls)
    answer = await ask(gw, sent, "K1ABC-9", "can you help me with converting "
                                            "miles to km")
    if calls["n"] != 1:
        problems.append("a real request beginning 'can you help me with' was "
                        "caught by the help text instead of the model")

    # 3 - a joke that mentions the weather is a joke
    sent, calls = [], {"n": 0, "last": ""}
    gw = new_gateway(sent, calls)
    answer = await ask(gw, sent, "KR4MVP-5", "Tell me a joke about the weather")
    if "23.3" in answer or "KM6YFK" in answer:
        problems.append("'a joke about the weather' was answered with a "
                        "weather report: %r" % answer[:70])
    if calls["n"] != 1:
        problems.append("the joke never reached the model (%d calls)"
                        % calls["n"])

    # 4 - and an actual weather question still gets the reading
    sent, calls = [], {"n": 0, "last": ""}
    gw = new_gateway(sent, calls)
    answer = await ask(gw, sent, "KR4MVP-5", "what is the weather near me")
    if "23.3" not in answer:
        problems.append("a real weather question no longer reaches the "
                        "registry: %r" % answer[:70])
    if calls["n"]:
        problems.append("a real weather question cost a model call")

    for p in problems:
        print("FAIL: " + p)
    print("checked 7 cases - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
