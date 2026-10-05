#!/usr/bin/env python3
"""Fail if a check drives its coroutine in a way that strands pending tasks.

Since v3.2.138 every answer part starts a resend task that sleeps 40 s or
more. Five checks ran their coroutine with
`asyncio.get_event_loop().run_until_complete(run())`, which returns with
those tasks still pending; at exit each one was collected outside a loop and
printed "Exception ignored in: <coroutine object AIGateway._resend> ...
RuntimeError: no running event loop" - 45 times in check_weather alone. The
checks still passed, and a real traceback would have been buried in the
noise. `asyncio.run()` cancels what is left and lets it finish inside the
loop.

What must hold: no tools/check_*.py calls
`get_event_loop().run_until_complete(`. A check that builds its own loop on
purpose (new_event_loop, to test threads) is not affected.

Usage:  python tools/check_event_loops.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent


def main() -> int:
    bad = [p.name for p in sorted(TOOLS.glob("check_*.py"))
           if p.name != Path(__file__).name
           and "get_event_loop().run_until_complete(" in p.read_text(encoding="utf-8")]
    for b in bad:
        print("  FAIL  %s strands pending tasks: use asyncio.run()" % b)
    if bad:
        print("\n%d failure(s)" % len(bad))
        return 1
    print("  ok    every check runs its coroutine with asyncio.run()")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
