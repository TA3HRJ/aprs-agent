#!/usr/bin/env python3
"""Fail if a repeated question is met with silence instead of the answer again.

W3AKU-7 asked "what is the aprs freq in us" six times in five minutes and was
answered once, then "what is w3ya freq" twice and "where is w1aw?" three
times - eleven questions, three answers. From his side the gateway worked
intermittently for no visible reason.

Dedup was doing what it was built to do: absorb retries so one question costs
one AI call. But a retry usually means the answer never arrived, and
suppressing it turns a delivery failure into a permanent one. He was not
asking again for a second opinion; he never got the first.

So the cached answer is replayed - no AI call, and the person who did not
hear it gets another chance. This check holds both halves of that: the
provider must be asked exactly once, and the sender must be sent more than
one copy.

No network and no provider: the answer is stubbed.

Usage:  python tools/check_replay.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

# The retries this check is about were minutes apart on the air. Time does
# not pass inside a loop, so it is moved by hand; the gateway reads the
# clock through aig._clock and nowhere else.
_REAL_CLOCK = aig._clock
_OFFSET = {"s": 0.0}
aig._clock = lambda: _REAL_CLOCK() + _OFFSET["s"]

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 0,          # limiter off: this is about dedup alone
    "rate_refill_s": 0,
}

LINE = "W3AKU-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :what is the aprs freq in us"
ANSWER = "APRS in the US: 144.390 MHz FM nationwide."
ASKED = 6


async def run() -> int:
    sent: list[str] = []

    class Queue:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8").strip())

    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Queue()

    calls = {"n": 0}

    async def stub(question: str, sender: str = "", history=None) -> str:
        calls["n"] += 1
        return ANSWER

    gw._ask_ai = stub

    for i in range(ASKED):
        _OFFSET["s"] = i * 60.0          # W3AKU-7 asked over five minutes
        await gw.handle(LINE)
    _OFFSET["s"] = 0.0

    replies = [s for s in sent if "::W3AKU-7" in s and ":ack" not in s]
    ids = {s.rsplit("{", 1)[-1] for s in replies if "{" in s}

    problems = []
    if calls["n"] != 1:
        problems.append("provider asked %d times, expected 1 - a repeat must "
                        "not cost another call" % calls["n"])
    if len(replies) < 2:
        problems.append("%d reply sent for %d identical questions - a repeat "
                        "is met with silence" % (len(replies), ASKED))
    if len(ids) != len(replies):
        problems.append("replies reuse a message id, so a client will discard "
                        "the replay as a duplicate")

    print("asked %d times -> %d provider call(s), %d deliveries, %d message ids"
          % (ASKED, calls["n"], len(replies), len(ids)))

    # The same text with a DIFFERENT message number each time. KC1MUR-5 sent
    # "When was Dream Police by cheap trick released" twice inside a minute on
    # 2026-09-20; the numbers differed, so the key differed, and one question
    # cost two provider calls and two near-identical answers on a shared
    # channel. A person re-sending because nothing came back writes exactly
    # this, and they must still be answered - just not paid for twice.
    sent2: list[str] = []

    class Queue2:
        async def put(self, b: bytes) -> None:
            sent2.append(b.decode("utf-8").strip())

    gw2 = AIGateway(dict(CFG), "")
    gw2._own_writer = Queue2()
    calls2 = {"n": 0}

    async def stub2(question: str, sender: str = "", history=None) -> str:
        calls2["n"] += 1
        return ANSWER

    gw2._ask_ai = stub2

    numbered = ("KC1MUR-5>APDR16,TCPIP*,qAC,T2X::DMWGPT   :"
                "When was Dream Police by cheap trick released{%s")
    for i, n in enumerate(("17", "18")):
        _OFFSET["s"] = i * 60.0          # a minute apart, as KC1MUR-5 sent it
        await gw2.handle(numbered % n)
    _OFFSET["s"] = 0.0

    replies2 = [s for s in sent2 if "::KC1MUR-5" in s and ":ack" not in s]
    if calls2["n"] != 1:
        problems.append("the same text sent twice with different message "
                        "numbers cost %d provider calls" % calls2["n"])
    if not replies2:
        problems.append("a re-send with a new message number was met with "
                        "silence")
    print("same text, two message numbers -> %d provider call(s), %d "
          "deliveries" % (calls2["n"], len(replies2)))

    # A copy that arrives in the same second is the sender's own client
    # sending twice, not somebody who waited and heard nothing. N1QQA did
    # exactly this on 2026-09-20: every question arrived twice, and each
    # answer went out twice - four transmissions for one question, on a
    # shared channel. A replay is for a retry, and a retry takes time.
    sent4: list[str] = []

    class Queue4:
        async def put(self, b: bytes) -> None:
            sent4.append(b.decode("utf-8").strip())

    gw4 = AIGateway(dict(CFG), "")
    gw4._own_writer = Queue4()
    calls4 = {"n": 0}

    async def stub4(question: str, sender: str = "", history=None) -> str:
        calls4["n"] += 1
        return ANSWER

    gw4._ask_ai = stub4
    twice = ("N1QQA>APDR16,TCPIP*,qAC,T2X::DMWGPT   :"
             "What is tomorrows weather outlook for wakefield NH?{%s")
    await gw4.handle(twice % "21")
    await gw4.handle(twice % "22")
    replies4 = [s for s in sent4 if "::N1QQA" in s and ":ack" not in s]
    if calls4["n"] != 1:
        problems.append("an immediate duplicate cost %d provider calls"
                        % calls4["n"])
    if len(replies4) > 1:
        problems.append("a duplicate arriving in the same second was "
                        "replayed: %d transmissions for one question"
                        % len(replies4))
    print("duplicate in the same second -> %d provider call(s), %d deliveries"
          % (calls4["n"], len(replies4)))
    for p in problems:
        print("FAIL  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
