#!/usr/bin/env python3
"""Fail if a background loop can die in silence, or if one scan's error can
end the watch.

Measured live. `_silence_watch_loop` stopped on 2026-08-29 at 16:45:26 and
nothing said so for 39 hours. Three days of journal held no traceback and no
"Task exception was never retrieved"; a py-spy dump showed both event loops
idle in select, so the task was not hung - it was gone. The map went on
showing silence cells the whole time, because those are computed per request,
so the only visible symptom was that alerts had stopped carrying an AI note.

Two independent faults produced that, and both are held here:

  the death was inaudible
    1. the loop's task must be referenced by the manager, so CPython cannot
       collect it mid-flight and swallow the exception with it
    2. a loop that raises must say so, with the traceback, at failure time
    3. a loop that RETURNS must say so too - none of them has a return path,
       so a clean exit is a fault as much as a crash is
    4. a cancelled task is shutdown, not a fault, and must stay quiet

  one bad scan ended everything
    5. an exception raised inside the scan body must not leave the loop
    6. and the loop must go on scanning afterwards

Usage:  python tools/check_watch_survives.py
Exit code 1 on failure.
"""
from __future__ import annotations

import ast
import asyncio
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


# ── 1-4: the supervisor ───────────────────────────────────────────────
from web_gui import AgentManager  # noqa: E402


class _Probe(AgentManager):
    """Only the two things _supervise touches."""

    def __init__(self):
        self._loop_tasks = set()
        self.said = []

    def _log_both(self, msg: str) -> None:
        self.said.append(msg)


async def _supervisor_cases() -> None:
    # 2. a loop that raises is reported, with the traceback
    p = _Probe()

    async def boom():
        raise RuntimeError("scan exploded")

    t = asyncio.ensure_future(boom())
    p._supervise(t, "silence")
    if t not in p._loop_tasks:
        fail("reference held", "the task was not kept anywhere")
    else:
        ok("reference held while running")
    await asyncio.sleep(0.05)
    said = "\n".join(p.said)
    if "RuntimeError" not in said or "scan exploded" not in said:
        fail("raise reported", f"nothing useful was said: {p.said!r}")
    elif "Traceback" not in said:
        fail("traceback reported", "the exception was named without its traceback")
    else:
        ok("a loop that raises is reported with its traceback")
    if t in p._loop_tasks:
        fail("reference released", "a finished task was never released")
    else:
        ok("reference released when finished")

    # 3. a loop that returns is reported too
    p = _Probe()

    async def quiet():
        return

    t = asyncio.ensure_future(quiet())
    p._supervise(t, "silence")
    await asyncio.sleep(0.05)
    if not any("EXITED" in m for m in p.said):
        fail("clean exit reported", f"a returning loop said nothing: {p.said!r}")
    else:
        ok("a loop that returns without error is still reported")

    # 4. cancellation is shutdown, not a fault
    p = _Probe()

    async def forever():
        await asyncio.sleep(3600)

    t = asyncio.ensure_future(forever())
    p._supervise(t, "silence")
    await asyncio.sleep(0.01)
    t.cancel()
    try:
        await t
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.05)
    if p.said:
        fail("cancel is quiet", f"shutdown was reported as a fault: {p.said!r}")
    else:
        ok("a cancelled loop is not reported as a fault")


asyncio.run(_supervisor_cases())

# ── 5-6: the scan body is guarded, and the loop keeps going ───────────
# Read the source rather than run it: the real body needs a live registry, a
# feed and a provider. What must be true is structural - the whole body sits
# inside a try, and the sleep that paces the loop is outside it, so a failed
# scan still waits before the next one instead of spinning.
src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
tree = ast.parse(src)

loop_fn = None
for node in ast.walk(tree):
    if isinstance(node, ast.AsyncFunctionDef) and node.name == "_silence_watch_loop":
        loop_fn = node
        break

if loop_fn is None:
    fail("loop found", "_silence_watch_loop is gone")
else:
    whiles = [n for n in loop_fn.body if isinstance(n, ast.While)]
    if not whiles:
        fail("loop found", "no `while` in _silence_watch_loop")
    else:
        body = whiles[0].body
        tries = [n for n in body if isinstance(n, ast.Try)]
        if len(tries) != 1 or not isinstance(body[0], ast.Try):
            fail("body guarded",
                 f"the scan body is not one try block at the top "
                 f"({len(tries)} try, first stmt {type(body[0]).__name__})")
        else:
            handlers = tries[0].handlers
            broad = [h for h in handlers
                     if h.type is not None and getattr(h.type, "id", "") == "Exception"]
            if not broad:
                fail("body guarded", "the guard does not catch Exception")
            else:
                ok("the whole scan body is inside one `except Exception` guard")

        tail = body[-1]
        is_sleep = (isinstance(tail, ast.Expr)
                    and isinstance(tail.value, ast.Await))
        if not is_sleep:
            fail("paced after failure",
                 "the loop does not end with an await outside the guard — "
                 "a failing scan would spin")
        else:
            ok("the pacing sleep is outside the guard, so a failure waits")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
