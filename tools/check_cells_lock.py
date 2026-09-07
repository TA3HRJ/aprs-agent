#!/usr/bin/env python3
"""Fail if the cell cache's lock can be shared across event loops, or if a
packet can be counted as one of this process's errors.

Both were found on 2026-09-07 by asking why the stat bar showed 337 errors.

**The lock.** `silence_cells_cached()` is called from two event loops: the
aiohttp app's, and the agent thread's. A module-level `asyncio.Lock` binds to
the first loop that uses it and raises `RuntimeError: bound to a different
event loop` for every caller on any other. `cells_warm_task` runs at app
startup and bound it to the web loop, so it was always the agent's silence
watch that lost — twelve times in nine hours, each one a scan that did not
happen:

    [silence] scan failed, watch continues: RuntimeError:
    <asyncio.locks.Lock object ...> is bound to a different event loop

That is also, almost certainly, what killed the watch outright on 2026-08-29.
F-2026-08-31-01 could not name the exception because the task was gone before
anyone looked; the guard added in v3.2.99 is what turned the next occurrence
into a line of text.

**The counter.** The Live Log carries packets as well as log lines, and the
error tally matched `error|fail|fatal` against every line — so a station whose
comment says "failsafe" raised the operator's error count. 337 shown against
65 real log lines over one uptime.

Usage:  python tools/check_cells_lock.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_gui  # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


# ── the lock, exercised from two loops the way the app does ───────────
results = {}


def _use_lock(tag: str) -> None:
    loop = asyncio.new_event_loop()
    try:
        async def _go():
            async with web_gui._get_cells_lock():
                await asyncio.sleep(0.05)
            return "ok"
        results[tag] = loop.run_until_complete(_go())
    except Exception as e:                       # noqa: BLE001
        results[tag] = f"{type(e).__name__}: {e}"
    finally:
        loop.close()


# The web loop takes it first, exactly as cells_warm_task does at startup.
_use_lock("web")
# Then the agent thread, with its own loop.
th = threading.Thread(target=_use_lock, args=("agent",))
th.start()
th.join(timeout=5)

if results.get("web") != "ok":
    fail("first loop", f"the first caller failed: {results.get('web')!r}")
else:
    ok("the first loop acquires the lock")

if results.get("agent") != "ok":
    fail("second loop",
         f"a caller on another loop failed: {results.get('agent')!r} — this is "
         f"the live fault of 2026-09-07")
else:
    ok("a second loop, in another thread, acquires it too")

# Concurrently, which is the case the lock exists for at all.
def _both() -> None:
    loop = asyncio.new_event_loop()
    try:
        async def _go():
            await asyncio.gather(*(_one() for _ in range(3)))

        async def _one():
            async with web_gui._get_cells_lock():
                await asyncio.sleep(0.01)
        loop.run_until_complete(_go())
        results["concurrent"] = "ok"
    except Exception as e:                       # noqa: BLE001
        results["concurrent"] = f"{type(e).__name__}: {e}"
    finally:
        loop.close()


_both()
if results.get("concurrent") != "ok":
    fail("same-loop serialisation", results["concurrent"])
else:
    ok("three callers on one loop still serialise")

# Closed loops must not accumulate: every loop above is closed by now.
leaked = [l for l in web_gui._cells_locks if l.is_closed()]
if len(web_gui._cells_locks) > 4:
    fail("loop table bounded",
         f"{len(web_gui._cells_locks)} locks retained for {len(leaked)} dead loops")
else:
    ok(f"the loop table stays small ({len(web_gui._cells_locks)} entries)")


# ── the lock, asserted structurally as well ───────────────────────────
# The behavioural test above passes on CPython 3.13, which no longer raises on
# a cross-loop Lock; the VPS runs 3.10, which does. So the behaviour cannot be
# demonstrated to fail on this machine, and the structure is asserted instead:
# the lock must be looked up BY the running loop, not shared.
import ast                                              # noqa: E402
import inspect                                          # noqa: E402

src = inspect.getsource(web_gui._get_cells_lock)
tree = ast.parse(src.lstrip())
calls = {getattr(getattr(n.func, "attr", None), "lower", lambda: "")()
         for n in ast.walk(tree) if isinstance(n, ast.Call)}
subscripted_by_loop = any(
    isinstance(n, ast.Name) and n.id == "loop"
    for n in ast.walk(tree)
)
if "get_running_loop" not in calls:
    fail("keyed by loop",
         "_get_cells_lock does not ask for the running loop — one lock is "
         "being shared across every loop, which is the 2026-09-07 fault")
elif not subscripted_by_loop:
    fail("keyed by loop", "the running loop is fetched but not used as the key")
else:
    ok("the lock is fetched per running loop, not shared across them")


# ── the error counter ─────────────────────────────────────────────────
class _Probe(web_gui.AgentManager):
    def __init__(self):
        self._err_count = 0
        self._ai_rx = 0
        self._ai_tx = 0


p = _Probe()
PACKETS = [
    "[logger] KC9ABC>APRS,TCPIP*:>Failsafe test beacon",
    "[logger] N0XYZ-9>APRS,WIDE1-1:=4012.34N/07430.12W-error margin 5m",
    "[logger] TA3ABC>APRS,qAR,YM3KC-8::TA3HRJ-7 :the antenna failed last night",
]
REAL = [
    "[telegram] poll error: TimeoutError: The read operation timed out",
    "[silence] scan failed, watch continues: RuntimeError: bound to a different loop",
    "[station-db] SQLite save failed: disk I/O error",
    "Read error from APRS-IS: connection reset",
]
p._count_log_lines("\n".join(PACKETS))
if p._err_count:
    fail("packets are not errors",
         f"{p._err_count} of {len(PACKETS)} packets counted as this process's errors")
else:
    ok("a packet whose text says 'error' or 'failed' is not counted")

p._count_log_lines("\n".join(REAL))
if p._err_count != len(REAL):
    fail("real errors still counted",
         f"counted {p._err_count} of {len(REAL)}, including the untagged one")
else:
    ok(f"all {len(REAL)} real log lines are counted, tagged or not")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
