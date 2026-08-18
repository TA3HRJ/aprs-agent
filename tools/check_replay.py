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

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

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

    async def stub(question: str, sender: str = "") -> str:
        calls["n"] += 1
        return ANSWER

    gw._ask_ai = stub

    for _ in range(ASKED):
        await gw.handle(LINE)

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
    for p in problems:
        print("FAIL  " + p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
