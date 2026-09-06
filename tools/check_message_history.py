#!/usr/bin/env python3
"""Fail if the gateway's own conversation can be lost, or if the world feed
can be archived by accident.

Measured on the live feed 2026-09-01: the Messages panel's 400-entry ring
spans **12.0 minutes**, holds **0** messages involving the gateway, and 7 of
400 (1.75%) involving the operator's own prefixes. A restart empties it. So
the ring is not a record and was never going to be one.

What the stored half must get right:

  it must keep what matters
    1. a message to or from the gateway callsign is kept
    2. so is one to or from a trigger alias
    3. so is one matching the operator's station filter, either end
    4. and the round trip through SQLite returns it intact

  it must not keep everything
    5. unrelated world-feed traffic is not stored - 48,000 rows a day and an
       archive of third parties' messages, which is a different object from a
       map of their positions
    6. a station filter of "*" does not turn that decision inside out
    7. the table is bounded by row count as well as by age, so no filter
       however broad can grow it without limit

Usage:  python tools/check_message_history.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import station_db as sdb          # noqa: E402
from web_gui import AgentManager  # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


CFG = {
    "allowed_callsigns": ["TA*", "TB*", "YM*"],
    "extensions": {"ai_gateway": {"callsign": "DMWGPT",
                                  "trigger_aliases": ["APRSGPT"]}},
}


class _Probe(AgentManager):
    def __init__(self, cfg):
        self._cfg = cfg

    def get_config(self):
        return self._cfg


def msg(frm, to):
    return {"from": frm, "to": to, "text": "hello", "ts": int(time.time()),
            "msg_id": "1", "channel": "APRS", "kind": "msg", "dir": "rx"}


p = _Probe(CFG)

# ── 1-3, 5: the scope decision ────────────────────────────────────────
CASES = [
    ("to the gateway",        msg("KO6FFZ", "DMWGPT"),  True),
    ("from the gateway",      msg("DMWGPT", "KO6FFZ"),  True),
    ("to a trigger alias",    msg("KO6FFZ", "APRSGPT"), True),
    ("station filter, sender", msg("TA3HRJ-7", "ANSRVR"), True),
    ("station filter, target", msg("ANSRVR", "YM3KC-8"), True),
    ("unrelated world feed",  msg("YD6ASL-10", "ANSRVR"), False),
    ("unrelated, both ends",  msg("KD3BNW-13", "WA4SKI-7"), False),
]
for label, m, want in CASES:
    got = p._msg_kept(m)
    if got != want:
        fail(label, f"expected kept={want}, got {got}")
    else:
        ok(label + (" -> kept" if want else " -> not stored"))

# ── 6: a bare "*" must not archive the world ──────────────────────────
star = _Probe({"allowed_callsigns": ["*"],
               "extensions": {"ai_gateway": {"callsign": "DMWGPT"}}})
if star._msg_kept(msg("YD6ASL-10", "ANSRVR")):
    fail("bare star filter", "a filter of '*' stored unrelated traffic")
else:
    ok("a station filter of '*' does not archive the world feed")
if not star._msg_kept(msg("KO6FFZ", "DMWGPT")):
    fail("bare star filter", "the gateway's own traffic stopped being kept")
else:
    ok("the gateway is kept regardless of the filter")

# ── 4, 7: the round trip and the row cap ──────────────────────────────
with tempfile.TemporaryDirectory() as d:
    path = str(Path(d) / "t.db")
    kept = [m for _, m, want in CASES if want]
    for i, m in enumerate(kept):
        m["ts"] = int(time.time()) - i          # distinct timestamps
    n = sdb.record_messages(path, kept)
    back = sdb.read_messages(path, 100)
    if n != len(kept):
        fail("round trip", f"stored {n} of {len(kept)}")
    elif len(back) != len(kept):
        fail("round trip", f"read back {len(back)} of {len(kept)}")
    else:
        got = {(m["from"], m["to"], m["text"]) for m in back}
        want = {(m["from"].upper(), m["to"].upper(), m["text"]) for m in kept}
        if got != want:
            fail("round trip", f"content changed: {got ^ want}")
        elif [m["ts"] for m in back] != sorted(m["ts"] for m in back):
            fail("round trip", "rows are not oldest-first")
        else:
            ok("stored messages come back intact and oldest-first")

    # The same message arriving again via another igate must not duplicate.
    again = sdb.record_messages(path, kept)
    if again != 0:
        fail("duplicate suppressed", f"{again} duplicate row(s) stored")
    else:
        ok("the same message gated twice is stored once")

    cap = sdb._MSG_HISTORY_MAX_ROWS
    if not isinstance(cap, int) or cap <= 0 or cap > 200000:
        fail("row cap", f"implausible cap {cap!r}")
    else:
        base = int(time.time())
        flood = [{"from": "TA1X", "to": "TA2Y", "text": "x%d" % i,
                  "ts": base - i, "msg_id": str(i), "channel": "APRS",
                  "kind": "msg", "dir": "rx"} for i in range(cap + 50)]
        sdb.record_messages(path, flood)
        import sqlite3
        con = sqlite3.connect(path)
        total = con.execute("SELECT COUNT(*) FROM message_history").fetchone()[0]
        con.close()
        if total > cap:
            fail("row cap", f"{total} rows stored, cap is {cap}")
        else:
            ok(f"the table is bounded by row count ({total} <= {cap})")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
