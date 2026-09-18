#!/usr/bin/env python3
"""Fail if the gateway can reuse a message number across a restart.

Measured 2026-09-19. TA3HRJ-10 asked DMWGPT "What is my location?" from the
aprs.fi iPhone app and saw one line. The gateway had sent two, and the app had
acknowledged both:

    DMWGPT -> TA3HRJ-10  {2  "TA3HRJ-10: 38.455,27.108 (KM38nk) 12d ago ..."
    DMWGPT -> TA3HRJ-10  {4  "feed only; full history: aprs.fi"
    TA3HRJ-10 -> DMWGPT  ack2, ack4

Thirteen days earlier the same station had asked "Test", and the reply had
carried {2 and {4 as well. Both were the first reply of their process: the
counter started from zero at every restart, so the first reply after any
restart was numbered 2 and 4 whoever it went to. APRS clients discard a
message whose sender and number they have already seen, and acknowledge it
anyway - which is exactly what an acknowledged line that never appears looks
like. Five restarts on 2026-09-17 alone.

The formula also stepped by two, (n + 1) % 999 + 1, halving a range that was
already only 999 wide.

What must hold:

  1. replies to the same station from two lifetimes of the gateway, sharing a
     config path, carry different numbers - the number survives a restart
  2. without a config path to keep it in, two lifetimes started at different
     times still start from different numbers
  3. consecutive numbers step by one
  4. every number is 1-5 digits, which is what the APRS message format allows
  5. the counter wraps from 99999 to 1
  6. a state file that cannot be written does not stop the reply

No network and no provider: the answer is stubbed.

Usage:  python tools/check_msg_ids.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 0,
    "rate_refill_s": 0,
}
LINE = "TA1ABC-10>APFII0,TCPIP*,qAC,APRSFI::DMWGPT   :what is the capital of peru{00591"
ANSWER = ("Lima is the capital of Peru, on the Pacific coast, "
          "and has been since the Spanish founded it in 1535.")

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


class Sink:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def reply_ids(sent: list[str]) -> list[str]:
    out = []
    for s in sent:
        if "::TA1ABC-10" in s and ":ack" not in s:
            m = re.search(r"\{([^{}]*)$", s)
            if m:
                out.append(m.group(1))
    return out


async def one_lifetime(config_path: str) -> list[str]:
    gw = AIGateway(dict(CFG), config_path)
    sink = Sink()
    gw._own_writer = sink

    async def stub(question: str, sender: str = "") -> str:
        return ANSWER

    gw._ask_ai = stub
    await gw.handle(LINE)
    return reply_ids(sink.sent)


async def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cfg_path = str(Path(tmp) / "aprsconfig.toml")

        # 1: the number survives a restart
        first = await one_lifetime(cfg_path)
        second = await one_lifetime(cfg_path)
        if len(first) < 2 or len(second) < 2:
            fail("restart", f"expected two-part replies, got {first} and {second}")
        elif set(first) & set(second):
            fail("restart",
                 f"the same station got numbers {first} before a restart and "
                 f"{second} after it - a client discards the repeats as "
                 f"duplicates and still acknowledges them (the 2026-09-19 fault)")
        else:
            ok(f"numbers survive a restart: {first} then {second}")

        # 6: an unwritable state file does not stop the reply
        bad_path = str(Path(tmp) / "no-such-dir" / "aprsconfig.toml")
        try:
            ids = await one_lifetime(bad_path)
            if len(ids) >= 2:
                ok("a state file that cannot be written does not stop the reply")
            else:
                fail("unwritable state", f"reply not sent in full: {ids}")
        except Exception as e:
            fail("unwritable state", f"{type(e).__name__}: {e}")

    # 2: without a state file, two start times give different numbers
    real_clock = getattr(aig, "_clock", None)
    try:
        aig._clock = lambda: 1_790_000_000.0
        early = await one_lifetime("")
        aig._clock = lambda: 1_790_000_000.0 + 3600
        late = await one_lifetime("")
    finally:
        if real_clock is None:
            try:
                delattr(aig, "_clock")
            except AttributeError:
                pass
        else:
            aig._clock = real_clock
    if set(early) & set(late):
        fail("no state file",
             f"two lifetimes an hour apart both used {sorted(set(early) & set(late))} "
             f"- without somewhere to keep the counter it must not start from a "
             f"constant")
    else:
        ok(f"without a state file, start time decides: {early} vs {late}")

    # 3, 4, 5: step, shape, wrap
    gw = AIGateway(dict(CFG), "")
    a, b, c = gw._next_msg_id(), gw._next_msg_id(), gw._next_msg_id()
    if not all(x.isdigit() for x in (a, b, c)) or int(b) - int(a) != 1 or int(c) - int(b) != 1:
        fail("step", f"consecutive numbers {a}, {b}, {c} do not step by one")
    else:
        ok(f"consecutive numbers step by one: {a}, {b}, {c}")
    if not all(re.fullmatch(r"[0-9]{1,5}", x) for x in (a, b, c)):
        fail("shape", f"numbers {a}, {b}, {c} are not 1-5 digits")
    else:
        ok("numbers are 1-5 digits")
    gw._msg_counter = 99999
    w = gw._next_msg_id()
    if w != "1":
        fail("wrap", f"after 99999 the next number was {w}, expected 1")
    else:
        ok("the counter wraps from 99999 to 1")


asyncio.get_event_loop().run_until_complete(run())
if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
