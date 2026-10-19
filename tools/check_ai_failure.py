#!/usr/bin/env python3
"""Fail if a provider that hangs or answers empty leaves a sender in silence,
or if an SWR figure is sent to the model to be got wrong.

F-2026-10-15-01: a provider call could hang for the OpenAI client's own
ten minutes, twice; a 200 with no answer in it raised a TypeError; and after
a failure the question stayed filed as "waiting on the model", so retries of
it were swallowed for ten minutes more.

F-2026-10-15-02: asked what SWR 2.5 means, the model gave the figures of
SWR 1.5 (4%, 1.5 dB; it is 18%, 0.9 dB).

What must hold:

  1. the OpenAI-compatible call sets a timeout of a minute or less and at
     most one retry
  2. a response with no choices, or a choice with no content, fails as
     "no answer", not as a TypeError, and the sender is not answered
  3. after a failed call, a retry of the same message is asked again rather
     than swallowed
  4. an SWR figure is answered without the model, with the right numbers,
     in the asker's language; "how do I lower it" still goes to the model

No network: the OpenAI client is replaced.

Usage:  python tools/check_ai_failure.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openai  # noqa: E402

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

_REAL_CLOCK = aig._clock
_OFFSET = {"s": 0.0}
aig._clock = lambda: _REAL_CLOCK() + _OFFSET["s"]
aig._RF_TURNAROUND_S = 0.0
aig._PART_GAP_S = 0.0
aig._RETRY_GAPS_S = ()

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
       "api_keys": {"deepseek": "stub"}, "rate_burst": 20,
       "rate_refill_s": 360, "extra_sms": 2}

SEEN: dict = {}
MODE = {"resp": "none"}


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, mode):
        self.choices = {"none": None, "empty": [], "nocontent": [_Choice(None)],
                        "ok": [_Choice("An answer.")]}[mode]


class _Completions:
    def create(self, **kw):
        SEEN["calls"] = SEEN.get("calls", 0) + 1
        return _Resp(MODE["resp"])


class _Chat:
    completions = _Completions()


class _FakeOpenAI:
    def __init__(self, **kw):
        SEEN["kw"] = kw
        self.chat = _Chat()


openai.OpenAI = _FakeOpenAI


def gateway(sent):
    class Q:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8").strip())
    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Q()
    errors = []
    gw.error = lambda m: errors.append(m)
    return gw, errors


def replies(sent, call):
    return [s for s in sent if "::" + call in s and ":ack" not in s]


async def main() -> int:
    problems = []

    # 1-2. the call's limits, and an empty 200
    for mode in ("none", "empty", "nocontent"):
        MODE["resp"] = mode
        SEEN.clear()
        gw, errors = gateway([])
        ans = await gw._ask_ai("hello", sender="W1ABC-8")
        kw = SEEN.get("kw", {})
        t = kw.get("timeout")
        if t is None or float(t) > 60:
            problems.append(f"{mode}: provider timeout {t!r}, want <= 60 s")
        if kw.get("max_retries", 2) > 1:
            problems.append(f"{mode}: max_retries {kw.get('max_retries', 2)!r}, want <= 1")
        if ans:
            problems.append(f"{mode}: an empty response produced an answer {ans!r}")
        if not errors or "TypeError" in errors[-1] or "no answer" not in errors[-1]:
            problems.append(f"{mode}: logged {errors[-1:]!r}, want 'no answer'")
        print(f"  choices={mode:9s} timeout={t} retries={kw.get('max_retries')} "
              f"-> {errors[-1] if errors else '(nothing logged)'}")

    # 3. a retry after a failure is asked again
    MODE["resp"] = "none"
    SEEN.clear()
    sent: list = []
    gw, _ = gateway(sent)
    line = ("W1ABC-8>APDR16,TCPIP*,qAC,T2X::DMWGPT   :"
            "what is the speed limit here{12")
    _OFFSET["s"] = 0.0
    await gw.handle(line)
    MODE["resp"] = "ok"
    _OFFSET["s"] = 45.0                  # the radio retries the same number
    await gw.handle(line)
    _OFFSET["s"] = 0.0
    got = replies(sent, "W1ABC-8")
    print(f"  failed, then retried: provider asked {SEEN.get('calls', 0)} times, "
          f"{len(got)} reply")
    if SEEN.get("calls", 0) != 2 or not got:
        problems.append("a retry after a failed call was swallowed - asked "
                        f"{SEEN.get('calls', 0)} times, {len(got)} replies")

    # 4. SWR, computed
    cases = (
        ("What does SWR 2.5 mean?", ("18%", "0.9 dB"), "en"),
        ("SWR 2.5 ne demek?", ("%18", "0.9 dB"), "tr"),
        ("SWR 2.5 NEDIR?", ("%18", "0.9 dB"), "tr"),
        ("Is SWR 1.5 good", ("4%", "0.2 dB"), "en"),
        ("my swr is 3.2, is it ok?", ("27%", "1.4 dB"), "en"),
    )
    for q, want, lang in cases:
        MODE["resp"] = "ok"
        SEEN.clear()
        sent = []
        gw, _ = gateway(sent)
        await gw.handle(f"TA3HX-4>APDR16,TCPIP*,qAC,T2X::DMWGPT   :{q}{{7")
        text = " ".join(s.split("::", 1)[1][10:].rsplit("{", 1)[0].removesuffix(" --")
                        for s in replies(sent, "TA3HX-4"))
        bad = []
        if SEEN.get("calls"):
            bad.append("went to the model")
        bad += [f"missing {w!r}" for w in want if w not in text]
        is_tr = "yansiyan" in text
        if (lang == "tr") != is_tr:
            bad.append(f"answered in the wrong language")
        print(f"  {q!r:30} -> {text!r}")
        if bad:
            problems.append(f"{q!r}: " + ", ".join(bad))
    for q in ("How do I lower SWR 2.5?", "what is the SWR test procedure"):
        SEEN.clear()
        sent = []
        gw, _ = gateway(sent)
        await gw.handle(f"TA3HX-4>APDR16,TCPIP*,qAC,T2X::DMWGPT   :{q}{{8")
        print(f"  {q!r:30} -> model asked {SEEN.get('calls', 0)} time(s)")
        if SEEN.get("calls") != 1:
            problems.append(f"{q!r} did not go to the model")

    if problems:
        print("\nFAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
