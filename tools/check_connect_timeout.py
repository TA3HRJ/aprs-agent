#!/usr/bin/env python3
"""Fail if a connect to an APRS-IS server that does not answer can hang.

Twice (2026-10-27 20:18, 2026-10-31 07:02) the updater rolled a good release
back with "packets 0 -> 0 in 60 s": the new process logged its login line
and then nothing, still inside asyncio.open_connection(), which had no
deadline. rotate.aprs2.net answers with eleven addresses and asyncio tries
them one after another, so one dead first address costs the kernel's whole
TCP connect timeout before the next is tried (F-2026-10-31-06). What must
hold (no network):

  1. a connect that never completes is given up within CONNECT_TIMEOUT_S,
     the start loop says so - naming the server, in the journal too - and
     tries again
  2. the next address is started CONNECT_STAGGER_S after the previous one
     rather than after it fails (happy_eyeballs_delay)

Usage:  python tools/check_connect_timeout.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aprs_connection as ac  # noqa: E402


class Stop(BaseException):
    """Ends start_server's endless loop from inside the second connect."""


def main() -> int:
    p = []
    calls = []

    async def fake_open(host, port, **kw):
        calls.append(kw)
        if len(calls) == 1:
            await asyncio.Event().wait()     # a server that never answers
        raise Stop

    async def no_sleep(*a, **k):
        return None

    real_open, real_sleep = asyncio.open_connection, asyncio.sleep
    had = getattr(ac, "CONNECT_TIMEOUT_S", None)
    if had is not None:
        ac.CONNECT_TIMEOUT_S = 0.3
    out, journal = io.StringIO(), io.StringIO()
    real_journal = sys.__stderr__
    cfg = {"server": "rotate.example", "port": 14580, "callsign": "N0CALL-5",
           "allowed_callsigns": ["N0CALL"]}

    async def run():
        try:
            await asyncio.wait_for(ac.start_server(cfg, None), timeout=3)
            return "returned"
        except Stop:
            return "retried"
        except asyncio.TimeoutError:
            return "hung"

    asyncio.open_connection, asyncio.sleep = fake_open, no_sleep
    sys.__stderr__ = journal
    try:
        with redirect_stderr(out):
            got = asyncio.run(run())
    finally:
        asyncio.open_connection, asyncio.sleep = real_open, real_sleep
        sys.__stderr__ = real_journal
        if had is not None:
            ac.CONNECT_TIMEOUT_S = had

    said = [ln for ln in out.getvalue().splitlines() if "rotate.example" in ln
            and "answer" in ln]
    print(f"  1 a server that never answers -> {got}, {len(calls)} connect(s), "
          f"said {said[:1]}")
    if got != "retried":
        p.append(f"1: the first connect {got} instead of giving up and retrying")
    if not said:
        p.append("1: no line saying the server did not answer")
    if not any("rotate.example" in ln and "answer" in ln
               for ln in journal.getvalue().splitlines()):
        p.append("1: the line does not reach the journal (sys.__stderr__)")

    # 2
    delay = calls[0].get("happy_eyeballs_delay") if calls else None
    stagger = getattr(ac, "CONNECT_STAGGER_S", None)
    print(f"  2 happy_eyeballs_delay={delay}, CONNECT_STAGGER_S={stagger}, "
          f"CONNECT_TIMEOUT_S={had}")
    if not delay or not stagger or delay != stagger:
        p.append("2: addresses are tried one after another, each waiting out the last")
    elif had is None or stagger >= had:
        p.append("2: the stagger does not leave room for a second address")

    for f in p:
        print("  FAIL  " + f)
    if p:
        print("\n%d failure(s)" % len(p))
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
