#!/usr/bin/env python3
"""Fail if a follow-up question arrives at the model stripped of what came
before it, or if asking a third time is met with silence.

2026-09-20, DL5XL-9, over half an hour:

    14:15:30  I want to travel from Bremen to Berlin. What is the best way?
    14:15:32  No live data here. Best bet: Deutsche Bahn train, Bremen Hbf --
    14:16:39  How long would it take by car?
    14:16:40  I don't have route or traffic data, and you haven't told me --
    14:16:45  the two places. Please resend with start and destination.

Each question was sent to the provider on its own, so the second one had no
subject. He then re-sent the same two messages four times over, which is what
someone does when they are trying to work out why a service does not follow
them - and the third repeat of one of them got nothing at all, because the
replay cache allows two and then goes quiet.

So: the last few exchanges with a sender ride along with the next question,
for ten minutes and in memory only; and when the replays are used up the
question takes the ordinary path again, where the token bucket - not silence -
is what limits it.

No network and no provider: the payload the model would have received is
captured instead.

Usage:  python tools/check_context.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 5,
    "rate_refill_s": 360,
}

Q1 = "I want to travel from Bremen to Berlin. What is the best way?"
A1 = "Best bet: DB train, Bremen Hbf to Berlin Hbf, roughly 4h."
Q2 = "How long would it take by car?"
A2 = "About 4h by car, 390km on the A1 and A2."


def line(sender: str, text: str, msg_id: str = "") -> str:
    tail = "{%s" % msg_id if msg_id else ""
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s%s" % (sender, text, tail)


def new_gateway(sent: list, seen: list, answers: list):
    class Queue:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Queue()

    async def stub(question: str, sender: str = "", history=None) -> str:
        seen.append({"question": question, "history": list(history or [])})
        return answers[min(len(seen), len(answers)) - 1]

    gw._ask_ai = stub
    return gw


def replies(sent: list, since: int, to_call: str) -> str:
    out = []
    for s in sent[since:]:
        if "::%-9s" % to_call not in s:
            continue
        body = s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            continue
        out.append(body.rsplit("{", 1)[0].replace(" --", "").strip())
    return " ".join(out)


async def run() -> int:
    problems = []

    # 1 - the follow-up carries the exchange before it
    sent, seen, = [], []
    gw = new_gateway(sent, seen, [A1, A2])
    await gw.handle(line("DL5XL-9", Q1, "11"))
    await gw.handle(line("DL5XL-9", Q2, "12"))
    if len(seen) != 2:
        problems.append("expected two provider calls, got %d" % len(seen))
    else:
        hist = seen[1]["history"]
        if not hist:
            problems.append("the follow-up reached the model with no history: "
                            "'%s' on its own" % seen[1]["question"])
        else:
            flat = " ".join(str(x) for x in hist)
            if "Bremen" not in flat or A1[:20] not in flat:
                problems.append("history does not carry the previous "
                                "question and answer: %r" % flat[:90])
        if seen[0]["history"]:
            problems.append("the first question carried history from nowhere")

    # 2 - another sender's conversation is not mixed in
    before = len(sent)
    await gw.handle(line("KR4MVP-5", Q2, "31"))
    if len(seen) == 3 and seen[2]["history"]:
        problems.append("one sender's history reached another sender's "
                        "question: %r" % str(seen[2]["history"])[:90])
    del before

    # 3 - and it is forgotten again
    sent, seen = [], []
    gw = new_gateway(sent, seen, [A1, A2])
    await gw.handle(line("DL5XL-9", Q1, "41"))
    real_clock = aig._clock
    try:
        aig._clock = lambda: real_clock() + 3600
        gw._processed.clear()
        await gw.handle(line("DL5XL-9", Q2, "42"))
    finally:
        aig._clock = real_clock
    if len(seen) == 2 and seen[1]["history"]:
        problems.append("an hour-old exchange was still attached to a new "
                        "question: %r" % str(seen[1]["history"])[:90])

    # 4 - the third identical question is answered, not met with silence
    sent, seen = [], []
    gw = new_gateway(sent, seen, [A1, A1, A1, A1])
    real = aig._clock
    for i in range(4):
        n = len(sent)
        # Minutes apart, as he sent them. A copy in the same second is a
        # client sending twice and is deliberately not replayed
        # (tools/check_replay.py holds that half).
        aig._clock = (lambda base, k: (lambda: base() + k * 90.0))(real, i)
        await gw.handle(line("DL5XL-9", Q1, "51"))
        if not replies(sent, n, "DL5XL-9"):
            problems.append("asking the same question %d times in a row left "
                            "the %dth unanswered" % (i + 1, i + 1))
            break
    aig._clock = real

    for p in problems:
        print("FAIL: " + p)
    print("checked 4 cases - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
