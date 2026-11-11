#!/usr/bin/env python3
"""Fail if the gateway and its model disagree about the rate limit, or if a
refusal is transmitted more than once.

2026-11-10 22:35-23:28 UTC+1, YO7CHY on two radios (-1 and -5), with the
limit at 5 questions then one every 6 minutes:

    22:49:44  how many questions may i ask you ?
              -> (model) Ask as many as you like; no fixed limit.
    23:18:22  why you ask me to wait ?
              -> (model) I didn't ask you to wait ... Possibly a delayed or
                 duplicated packet from the gateway.

The notice "Too many questions - please wait N min" is sent by the code and
never reached the model's history or rules. YO7CHY-5 never acked, so its
notice went out four times (resends 40/60/120 s); and after YO7CHY-1 was
told, YO7CHY-5 met silence, because "told" was the base callsign's.

What must hold (the model and the network stubbed, resends shortened):

  1. a refusal goes out once, even unacked; an answer is still resent
  2. "told" is per full callsign: another SSID of the same station is told
     once too, the same SSID only once
  3. a question about the limit ("how many questions", "why ... wait",
     the notice quoted back, Turkish "kac soru") is answered by the code,
     with the configured numbers and this station's wait, no model call and
     no token spent; once per 10 min, then the ordinary path
  4. a notice that was sent is in the history the model gets next
  5. the model's rules state the limit and the notice, and forbid denying a
     message or inventing a cause

Usage:  python tools/check_rate_talk.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

RETRY = (0.15, 0.15, 0.15)
aig._RF_TURNAROUND_S = 0.0
aig._PART_GAP_S = 0.0
aig._RETRY_GAPS_S = RETRY

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "anthropic",
       "api_keys": {"anthropic": "stub"}, "extra_sms": 2,
       "rate_burst": 2, "rate_refill_s": 360}
NET = "APDR16,TCPIP*,qAC,T2X"


def line(sender, text, mid):
    return "%s>%s::DMWGPT   :%s{%s" % (sender, NET, text, mid)


class Rec:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        s = b.decode("utf-8", "replace").strip()
        to, body = s.split("::", 1)[1][:9].strip(), s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            return
        self.sent.append((to, body.rsplit("{", 1)[0]))


def new_gateway():
    gw = AIGateway(dict(CFG), "")
    rec = Rec()
    gw._own_writer = rec
    seen = []

    async def stub(question, sender="", history=None):
        seen.append({"q": question, "history": list(history or [])})
        return "A short answer."

    gw._ask_ai = stub
    return gw, rec, seen


def count(rec, to, text):
    return sum(1 for t, b in rec.sent if t == to and text in b)


SYSTEM: list = []


class _Resp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"content": [{"type": "text", "text": "OK."}]}


class _Client:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, headers=None, json=None):
        SYSTEM.append((json or {}).get("system", ""))
        return _Resp()


async def run() -> int:
    p = []
    LIMIT = getattr(aig, "_LIMIT_MSG", None)
    LIMIT_TR = getattr(aig, "_LIMIT_MSG_TR", None)
    if LIMIT is None:
        p.append("no limit-question pattern")
    gw, rec, seen = new_gateway()
    for i, q in enumerate(("what is a t2lt antenna", "what is a dipole"), 1):
        await gw.handle(line("YO7CHY-1", q, str(i)))
    await gw.handle(line("YO7CHY-1", "you run on a local computer ?", "3"))
    await gw.handle(line("YO7CHY-5", "What you ca-n do?", "4"))
    await gw.handle(line("YO7CHY-5", "H", "5"))
    await asyncio.sleep(sum(RETRY) + 0.3)
    n1 = count(rec, "YO7CHY-1", "Too many questions")
    n5 = count(rec, "YO7CHY-5", "Too many questions")
    ans = count(rec, "YO7CHY-1", "A short answer.")
    print(f"  notice to -1 x{n1}, to -5 x{n5}; first answer sent x{ans // 2}")
    if n1 != 1:
        p.append(f"the notice to YO7CHY-1 went out {n1} times, expected once")
    if n5 != 1:
        p.append(f"YO7CHY-5 was told {n5} times, expected once (its own SSID)")
    if ans < 2 * (1 + len(RETRY)):
        p.append("an unacked answer is no longer resent")

    calls = len(seen)
    tokens = gw._buckets["YO7CHY"][0]
    for text, mid in (("how many questions may i ask you ?", "6"),):
        await gw.handle(line("YO7CHY-1", text, mid))
    got = " ".join(b for t, b in rec.sent if t == "YO7CHY-1" and "Limit per station" in b
                   or (t == "YO7CHY-1" and "radio channel" in b))
    print(f"  limit answer: {got[:110]!r}")
    if "2 questions" not in got or "1 every 6 min" not in got or "Next one in" not in got:
        p.append(f"the limit question was not answered by the code with the numbers: {got!r}")
    if len(seen) != calls:
        p.append("the limit question reached the model")
    if gw._buckets["YO7CHY"][0] < tokens - 1e-6:
        p.append("the limit answer spent a token")

    for text in ("but you say too many questiona , wait", "why you ask me to wait ?",
                 "your answer : Too many questions - please wait 4 min"):
        if not (LIMIT and LIMIT.search(text)):
            p.append(f"not read as a limit question: {text!r}")
    for text in ("kac soru sorabilirim", "neden beklememi istiyorsun"):
        if not (LIMIT_TR and LIMIT_TR.search(text)):
            p.append(f"not read as a Turkish limit question: {text!r}")
    for text in ("what is a t2lt antenna", "speed of light", "wait for the beacon"):
        if LIMIT and LIMIT.search(text):
            p.append(f"an ordinary question read as a limit question: {text!r}")
    gw2, rec2, _ = new_gateway()
    await gw2.handle(line("TA1ABC-7", "kac soru sorabilirim", "1"))
    tr = " ".join(b for _, b in rec2.sent)
    if "2 soru" not in tr or "Simdi sorabilirsiniz" not in tr:
        p.append(f"Turkish limit answer: {tr!r}")
    b = gw2._buckets.get("TA1ABC")
    if b is not None and b[0] < 2.0 - 1e-6:
        p.append("asking about the limit spent a token")

    before = len(rec.sent)
    await gw.handle(line("YO7CHY-1", "how many questions can i send", "7"))
    again = [b for t, b in rec.sent[before:] if "radio channel" in b]
    if again:
        p.append("the limit answer was given twice within 10 minutes")

    gw._buckets["YO7CHY"][0] = 2.0          # a token earned back
    await gw.handle(line("YO7CHY-1", "why ?", "8"))
    hist = " ".join(str(x) for x in (seen[-1]["history"] if seen else []))
    if "Too many questions" not in hist:
        p.append(f"the notice is not in the history the model gets: {hist[:120]!r}")

    httpx.Client = _Client
    gw3 = AIGateway(dict(CFG), "")
    await gw3._ask_ai("hello", sender="YO7CHY-1")
    sp = (SYSTEM[-1] if SYSTEM else "").lower()
    for what, words in (("the numbers", ("2 questions", "every 6 minutes")),
                        ("the notice", ("too many questions",)),
                        ("never deny", ("never deny",)),
                        ("no invented cause", ("duplicated packets",))):
        if not all(w in sp for w in words):
            p.append(f"the model's rules lack {what}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
