#!/usr/bin/env python3
"""Fail if a background loop can die and stay dead, or die unnoticed.

AUDIT-2026-10-08 F1/F2. _supervise() reported a dead loop and left it dead,
and it wrapped three loops of the six that matter. On 2026-10-07 one of the
others - broadcast_logs, which feeds every packet to the registry - died
seconds after each start, and the agent stayed connected and counted nothing
for twelve hours (F-2026-10-07-04). Its own deafness was in its log only.

What must hold:

  1. AgentManager._keep_alive() restarts a loop that raises, logs each death
     and each restart, and records the deaths
  2. the log, persist, silence, health, monitor and station-AI loops are
     started through keep_running()
  3. the fixed beacon's loop body is guarded, and the gateway's status loop
     guards its settings read; neither task is left unreferenced
  4. _health_notes(): deaf past _HEALTH_DEAF_S is told once, and its end;
     a loop dying _HEALTH_DEATHS times in the window is told once an hour
  5. the watchdog thread starts only under systemd (INVOCATION_ID)
  6. a notification that was sent says so in the journal (F7)

Usage:  python tools/check_loops_survive.py
Exit code 1 on failure.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_gui  # noqa: E402

AM = web_gui.AgentManager


def loop_body(path: str, func: str):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func:
            for sub in ast.walk(node):
                if isinstance(sub, ast.While):
                    return sub.body
    return None


def main() -> int:
    fails = []
    for name in ("_keep_alive", "keep_running", "_health_notes", "start_watchdog"):
        if not hasattr(AM, name):
            fails.append("no AgentManager.%s" % name)
    if fails:
        for f in fails:
            print("  FAIL  " + f)
        print("\n%d failure(s)" % len(fails))
        return 1

    # 1 · restarted
    logs = []
    m = types.SimpleNamespace(
        _log_both=logs.append, _loop_deaths={},
        _RESTART_DELAY_S=0.01, _RESTART_CAP_S=0.05, _RESTART_RESET_S=600.0)
    calls = [0]

    async def flaky():
        calls[0] += 1
        if calls[0] <= 2:
            raise RuntimeError("boom %d" % calls[0])
        await asyncio.sleep(10)

    async def run():
        t = asyncio.ensure_future(AM._keep_alive(m, "test", flaky))
        for _ in range(100):
            await asyncio.sleep(0.02)
            if calls[0] >= 3:
                break
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
    if calls[0] < 3:
        fails.append("a loop that raised twice was started %d times, not 3"
                     % calls[0])
    if sum("LOOP DIED" in l for l in logs) != 2 or \
            sum("loop restarted" in l for l in logs) < 2:
        fails.append("deaths and restarts not both logged: %r" % logs[:4])
    if len(m._loop_deaths.get("test", [])) != 2:
        fails.append("deaths not recorded: %r" % m._loop_deaths)

    # 2 · who is kept running
    src = inspect.getsource(web_gui)
    for name in ("log", "persist", "silence", "health", "monitor", "station-ai"):
        if 'keep_running("%s"' % name not in src:
            fails.append("the %s loop is not started through keep_running" % name)

    # 3 · extension loops
    body = loop_body("extensions/fixed_beacon.py", "_beacon_loop")
    if not body or not isinstance(body[0], ast.Try):
        fails.append("the fixed beacon's sends are not guarded")
    body = loop_body("extensions/ai_gateway_ext.py", "_status_loop")
    if not body or not isinstance(body[0], ast.Try):
        fails.append("the status loop's settings read is not guarded")
    for path, attr in (("extensions/fixed_beacon.py", "self._beacon_task = "),
                       ("extensions/ai_gateway_ext.py", "self._status_task = "),
                       ("extension_server.py", "store.serve_task = ")):
        if attr not in (ROOT / path).read_text(encoding="utf-8"):
            fails.append("%s drops its task reference" % path)

    # 4 · health notices
    now = 1_800_000_000.0
    deaf = [now - 1000]
    h = types.SimpleNamespace(
        running=True, _health_sent={}, _loop_deaths={},
        _station_db=types.SimpleNamespace(deaf_since=lambda: deaf[0]),
        _HEALTH_DEAF_S=900.0, _HEALTH_DEATHS=3, _HEALTH_DEATHS_WINDOW_S=1800.0)
    n1 = AM._health_notes(h, now)
    n2 = AM._health_notes(h, now + 60)
    deaf[0] = 0.0
    n3 = AM._health_notes(h, now + 120)
    if len(n1) != 1 or "no packet heard" not in n1[0] or n2:
        fails.append("deafness not told exactly once: %r, then %r" % (n1, n2))
    if len(n3) != 1 or "again" not in n3[0]:
        fails.append("the end of deafness not told: %r" % n3)
    h._loop_deaths = {"log": [now - 100, now - 50, now - 10]}
    n4 = AM._health_notes(h, now)
    n5 = AM._health_notes(h, now + 600)
    if len(n4) != 1 or "log loop died 3 times" not in n4[0] or n5:
        fails.append("repeated deaths not told once an hour: %r, then %r"
                     % (n4, n5))

    # 6 · a notification that went out leaves a line (F7)
    ns = inspect.getsource(AM._send_notification)
    if "[notify] telegram: sent" not in ns or "[notify] smtp: sent" not in ns:
        fails.append("a successful notification leaves no trace")

    # 5 · watchdog only under systemd
    saved = os.environ.pop("INVOCATION_ID", None)
    try:
        if AM.start_watchdog(types.SimpleNamespace()):
            fails.append("the watchdog started outside systemd")
    finally:
        if saved is not None:
            os.environ["INVOCATION_ID"] = saved

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    loops come back, the operator hears of deafness and repeated "
          "deaths, the watchdog waits for systemd")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
