#!/usr/bin/env python3
"""Fail if a silence AI note can finish without saying how long it took.

AUDIT-2026-09-15 item 10: twelve silence assessments hit the 20 s read
timeout in one day, and the audit said to measure the provider's latency for
a week before choosing a new number. Nothing could be measured. Only
failures reached the journal - 28 since 2026-08-21, 27 of them inside three
hours on the evening of 2026-09-14 and one a 503 - while the ~130-360 notes a
day that succeeded left no trace of how long they took. A timeout set from
that would have been set from the outage, not from the ordinary answer.

The audit also said a longer timeout "costs nothing but a later note". It
does not: the monitor loop awaits each assessment in turn, so the next alert
in the same pass waits for its notification too.

What must hold:

  1. a note that arrives is logged with its duration and its cell
  2. a failure is logged with its duration and the provider's reason, and
     the alert still goes out with no note
  3. an empty answer (JSON that did not parse) says so
  4. no success line matches the patterns _count_log_lines counts as errors
     ("error", "fail", "fatal") - a measurement must not read as a fault
  5. the monitor loop reaches _assess_silence only through _silence_note, so
     a new caller cannot skip the timing

Usage:  python tools/check_ai_note_latency.py
Exit code 1 on failure.
"""
from __future__ import annotations

import ast
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


from web_gui import AgentManager  # noqa: E402


class _Probe(AgentManager):
    """Only what _silence_note touches; the provider is replaced."""

    def __init__(self, delay: float, answer=None, exc=None):
        self.said = []
        self._delay, self._answer, self._exc = delay, answer, exc

    def _log_both(self, msg: str) -> None:
        self.said.append(msg)

    async def _assess_silence(self, c: dict, ai_cfg: dict) -> str:
        await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._answer


SECONDS = re.compile(r"(\d+\.\d) s\b")


async def _cases() -> None:
    if not hasattr(AgentManager, "_silence_note"):
        fail("1-4", "AgentManager has no _silence_note - the call is not timed")
        return
    c = {"cell": "KM38"}

    # 1 - success
    p = _Probe(0.3, answer="[igate_failure/high] One gate went quiet.")
    note = await p._silence_note("KM38", c, {})
    line = " | ".join(p.said)
    m = SECONDS.search(line)
    if note != "[igate_failure/high] One gate went quiet.":
        fail("1 note", f"returned {note!r}")
    elif len(p.said) != 1 or "KM38" not in line or not m or not 0.25 <= float(m.group(1)) <= 1.0:
        fail("1 note", f"expected one line with KM38 and ~0.3 s, got {p.said!r}")
    else:
        ok(f"1 note logged: {line}")

    # 2 - failure
    p = _Probe(0.2, exc=TimeoutError("The read operation timed out"))
    note = await p._silence_note("KM38", c, {})
    line = " | ".join(p.said)
    m = SECONDS.search(line)
    if note != "":
        fail("2 failure", f"returned {note!r}, the alert must go out with no note")
    elif (len(p.said) != 1 or "failed" not in line or "timed out" not in line
          or not m or not 0.15 <= float(m.group(1)) <= 1.0):
        fail("2 failure", f"expected duration and reason, got {p.said!r}")
    else:
        ok(f"2 failure logged: {line}")

    # 3 - empty answer
    p = _Probe(0.0, answer="")
    await p._silence_note("KM38", c, {})
    if not p.said or "empty" not in p.said[-1]:
        fail("3 empty", f"got {p.said!r}")
    else:
        ok(f"3 empty answer says so: {p.said[-1]}")

    # 4 - a measurement is not an error, by the counter's own patterns
    import web_gui
    counted = [web_gui._ERR_RE, web_gui._AIERR_RE]
    for ans in ("[unknown/low] x", ""):
        p = _Probe(0.0, answer=ans)
        await p._silence_note("KM38", c, {})
        if any(r.search(s) for s in p.said for r in counted):
            fail("4 not an error", f"{p.said!r} would be counted as an error line")
            break
    else:
        ok("4 no success line reads as an error")


def _callers_of(name: str) -> list[str]:
    tree = ast.parse((ROOT / "web_gui.py").read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for node in ast.walk(fn):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr == name):
                    out.append(fn.name)
    return out


def main() -> int:
    asyncio.run(_cases())
    callers = sorted(set(_callers_of("_assess_silence")))
    if callers != ["_silence_note"]:
        fail("5 one door", f"_assess_silence is called from {callers}, "
                           f"expected only _silence_note")
    else:
        ok("5 _assess_silence is reached only through _silence_note")
    print(f"{FAIL} problems")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
