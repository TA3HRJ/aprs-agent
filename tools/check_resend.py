#!/usr/bin/env python3
"""Fail if an answer part lost on the way to a radio is never sent again.

2026-09-27 23:02: TA3HX-7 sent TEST over RF. The gateway answered in two
parts. The first left under a second after the question and never arrived;
the second, five seconds later, did and was acked (ack59899). Nothing sent
the first one again: every part went out once, and the acks that would
have said which ones arrived were dropped unread. The radio that has just
transmitted is not yet listening, and APRS messaging everywhere else is
resend-until-acked.

The same review found the two replay loops sleeping after a part instead
of before the next one, which sent the first two parts back to back.

What must hold (delays shortened for the test):

  1. to a sender heard on RF (qAR), the first part waits the turnaround;
     to one typed online (qAC) it does not
  2. parts are spaced by the part gap, in a fresh answer and in a replay
  3. a part that draws no ack is sent again, the same message number, the
     configured number of times and no more
  4. an ack stops the resends of that part only; so does a rej, and so does
     the REPLY-ACK form "ackNN}"
  5. an ack for a number we never sent is ignored, and costs no answer

No network and no provider: the model is stubbed.

Usage:  python tools/check_resend.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

TURN, GAP, RETRY = 0.30, 0.20, (0.25, 0.25, 0.25)
aig._RF_TURNAROUND_S = TURN
aig._PART_GAP_S = GAP
aig._RETRY_GAPS_S = RETRY

_REAL_CLOCK = aig._clock
_OFFSET = {"s": 0.0}
aig._clock = lambda: _REAL_CLOCK() + _OFFSET["s"]

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "rate_burst": 20,
    "rate_refill_s": 360,
    "extra_sms": 2,
}
LONG = ("This answer is long enough to need two APRS message parts, "
        "so the second part follows the first after a gap.")
RF = "APAT89,WIDE1-1,qAR,TA1ABC-10"
NET = "APDR16,TCPIP*,qAC,T2TEST"


class Rec:
    def __init__(self):
        self.t0 = time.monotonic()
        self.sent = []          # (seconds since t0, text, msg id)

    async def put(self, b: bytes) -> None:
        s = b.decode("utf-8", "replace").strip()
        body = s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            return
        text, _, mid = body.rpartition("{")
        self.sent.append((time.monotonic() - self.t0, text, mid))


def new_gateway(answer=LONG):
    gw = AIGateway(dict(CFG), "")
    rec = Rec()
    gw._own_writer = rec
    calls = {"n": 0}

    async def stub(question, sender="", history=None):
        calls["n"] += 1
        return answer

    gw._ask_ai = stub
    return gw, rec, calls


def line(sender, text, path, mid=""):
    return "%s>%s::DMWGPT   :%s%s" % (sender, path, text,
                                      ("{" + mid) if mid else "")


def ack(sender, mid, form="ack"):
    return "%s>%s::DMWGPT   :%s%s" % (sender, RF, form, mid)


async def run() -> int:
    problems = []

    # 1 - turnaround before the first part, RF only
    gw, rec, _ = new_gateway("Short answer.")
    rec.t0 = time.monotonic()
    await gw.handle(line("TA1ABC-7", "question one", RF))
    first_rf = rec.sent[0][0] if rec.sent else None
    gw2, rec2, _ = new_gateway("Short answer.")
    rec2.t0 = time.monotonic()
    await gw2.handle(line("W1ABC-9", "question one", NET))
    first_net = rec2.sent[0][0] if rec2.sent else None
    print("  first part: RF after %s s, internet after %s s"
          % (None if first_rf is None else round(first_rf, 2),
             None if first_net is None else round(first_net, 2)))
    if first_rf is None or first_rf < TURN * 0.9:
        problems.append("the first part to an RF sender did not wait the "
                        "turnaround (%s s)" % first_rf)
    if first_net is None or first_net > TURN * 0.5:
        problems.append("a sender typed online was made to wait (%s s)" % first_net)

    # 2-4 - two parts, spaced; resends until acked
    gw, rec, _ = new_gateway()
    rec.t0 = time.monotonic()
    await gw.handle(line("TA1ABC-7", "tell me something long", RF, "12"))
    parts = [(t, txt, mid) for t, txt, mid in rec.sent]
    if len(parts) != 2:
        problems.append("expected a two-part answer, got %d" % len(parts))
    else:
        gap = parts[1][0] - parts[0][0]
        print("  gap between parts: %.2f s" % gap)
        if gap < GAP * 0.9:
            problems.append("parts were not spaced (%.2f s)" % gap)
        m1, m2 = parts[0][2], parts[1][2]
        # the radio acks the second part only, as TA3HX-7 did
        await gw.handle(ack("TA1ABC-7", m2))
        await asyncio.sleep(sum(RETRY) + 0.3)
        c1 = sum(1 for _, _, m in rec.sent if m == m1)
        c2 = sum(1 for _, _, m in rec.sent if m == m2)
        print("  sends: unacked part %s x%d, acked part %s x%d" % (m1, c1, m2, c2))
        if c1 != 1 + len(RETRY):
            problems.append("the unacked part was sent %d times, expected %d"
                            % (c1, 1 + len(RETRY)))
        if c2 != 1:
            problems.append("the acked part was sent again (%d times)" % c2)
        if any(txt != parts[0][1] for _, txt, m in rec.sent if m == m1):
            problems.append("a resend changed the text of the part")

    # 4 - rej and the REPLY-ACK form also stop resends
    for form, label in (("rej", "rej"), ("ack", "REPLY-ACK")):
        gw, rec, _ = new_gateway("Short answer.")
        rec.t0 = time.monotonic()
        await gw.handle(line("TA1ABC-7", "question %s" % label, NET, "7"))
        mid = rec.sent[0][2] if rec.sent else "?"
        tail = "}" if label == "REPLY-ACK" else ""
        await gw.handle(ack("TA1ABC-7", mid + tail, form))
        await asyncio.sleep(sum(RETRY) + 0.3)
        n = sum(1 for _, _, m in rec.sent if m == mid)
        if n != 1:
            problems.append("a %s did not stop the resends (%d sends)" % (label, n))

    # 5 - an ack for a number we never sent
    gw, rec, calls = new_gateway()
    await gw.handle(ack("TA1ABC-7", "99999"))
    if rec.sent or calls["n"]:
        problems.append("a stray ack produced traffic or a model call")

    # 2 - a replay is spaced too (the loops used to send parts 1 and 2 together)
    gw, rec, calls = new_gateway()
    await gw.handle(line("TA1ABC-7", "replay me please", NET, "30"))
    for _, _, m in list(rec.sent):
        await gw.handle(ack("TA1ABC-7", m))
    _OFFSET["s"] += 40            # past the replay floor, inside the cache window
    before = len(rec.sent)
    rec.t0 = time.monotonic()
    await gw.handle(line("TA1ABC-7", "replay me please", NET, "30"))
    replay = rec.sent[before:]
    if calls["n"] != 1:
        problems.append("the replay asked the model again (%d calls)" % calls["n"])
    if len(replay) != 2:
        problems.append("the replay sent %d parts, expected 2" % len(replay))
    else:
        g = replay[1][0] - replay[0][0]
        print("  gap between replayed parts: %.2f s" % g)
        if g < GAP * 0.9:
            problems.append("replayed parts went out back to back (%.2f s)" % g)

    for p in problems:
        print("FAIL: " + p)
    print("checked 5 behaviours - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
