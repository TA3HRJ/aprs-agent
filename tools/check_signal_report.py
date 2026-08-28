#!/usr/bin/env python3
"""Fail if an invented signal report can reach the air, or if a real answer
about signal reports gets eaten.

Measured live on the public service. VK2AHB-7 in Australia sent "test.from VK"
and on 2026-08-28 the model replied:

    OK VK2AHB-7, receiving you 5x9. Test acknowledged. 73.

DMWGPT has no receiver. That packet arrived over TCP from the APRS-IS
backbone. "5x9" is a report on a radio path nobody measured, sent to an
operator who was, by the look of it, testing that exact path. The system
prompt already forbids role-playing a QSO; the model did it anyway, which is
the lesson _strip_signature was written from.

Two ways this can go wrong, and both are held here:

  it lets a false report through
    1. the observed case, with an ordinary sentence after it
    2. an answer that is ONLY the false report - the whole transmission is
       then a fabricated measurement, and it must still say something true
    3. the other phrasings a model reaches for: "you are 59", "loud and
       clear", "copy you 5 by 9"

  it cuts something it should not
    4. RST is a normal thing to be asked about. "RST = Readability, Signal,
       Tone" is a correct answer and contains no claim at all
    5. "599 is a typical CW contest report" explains a report without
       claiming one
    6. "I hear you" with no report token is not a measurement
    7. an ordinary answer with no radio talk in it is never touched

And the test path itself: a test message must be answered from the packet,
never by the model, and must say that no signal report is possible.

Usage:  python tools/check_signal_report.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import (  # noqa: E402
    _strip_signal_report, _test_answer,
)

# (label, input, must_not_contain, must_equal or None)
CASES = [
    # ── must be stripped ──────────────────────────────────────────────
    ("live case",       "OK VK2AHB-7, receiving you 5x9. Test acknowledged. 73.",
     "5x9", "Test acknowledged. 73."),
    ("only the report", "Receiving you 5x9.", "5x9", None),
    ("you are 59",      "You are 59 into my station. Ask me anything.",
     "59", "Ask me anything."),
    ("loud and clear",  "I copy you loud and clear. APRS is 144.390 in the US.",
     "loud and clear", "APRS is 144.390 in the US."),
    ("5 by 9",          "Copy you 5 by 9 here. 73.", "5 by 9", "73."),

    # ── must survive untouched ────────────────────────────────────────
    ("rst explained",   "RST = Readability, Signal, Tone. Readability 1-5, "
                        "Signal 1-9, Tone 1-9.", None, None),
    ("599 explained",   "599 is a typical CW contest report.", None, None),
    ("hear you only",   "I hear you asking about SWR.", None, None),
    ("plain answer",    "SWR is the ratio of forward to reflected power.",
     None, None),
    ("swr number",      "SWR 2.5 means about 18% of the power comes back.",
     None, None),
]

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


for label, text, banned, expect in CASES:
    out = _strip_signal_report(text)
    if banned is not None and banned.lower() in out.lower():
        fail(label, f"{banned!r} still present in {out!r}")
        continue
    if expect is not None and out != expect:
        fail(label, f"expected {expect!r}, got {out!r}")
        continue
    if banned is None and out != text:
        fail(label, f"changed an answer it should not touch: {out!r}")
        continue
    print(f"  ok    {label}")

# An answer that is nothing BUT the false report must still say something,
# and that something must not be a report.
only = _strip_signal_report("Receiving you 5x9.")
if not only or "5" in only:
    fail("empty result", f"left {only!r}")
else:
    print("  ok    empty result says something true")

# ── the test path ─────────────────────────────────────────────────────
RF_LINE = ("VK2AHB-7>APRS,WIDE1-1,qAR,VK2RAG-1::DMWGPT   :test.from VK")
IS_LINE = ("W1ABC>APRS,TCPIP*,qAC,T2SYDNEY::DMWGPT   :test")

a = _test_answer("test.from VK", "VK2AHB-7", RF_LINE)
if a is None:
    fail("test answered", "a test message was handed to the model")
elif "VK2RAG-1" not in a:
    fail("test names the gate", f"gate missing from {a!r}")
elif "signal" not in a.lower():
    fail("test refuses a report", f"no refusal in {a!r}")
else:
    print("  ok    RF test answered from the packet, gate named, report refused")

b = _test_answer("test", "W1ABC", IS_LINE)
if b is None:
    fail("internet test answered", "handed to the model")
elif "T2SYDNEY" in b:
    fail("internet test", f"named a backbone server as an igate: {b!r}")
else:
    print("  ok    internet-connected test names no igate")

# A question that merely contains the word must NOT be short-circuited.
c = _test_answer("What is the SWR test procedure for a dipole?", "TA1ABC", RF_LINE)
if c is not None:
    fail("real question", f"a question was answered as a test: {c!r}")
else:
    print("  ok    a question containing 'test' still reaches the model")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
