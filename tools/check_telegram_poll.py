#!/usr/bin/env python3
"""Fail if an idle Telegram poll can raise the operator's error counter.

Measured on the live VPS 2026-09-24: 62 `[telegram] poll error` lines in 24
hours, 59 of them timeouts, and not one missed message among them. Every one
reached the error counter, because `_count_log_lines` counts any log line
containing "error", and `TimeoutError` is spelt with it.

The cause is a margin. getUpdates is a long poll: Telegram is asked to hold
the request open for 10 s when there is nothing to deliver, and the HTTP
client was given 15 s to receive the answer. Five seconds covers the round
trip only on a good day, so an idle bot timed out several times an hour. The
three that were not timeouts were a reset and two slow handshakes — real
network, but a single one heals on the next poll.

What must hold:

  structure
    1. the HTTP timeout on getUpdates exceeds the long-poll wait by at
       least 15 s, so an idle poll ends with Telegram's empty answer rather
       than with the client giving up

  behaviour, lines fed through web_gui's own error classifier
    2. isolated failures, each followed by a good poll, count as 0 errors
    3. a sustained outage counts as exactly 1 error, however long it lasts
    4. the recovery after that outage is logged, and counts as 0

Usage:  python tools/check_telegram_poll.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extensions  # noqa: E402
import extensions.telegram_ext as tg  # noqa: E402
import web_gui  # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


def counted(lines: list[str]) -> int:
    """How many of these lines the operator's error counter would count."""
    return sum(1 for ln in lines
               if web_gui._AIERR_RE.search(ln) or web_gui._ERR_RE.search(ln))


LINES: list[str] = []
extensions.Extension._emit = staticmethod(LINES.append)

CFG = {"bot_token": "123456:ABCDEFGHIJKLMNOP", "chat_id": "1",
       "poll_enabled": True, "from_callsign": "N0CALL",
       "poll_interval_secs": 0}


# ── 1: the HTTP timeout outlasts the long poll ────────────────────────
seen: dict = {}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake_urlopen(req, timeout=None):
    seen["timeout"] = timeout
    seen["body"] = json.loads(req.data.decode()) if req.data else {}
    return _Resp(b'{"ok": true, "result": []}')


real_urlopen = tg.urllib.request.urlopen
tg.urllib.request.urlopen = _fake_urlopen
try:
    ext = tg.Telegram(dict(CFG))
    asyncio.run(ext._check_updates())
finally:
    tg.urllib.request.urlopen = real_urlopen

wait = seen.get("body", {}).get("timeout")
http = seen.get("timeout")
if wait is None or http is None:
    fail("1 margin", f"could not observe the call (wait={wait}, http={http})")
elif http - wait < 15:
    fail("1 margin", f"long poll {wait} s, HTTP timeout {http} s — "
                     f"{http - wait} s is not a margin")
else:
    ok(f"1 margin: long poll {wait} s, HTTP timeout {http} s")


# ── 2-4: the loop, driven by a scripted sequence ──────────────────────
class _Stop(BaseException):  # past the loop's own "except Exception"
    pass


async def _no_wait(_s):
    return None


def run(script: list) -> list[str]:
    """Run _poll_loop over `script` (True = a good poll, or an exception to
    raise) and return what it logged after startup."""
    ext = tg.Telegram(dict(CFG))
    steps = iter(script)

    async def fake_check():
        step = next(steps, _Stop())
        if step is True:
            return None
        raise step

    ext._check_updates = fake_check

    shim = types.SimpleNamespace(**{k: getattr(asyncio, k)
                                    for k in dir(asyncio)
                                    if not k.startswith("__")})
    shim.sleep = _no_wait
    real_asyncio = tg.asyncio
    tg.asyncio = shim
    del LINES[:]
    try:
        async def go():
            try:
                await ext._poll_loop()
            except _Stop:
                pass
        # deleteWebhook goes through the real _tg_api; keep it offline
        real_api = tg._tg_api
        tg._tg_api = lambda *a, **k: {"ok": True}
        try:
            asyncio.run(go())
        finally:
            tg._tg_api = real_api
    finally:
        tg.asyncio = real_asyncio
    return [ln for ln in LINES
            if "webhook" not in ln and "polling Telegram" not in ln]


T = TimeoutError("The read operation timed out")
R = ConnectionResetError(104, "Connection reset by peer")

lines = run([T, True, T, True, R, True, T, True])
n = counted(lines)
if n:
    fail("2 isolated", f"{n} counted from four one-off failures: {lines}")
else:
    ok(f"2 isolated: four one-off failures, 0 counted ({len(lines)} lines)")

lines = run([True] + [T] * 12 + [True])
n = counted(lines)
if n != 1:
    fail("3 outage", f"{n} counted from one twelve-poll outage: {lines}")
else:
    ok("3 outage: twelve failed polls in a row, 1 counted")

recovered = [ln for ln in lines if "recovered" in ln]
if not recovered:
    fail("4 recovery", f"no recovery line: {lines}")
elif counted(recovered):
    fail("4 recovery", f"the recovery line is counted as an error: {recovered}")
else:
    ok("4 recovery logged, not counted")


print()
print("FAIL" if FAIL else "PASS", f"— {FAIL} problem(s)")
sys.exit(1 if FAIL else 0)
