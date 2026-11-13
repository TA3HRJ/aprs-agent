#!/usr/bin/env python3
"""Fail if one question can set off a storm of transmissions.

2026-11-13 20:46-20:53 UTC+1, SP2ST-3 asked "Co to jest APRS?" once. Its
radio sent the question three more times. The gateway's ack went out only for
the first copy, so the radio never heard one and kept asking. Every copy
replayed the whole three-part answer with fresh message numbers, and each
replay got its own resends (40/60/120 s) on top of the first answer's.
About 40 transmissions went out for one question. Eleven of them came after
SP2ST-3 sent QRT.

The same evening YO7CHY-5, whose acks never arrive, got every answer four
times. It had acked nothing on 2026-11-10 either.

What must hold (the model stubbed, the delays shortened):

  1. every copy of a numbered message is acked, not only the first
  2. a repeat that arrives while the answer's resends are still running
     starts no replay. One question costs at most parts x (1 + resends)
     transmissions.
  3. a sign-off (QRT, 73, tnx) stops the resends of the earlier answer.
     A new question does not.
  4. a station that acked no part of its last answer gets the next one
     without resends, until it acks anything
  5. an ack still stops that part's resends
  6. under all of it, a ceiling: past _TX_CAP_N packets to one station in
     _TX_CAP_S nothing more is resent to it; a fresh answer still goes

Usage:  python tools/check_resend_storm.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

RETRY = (0.3, 0.3, 0.3)
aig._RF_TURNAROUND_S = 0.0
aig._PART_GAP_S = 0.02
aig._RETRY_GAPS_S = RETRY
CHAIN = sum(RETRY) + 0.4

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "anthropic",
       "api_keys": {"anthropic": "stub"}, "extra_sms": 2,
       "rate_burst": 0, "rate_refill_s": 0}
NET = "APDR16,TCPIP*,qAR,SR2ABC"
LONG = ("APRS to Automatic Packet Reporting System: cyfrowa transmisja "
        "krotkich pakietow przez radio, glownie pozycji, pogody i komunikatow, "
        "a takze wiadomosci tekstowych miedzy stacjami w calym kraju. 73")


def line(sender, text, mid=""):
    return "%s>%s::DMWGPT   :%s%s" % (sender, NET, text,
                                      ("{" + mid) if mid else "")


class Rec:
    def __init__(self):
        self.sent = []          # (to, body, id)

    async def put(self, b: bytes) -> None:
        s = b.decode("utf-8", "replace").strip()
        rest = s.split("::", 1)[1]
        to, body = rest[:9].strip(), rest[9:].lstrip(":")
        mid = body.rsplit("{", 1)[1] if "{" in body else ""
        self.sent.append((to, body.rsplit("{", 1)[0], mid))


def new_gateway(answers):
    gw = AIGateway(dict(CFG), "")
    gw._REPLAY_MIN_AGE_S = 0.05      # the radio's retries, sped up
    rec = Rec()
    gw._own_writer = rec

    async def stub(question, sender="", history=None):
        return answers.get(question, "A short answer.")

    gw._ask_ai = stub
    return gw, rec


def parts_of(rec, to, word):
    return [x for x in rec.sent if x[0] == to and word in x[1]]


async def run() -> int:
    p = []

    # 1-2: SP2ST-3's radio repeats one question, nothing is acked
    gw, rec = new_gateway({"Co to jest APRS?": LONG})
    await gw.handle(line("SP2ST-3", "Co to jest APRS?", "7"))
    for gap in (0.12, 0.15, 0.2):
        await asyncio.sleep(gap)
        await gw.handle(line("SP2ST-3", "Co to jest APRS?", "7"))
    await asyncio.sleep(0.1)
    await gw.handle(line("SP2ST-3", "Co to jest APRS?", "8"))  # numbered afresh
    await asyncio.sleep(CHAIN)
    tx = parts_of(rec, "SP2ST-3", "")
    tx = [x for x in tx if not x[1].startswith(("ack", "rej"))]
    n_parts = len({x[2] for x in tx[:3]})
    acks7 = sum(1 for x in rec.sent if x[0] == "SP2ST-3" and x[1] == "ack7")
    acks8 = sum(1 for x in rec.sent if x[0] == "SP2ST-3" and x[1] == "ack8")
    budget = 3 * (1 + len(RETRY))
    print(f"  one question, 5 copies: {len(tx)} transmissions "
          f"(budget {budget}); ack7 x{acks7}, ack8 x{acks8}")
    if n_parts != 3:
        p.append(f"the long answer was not three parts ({n_parts})")
    if len(tx) > budget:
        p.append(f"{len(tx)} transmissions for one question, more than "
                 f"{budget} (parts x (1 + resends))")
    if acks7 < 4:
        p.append(f"4 copies of message 7 drew {acks7} ack(s)")
    if acks8 < 1:
        p.append("the copy numbered afresh was not acked")

    # 3: a sign-off stops the resends; a new question does not
    gw, rec = new_gateway({"Co to jest APRS?": LONG})
    await gw.handle(line("SP2ST-3", "Co to jest APRS?", "1"))
    await asyncio.sleep(0.1)
    await gw.handle(line("SP2ST-3", "QRT", "2"))
    mark = len(rec.sent)
    await asyncio.sleep(CHAIN)
    after = [x for x in rec.sent[mark:] if "pakietow" in x[1] or "APRS to" in x[1]
             or "komunikatow" in x[1]]
    print(f"  after QRT: {len(after)} resends of the earlier answer")
    if after:
        p.append(f"{len(after)} resends of the answer went out after QRT")

    gw, rec = new_gateway({"Co to jest APRS?": LONG})
    await gw.handle(line("SP2ST-3", "Co to jest APRS?", "1"))
    await asyncio.sleep(0.1)
    await gw.handle(line("SP2ST-3", "a jak daleko?", "2"))
    await asyncio.sleep(CHAIN)
    first = parts_of(rec, "SP2ST-3", "APRS to")
    if len(first) != 1 + len(RETRY):
        p.append(f"a new question stopped the earlier answer's resends "
                 f"(first part sent x{len(first)})")

    # 4-5: a station that never acks; then it acks
    gw, rec = new_gateway({"q1": "Answer one.", "q2": "Answer two.",
                           "q3": "Answer three.", "q4": "Answer four."})
    await gw.handle(line("YO7CHY-5", "q1", "1"))
    await asyncio.sleep(CHAIN)
    await gw.handle(line("YO7CHY-5", "q2", "2"))
    await asyncio.sleep(CHAIN)
    a1 = len(parts_of(rec, "YO7CHY-5", "Answer one."))
    a2 = len(parts_of(rec, "YO7CHY-5", "Answer two."))
    print(f"  never acks: first answer x{a1}, second x{a2}")
    if a1 != 1 + len(RETRY):
        p.append(f"the first answer to a silent station went out x{a1}, "
                 f"expected {1 + len(RETRY)}")
    if a2 != 1:
        p.append(f"after an answer drew no ack, the next went out x{a2}, "
                 f"expected once")
    a2id = parts_of(rec, "YO7CHY-5", "Answer two.")[0][2]
    await gw.handle("YO7CHY-5>%s::DMWGPT   :ack%s" % (NET, a2id))
    await gw.handle(line("YO7CHY-5", "q3", "3"))
    await asyncio.sleep(0.1)
    a3 = parts_of(rec, "YO7CHY-5", "Answer three.")
    await gw.handle("YO7CHY-5>%s::DMWGPT   :ack%s" % (NET, a3[0][2]))
    await gw.handle(line("YO7CHY-5", "q4", "4"))
    await asyncio.sleep(CHAIN)
    a3 = len(parts_of(rec, "YO7CHY-5", "Answer three."))
    a4 = len(parts_of(rec, "YO7CHY-5", "Answer four."))
    print(f"  after it acks: third x{a3} (acked), fourth x{a4} (unacked)")
    if a3 != 1:
        p.append(f"an acked answer went out x{a3}")
    if a4 != 1 + len(RETRY):
        p.append(f"after an ack the station's answers are not resent again "
                 f"(x{a4})")

    # 6: the ceiling, lowered so one answer reaches it
    cap = getattr(aig, "_TX_CAP_N", None)
    if cap is None:
        p.append("no resend ceiling")
    else:
        aig._TX_CAP_N = 5
        gw, rec = new_gateway({"Co to jest APRS?": LONG, "q2": "Answer two."})
        await gw.handle(line("SP2ST-3", "Co to jest APRS?", "1"))
        await asyncio.sleep(CHAIN)
        n = len([x for x in rec.sent if x[0] == "SP2ST-3"
                 and not x[1].startswith("ack")])
        gw._no_ack_until.clear()
        await gw.handle(line("SP2ST-3", "q2", "2"))
        await asyncio.sleep(0.05)
        fresh = len(parts_of(rec, "SP2ST-3", "Answer two."))
        aig._TX_CAP_N = cap
        print(f"  ceiling 5: {n} packets for a 3-part answer; a fresh answer "
              f"after it x{fresh}")
        if n != 5:
            p.append(f"with a ceiling of 5, {n} packets went out")
        if fresh != 1:
            p.append("the ceiling stopped a fresh answer's first transmission")

    sign = getattr(aig, "_SIGN_OFF", None)
    for text in ("QRT", "73", "tnx 73", "73 de SP2ST", "Thanks!"):
        if not (sign and sign.match(text)):
            p.append(f"not read as a sign-off: {text!r}")
    for text in ("what is qrt", "73 MHz?", "thanks, how far is it"):
        if sign and sign.match(text):
            p.append(f"a question read as a sign-off: {text!r}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
