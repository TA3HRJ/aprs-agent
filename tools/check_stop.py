#!/usr/bin/env python3
"""Fail if a stop can be reported as successful without having happened, or if
a second agent can be started over a live one.

Measured live on 2026-09-06. The operator reported that the Stop button did
nothing. It was not the button, not the browser and not the proxy: the Apache
log showed four `POST /api/stop` requests answered **200**, and three minutes
after the last one `/api/status` still said `running: true` with the packet
counter climbing.

The chain behind it:

  * `_run_agent` builds a NEW `_agent_loop` and a NEW `_stop_event` on every
    call, and sets `running = True` only after loading the config.
  * `start()` guarded on `running` alone, so a second start was admitted in
    that window and replaced both objects.
  * `_agent_main` had already evaluated `self._stop_event` and was parked on
    the previous Event, which nothing would ever set again.
  * `stop()` returned True for having *scheduled* a callback, so the answer
    was 200 and the interface believed it.

What must hold:

  the report must be honest
    1. stop() on a stopped agent is False, not a cheerful no-op
    2. stop() is False when there is no loop or no stop event to signal
    3. stop() is False when the loop refuses work (closed loop)
    4. and the failure is said out loud, not swallowed

  a second agent must not be startable over a live one
    5. not while `running` is True
    6. **and not while the thread is alive but `running` is not yet True** —
       the window the live fault came through
    7. a genuinely idle manager can still start

Usage:  python tools/check_stop.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web_gui import AgentManager  # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


class _Probe(AgentManager):
    def __init__(self):
        self.running = False
        self._thread = None
        self._agent_loop = None
        self._stop_event = None
        self.said = []

    def _log_both(self, msg: str) -> None:
        self.said.append(msg)


# ── 1: a stopped agent ────────────────────────────────────────────────
p = _Probe()
if p.stop() is not False:
    fail("stop when stopped", "reported success with nothing running")
else:
    ok("stop on a stopped agent reports False")

# ── 2: running, but nothing to signal ─────────────────────────────────
p = _Probe()
p.running = True
if p.stop() is not False:
    fail("no stop event", "reported success with no loop or event")
elif not p.said:
    fail("no stop event", "failed silently — the operator sees a dead button")
else:
    ok("stop with nothing to signal reports False, and says so")

# ── 3: a loop that will not accept work ───────────────────────────────
p = _Probe()
p.running = True
dead = asyncio.new_event_loop()
dead.close()
p._agent_loop = dead
p._stop_event = asyncio.Event()
if p.stop() is not False:
    fail("closed loop", "reported success against a closed loop")
elif not any("loop" in m for m in p.said):
    fail("closed loop", f"said nothing useful: {p.said!r}")
else:
    ok("stop against a closed loop reports False, and names it")

# ── 4: the happy path still works ─────────────────────────────────────
p = _Probe()
p.running = True
loop = asyncio.new_event_loop()
ev = asyncio.Event()
p._agent_loop, p._stop_event = loop, ev
done = threading.Event()


async def _park():
    await ev.wait()
    done.set()


def _spin():
    loop.run_until_complete(_park())


th = threading.Thread(target=_spin, daemon=True)
th.start()
time.sleep(0.2)
res = p.stop()
if res is not True:
    fail("happy path", f"a working stop reported {res!r}")
elif not done.wait(3):
    fail("happy path", "the stop event never woke the waiter")
else:
    ok("a working stop signals the event and reports True")
th.join(timeout=2)
loop.close()

# ── 5-7: the second-agent guard ───────────────────────────────────────
p = _Probe()
p.running = True
if p.start() is not False:
    fail("start while running", "a second agent was admitted")
else:
    ok("start is refused while running")

# The window the live fault came through: thread alive, running still False.
p = _Probe()
alive = threading.Event()
p._thread = threading.Thread(target=lambda: alive.wait(5), daemon=True)
p._thread.start()
time.sleep(0.1)
if p.running:
    fail("window setup", "running should still be False for this case")
elif p.start() is not False:
    fail("start in the startup window",
         "a second agent was admitted while the first thread was alive — "
         "this is the live fault of 2026-09-06")
else:
    ok("start is refused while a previous thread is alive but not yet running")
alive.set()

p = _Probe()
p._thread = None
started = []
p._run_agent = lambda: started.append(1) or time.sleep(0.3)
if p.start() is not True:
    fail("idle start", "an idle manager refused to start")
else:
    time.sleep(0.2)
    ok("an idle manager still starts")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
