#!/usr/bin/env python3
"""Fail if the APRS-IS login callsign can collide in silence.

Measured on 2026-09-09. The operator's own SharkRF openSPOT4 was injecting
into APRS-IS as `TA3HRJ-1>APOSB4,TCPIP*,qAS,TA3HRJ` while this agent was
logged in as `TA3HRJ`. APRS-IS does not deliver a packet to a connection whose
login matches the callsign in the packet's q-construct, so the hotspot was
**invisible to its own operator's agent**:

    login TA3HRJ    5 h 15 min of feed, `TA3HRJ-1>` packets:  0
    login TA3HRJ-9  first beacon arrived 51 seconds later:    1

Every other SSID of the same base callsign — `TA3HRJ-12` via `qAC,T2CHILE`,
`TA3HRJ-8` via `qAR,TA3TX-4` — arrived normally throughout. The q-construct
was the only thing that differed, and there was no error anywhere.

What must hold:

  1. the login callsign is stated at startup, so the value can be read from
     the journal rather than inferred from a config file nobody opens
  2. a bare base callsign warns — it is the value a hotspot, an igate or a
     phone app picks by default, so it is the one that collides
  3. an SSID'd login does not warn
  4. the warning names the callsign, so the reader knows what to change
  5. the passcode is unchanged by the SSID, because that is what makes the
     advice free to follow

Usage:  python tools/check_login_collision.py
Exit code 1 on failure.
"""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aprs_connection import _warn_login_collision   # noqa: E402
from config import calculate_passcode               # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


def emitted(callsign: str) -> str:
    """What reaches the Live Log (sys.stderr).

    The journal stream is swallowed too, so this check's own output stays
    clean — the function writes to both by design.
    """
    import sys as _s
    real, sink, buf = _s.__stderr__, io.StringIO(), io.StringIO()
    try:
        _s.__stderr__ = sink
        with redirect_stderr(buf):
            _warn_login_collision(callsign)
    finally:
        _s.__stderr__ = real
    return buf.getvalue()


def emitted_journal(callsign: str) -> str:
    """What reaches journald (sys.__stderr__).

    While the agent runs, `sys.stderr` is the browser's Live Log — swapped in
    `_run_agent` before the APRS-IS connection is opened. v3.2.108 wrote only
    there, so the login line the operator was meant to read months later in
    `journalctl` never reached the journal at all. Both streams are asserted
    here because only one of them is the point.
    """
    import sys as _s
    real, buf = _s.__stderr__, io.StringIO()
    fake = io.StringIO()
    try:
        _s.__stderr__ = buf
        with redirect_stderr(fake):
            _warn_login_collision(callsign)
    finally:
        _s.__stderr__ = real
    return buf.getvalue()


# ── 1: the login is always stated ─────────────────────────────────────
for cs in ("TA3HRJ", "TA3HRJ-5"):
    out = emitted(cs)
    if cs not in out or "login callsign" not in out:
        fail("login stated", f"{cs} produced {out!r}")
        break
else:
    ok("the login callsign is stated at startup, with and without an SSID")

# ── 1b: and it reaches the journal, not only the Live Log ─────────────
j_plain = emitted_journal("TA3HRJ-5")
j_bare = emitted_journal("TA3HRJ")
if "login callsign" not in j_plain:
    fail("login reaches journald",
         "the login line went only to the Live Log — which is what v3.2.108 "
         "shipped, and it made the line unreadable from journalctl")
elif "WARNING" not in j_bare:
    fail("warning reaches journald", f"journald got {j_bare!r}")
else:
    ok("both the login line and the warning reach journald")


# ── 2: a bare callsign warns ──────────────────────────────────────────
bare = emitted("TA3HRJ")
if "WARNING" not in bare:
    fail("bare callsign warns",
         "a login with no SSID passed without a word — this is the 2026-09-09 "
         "fault, in which a hotspot was invisible for five hours")
elif "TA3HRJ" not in bare:
    fail("warning names it", f"the warning does not name the callsign: {bare!r}")
else:
    ok("a bare base callsign warns, and the warning names it")

# ── 3: an SSID'd login is quiet ───────────────────────────────────────
for cs in ("TA3HRJ-5", "TA3HRJ-9", "KM7AZO-1"):
    if "WARNING" in emitted(cs):
        fail("SSID is quiet", f"{cs} warned; only a bare callsign should")
        break
else:
    ok("an SSID'd login passes without a warning")

# ── 5: the advice is free — the passcode does not change ──────────────
base = calculate_passcode("TA3HRJ")
for cs in ("TA3HRJ-5", "TA3HRJ-9", "TA3HRJ-15"):
    if calculate_passcode(cs) != base:
        fail("passcode unchanged",
             f"{cs} needs a different passcode than the base callsign — the "
             f"advice to add an SSID would not be free")
        break
else:
    ok("the passcode is identical with and without an SSID")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
