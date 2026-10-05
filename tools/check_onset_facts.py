#!/usr/bin/env python3
"""Fail if a silence alert's timing is turned into a verdict instead of facts.

2026-10-05 (F-2026-10-05-03 and its correction): the last packets of every
live alert's silent stations spread over 1.9-19 h, and the AI note read that
as "these stations did NOT go down together, which argues against one power
or infrastructure event". It does not argue that. After a mains failure the
unprotected stations stop at once and those on UPS, battery or solar stop
later - minutes to hours - so one outage staggers too. A spread gate was
proposed and withdrawn on the same ground. What is left is to state what
was measured and let the reader weigh it.

What must hold:

  1. StationDB.onset_facts() measures from each station's LAST PACKET, not
     last packet + its own threshold (which made stations of different
     cadence look staggered when they stopped together): the spread, and
     the opening - how many fell silent within one beacon interval (at
     least 15 min) of the first
  2. /api/silence carries those facts on alerting cells, with the stations
     that have come back while the alert ran
  3. the AI context states the spread, the opening and the returns, names
     UPS / battery / solar backup as a reason one outage staggers, and no
     longer says a wide spread argues against one outage
  4. the map popup shows the three facts

Usage:  python tools/check_onset_facts.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from station_db import StationDB, StationRecord  # noqa: E402

NOW = time.time()


def put(db, call, ago_s, interval_s):
    r = StationRecord(call)
    r.last_seen = NOW - ago_s
    r.ema_interval_s = interval_s
    db._stations[call] = r


def main() -> int:
    fails = []
    db = StationDB()
    if not hasattr(db, "onset_facts"):
        fails.append("StationDB has no onset_facts()")
    else:
        # mains cut at -6 h: two unprotected stations stop together (one beacons
        # every 10 min, one every 30), a UPS one 40 min later, a solar one 5 h later
        put(db, "AA1AA", 6 * 3600, 600)
        put(db, "AA1AB", 6 * 3600 + 1200, 1800)
        put(db, "AA1AC", 6 * 3600 - 2400, 600)
        put(db, "AA1AD", 1 * 3600, 600)
        f = db.onset_facts(["AA1AA", "AA1AB", "AA1AC", "AA1AD"])
        if f.get("n") != 4:
            fails.append("n %r, expected 4" % f.get("n"))
        if abs(f.get("spread_s", 0) - (5 * 3600 + 1200)) > 2:
            fails.append("spread %r s, expected the last-packet spread %d s"
                         % (f.get("spread_s"), 5 * 3600 + 1200))
        if f.get("opening") != 2:
            fails.append("opening %r, expected 2 (the two that stopped within "
                         "the longest interval, 30 min, of the first)" % f.get("opening"))
        g = db.onset_facts(["AA1AA"])
        if g.get("n") != 1 or g.get("spread_s") != 0:
            fails.append("a single station: %r" % g)

    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    if 'c["onset"]' not in web or "_silence_seen" not in web:
        fails.append("/api/silence does not carry onset facts with the returns")
    i = web.find("def _onset_context")
    ctx = web[i:web.find("\n    def ", i + 10)] if i >= 0 else ""
    if "did NOT go down together" in ctx or "argues against one power" in ctx:
        fails.append("the AI context still reads a wide spread as independence")
    for w in ("UPS", "battery", "solar", "onset_facts", "came back"):
        if w not in ctx:
            fails.append("the AI context does not mention %r" % w)
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    j = page.find("function silPopup")
    pop = page[j:page.find("\nfunction ", j + 10)] if j >= 0 else ""
    if "c.onset" not in pop or "sil_onset" not in pop:
        fails.append("the map popup does not show the onset facts")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    spread, opening and returns stated as facts; backup power named")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
