#!/usr/bin/env python3
"""Fail if a station injected over the internet under someone else's login
is taken for a radio witness.

2026-10-06 (F-2026-10-06-03): VU3ZAG-13, an internet-connected weather
station near Mumbai, sends beacons for about twenty Kerala and Tamil Nadu
repeaters under their own callsigns -

    VU2CSD>APRS,TCPIP*,qAS,VU3ZAG-13:!0853.45N/07636.08Er...

- none of them on air. `last_gate` took VU3ZAG-13 for their igate, so when
the Pico stopped, five cells lit up as "IGate failure" and one as "possible
outage". 35 of 254 silent stations in the live threshold cells were like
this, and 3 of 12 alerts had no radio witness at all.

What must hold:

  1. a TCPIP* packet carried under another login records its gate as
     "TCPIP/<login>", which survives a restart in the stations table
  2. a station injecting itself (TCPIP*, qAS, its own base call) keeps the
     plain login - it is self-gated, as before
  3. RF-gated and qAC/T2 paths are unchanged
  4. is_backbone_gate() counts "TCPIP/..." as internet, so a cell of such
     stations has no independent gate (gate_independence)
  5. the gateway's "last gated by" answer says internet for such a record

Usage:  python tools/check_injected_gate.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import station_db  # noqa: E402
from station_db import StationDB  # noqa: E402

CASES = (
    ("VU2CSD>APRS,TCPIP*,qAS,VU3ZAG-13:!0853.45N/07636.08Er VU2CSD Repeater",
     "VU2CSD", "TCPIP/VU3ZAG-13"),
    ("TA1ABC-1>APOSB4,TCPIP*,qAS,TA1ABC:!3825.00N/02706.00E-openSPOT",
     "TA1ABC-1", "TA1ABC"),
    ("TA1ABC-7>APAT89,WIDE1-1,qAR,TA1XYZ-10:!3825.00N/02706.00E>",
     "TA1ABC-7", "TA1XYZ-10"),
    ("TA1ABC-9>APDR16,TCPIP*,qAC,T2TEST:!3825.00N/02706.00E>",
     "TA1ABC-9", "T2TEST"),
)


def main() -> int:
    fails = []
    db = StationDB()
    for line, call, want in CASES:
        db.ingest(line)
        r = db._stations.get(call)
        got = r.last_gate if r else None
        if got != want:
            fails.append("%s: last_gate %r, expected %r" % (call, got, want))
    if not station_db.is_backbone_gate("TCPIP/VU3ZAG-13"):
        fails.append("is_backbone_gate does not count TCPIP/<login> as internet")
    if station_db.is_backbone_gate("TA1XYZ-10"):
        fails.append("an ordinary igate is counted as internet")
    g = {"VU2CSD": "TCPIP/VU3ZAG-13", "VU2GCC": "TCPIP/VU3ZAG-13",
         "VU2IP": "TCPIP/VU3ZAG-13", "VU2TTD": "TCPIP/VU3ZAG-13"}
    got = station_db.gate_independence(g, list(g))
    if got != (0, 0, 4):
        fails.append("four injected stations gave gate_independence %r, "
                     "expected (0, 0, 4)" % (got,))

    src = (ROOT / "extensions" / "ai_gateway_ext.py").read_text(encoding="utf-8")
    i = src.find('gate = (rec or {}).get("last_gate") or ""')
    tail = src[i:i + 900]
    if i < 0 or "is_backbone_gate" not in tail or "internet" not in tail:
        fails.append("the 'last gated by' answer does not say internet for "
                     "an injected record")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    internet-injected stations are internet-gated, not radio witnesses")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
