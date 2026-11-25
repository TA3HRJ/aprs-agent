#!/usr/bin/env python3
"""Fail if the AI gateway answers an automatic reply or a bare sign-off.

An auto-responder answers every message it is sent, the gateway's answers
included, and each answer draws the next receipt. F-2026-09-27-01 was two
such machines exchanging 6,102 messages in 96 minutes. The receipt comes
from a real callsign, so the service-name test of F-2026-09-20-05 does not
catch it, and one station's receipts each end in a different time of day,
so the text dedup does not either. Measured 2026-11-25 with a stub model:
the PT2VHF client's default auto-reply, that station's receipt, "73" and
"tnx 73" each cost one model call and two transmissions (F-2026-11-25-01).

What must hold (no network, stub model):

  1. an automatic reply - English, Portuguese, Turkish, German, with or
     without a time of day on the end - is acked, not answered, and costs
     no model call
  2. a sign-off on its own (73, tnx 73, QRT, bye) likewise
  3. a question that uses the same words is still answered: "Are you
     away?", "is my message received?", "mesajim alindi mi"
  4. ordinary questions and greetings are still answered
  5. an auto-responder that receipts the gateway's answer gets nothing back:
     one question, one model call, however many receipts follow

Usage:  python tools/check_auto_reply.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

aig._RF_TURNAROUND_S = 0.0
aig._PART_GAP_S = 0.01
aig._RETRY_GAPS_S = (0.1,)

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "anthropic",
       "api_keys": {"anthropic": "stub"}, "rate_burst": 0, "rate_refill_s": 0}
NET = "APRS,TCPIP*,qAC,T2TEST"

AUTO = [
    "Mensagem recebida. Retornarei assim que possivel.",   # PT2VHF default
    "Mensagem recebida. Retornarei assim que possível.",
    "Mesajiniz alindi. Tesekkur ediyoruz - DARD81 (19:05:25)",
    "Mesajınız alındı. Teşekkür ediyoruz - DARD81 (03:28:23)",
    "Mesajin alindi. N0CALL / CLUB",
    "Auto-reply: I am away from the radio",
    "AUTOREPLY - not at the station, will reply later",
    "I'm away, will be back at 18z",
    "Nachricht erhalten, ich bin abwesend",
]
SIGNOFF = ["73", "tnx 73", "QRT", "bye", "Thanks!"]
ASKED = [
    "Are you away?",
    "is my message received?",
    "mesajim alindi mi",
    "What does auto reply mean in APRS?",
    "Why was my message received twice",
]
ORDINARY = ["Hello", "igate near me", "What is APRS?", "DATE",
            "Will it rain in KM38 tomorrow"]


class Rec:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8", "replace"))


def gateway():
    gw = AIGateway(dict(CFG), "")
    rec = Rec()
    gw._own_writer = rec
    gw.log = gw.warn = lambda *a, **k: None      # quiet
    calls: list[str] = []

    async def stub(question, sender="", history=None):
        calls.append(question)
        return "A short answer."

    gw._ask_ai = stub
    return gw, rec, calls


def pkt(sender: str, text: str, mid: str) -> str:
    return f"{sender}>{NET}::DMWGPT   :{text}{{{mid}"


async def one(text: str):
    gw, rec, calls = gateway()
    await gw.handle(pkt("N0CALL-9", text, "12"))
    await asyncio.sleep(0.25)
    acks = sum(1 for s in rec.sent if ":ack12" in s)
    texts = [s for s in rec.sent if "::N0CALL-9" in s and ":ack" not in s]
    return len(calls), len(texts), acks


async def run(p: list) -> None:
    for group, want_answer in ((AUTO, False), (SIGNOFF, False),
                               (ASKED, True), (ORDINARY, True)):
        for text in group:
            n_calls, n_text, acks = await one(text)
            answered = n_text > 0
            print(f"  {text[:52]!r:56} model {n_calls}, sent {n_text}, "
                  f"ack {acks}")
            if acks != 1:
                p.append(f"{text!r} drew {acks} acks, expected 1")
            if want_answer and not answered:
                p.append(f"a question went unanswered: {text!r}")
            if not want_answer and (answered or n_calls):
                p.append(f"answered {text!r} ({n_calls} model calls, "
                         f"{n_text} packets)")

    # 5: an auto-responder receipting the gateway's answer
    gw, rec, calls = gateway()
    await gw.handle(pkt("N0CALL-7", "What is a digipeater?", "1"))
    await asyncio.sleep(0.05)
    for i, t in enumerate(("19:05:25", "19:05:31", "19:06:02")):
        await gw.handle(pkt("N0CALL-7", f"Mesajiniz alindi. Tesekkur "
                                        f"ediyoruz - DARD81 ({t})", f"{i + 2}"))
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.25)
    print(f"  question then 3 receipts: {len(calls)} model call(s)")
    if len(calls) != 1:
        p.append(f"one question and three receipts cost {len(calls)} model "
                 f"calls, expected 1")


def main() -> int:
    p: list[str] = []
    if not hasattr(aig, "_not_for_answer"):
        p.append("no test for automatic replies and sign-offs")
    with redirect_stderr(io.StringIO()):
        asyncio.run(run(p))
    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
