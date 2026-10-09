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
  5. the opening window is the FIRST station's own interval (at least
     15 min), not the longest in the cell: one station beaconing every
     4-6 h stretched the window to hours in DM15, FJ09 and JN27
  6. the evidence bundle ("Copy as AI prompt") carries the same facts and
     says what a station's `since` is. 2026-10-05: ChatGPT and Gemini, given
     v3.2.147 bundles for KM59 and LM09, both read an 8.9 h spread as
     evidence against one outage, and read `since` (last packet + 3x the
     interval) as the moment each station went quiet
  7. each silent station in the bundle says whether its gate fell silent
     before it. Gemini blamed KM59 on YM2KF-10 failing as TA2OK's gate;
     TA2OK had stopped about 7 h before YM2KF-10 did

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
        # the first to stop beacons every 10 min; another every 5 h. The window
        # is the first one's, 15 min, so the 5 h station 40 min later is out
        put(db, "BB1AA", 8 * 3600, 600)
        put(db, "BB1AB", 8 * 3600 - 2400, 5 * 3600)
        put(db, "BB1AC", 2 * 3600, 600)
        h = db.onset_facts(["BB1AA", "BB1AB", "BB1AC"])
        if h.get("opening") != 1 or h.get("window_s") != 900:
            fails.append("opening window taken from the longest interval, not "
                         "the first station's: %r" % h)
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
    for w in ("backup power", "onset_facts", "came back", "unknown"):
        if w not in ctx:
            fails.append("the AI context does not mention %r" % w)
    # 2026-10-06 (F-2026-10-06-04): naming UPS, battery and solar one by one
    # tipped the note from 98 % "unknown" to 73 % "power_outage". The
    # mechanism is stated once, generally, beside the drop-out one.
    for w in ("UPS", "battery", "solar"):
        if w in ctx.split('"""', 2)[-1]:
            fails.append("the AI context still lists %r - one generic phrase, "
                         "beside the drop-out reading" % w)
    if "drop-out" not in ctx:
        fails.append("the AI context does not give the drop-out reading beside the outage one")
    k = web.find("async def get_silence_evidence")
    ev = web[k:web.find("\n@routes", k + 10)] if k >= 0 else ""
    if 'c["onset"]' not in ev:
        fails.append("the evidence bundle does not carry the onset facts")
    if "backup power" not in ev or "UPS" in ev or "since_means" not in ev:
        fails.append("the evidence bundle does not name backup power (generically) "
                     "or say what `since` is")
    if "gate_stopped_first" not in ev:
        fails.append("bundle stations do not say whether their gate fell silent first")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    j = page.find("function silPopup")
    pop = page[j:page.find("\nfunction ", j + 10)] if j >= 0 else ""
    if "c.onset" not in pop or "sil_onset" not in pop:
        fails.append("the map popup does not show the onset facts")
    import re as _re
    for lang_key in _re.findall(r'sil_backup:"([^"]*)"', page):
        if "UPS" in lang_key or "solar" in lang_key.lower() or "güneş" in lang_key:
            fails.append("the popup's backup note still lists devices: %r" % lang_key[:60])

    # F-2026-10-06-04, probed 2026-10-08: the three constructed alerts. A
    # tight onset, and one with backup-power stragglers, are stated as
    # agreeing; a spread with one early drop keeps the unknown rule.
    import types
    import web_gui as _wg
    def onset(drops, back=()):
        d = StationDB()
        calls = []
        for i, ago in enumerate(drops):
            c = "CC1A%02d" % i
            put(d, c, ago, 600)
            calls.append(c)
        m = types.SimpleNamespace(_station_db=d,
                                  _silence_seen={"KM38": set(calls) | set(back)})
        return _wg.AgentManager._onset_context(m, {"cell": "KM38",
                                                    "silent_calls": calls})
    A = onset([2400 + 20 * i for i in range(8)])
    B = onset([14400 + 40 * i for i in range(6)] + [3600, 3300])
    C = onset([36000, 28000, 22000, 17000, 12000, 8000, 5000, 2400])
    Bb = onset([14400 + 40 * i for i in range(6)] + [3600, 3300], back=("CC1Z00",))
    if "unknown" in A:
        fails.append("a 2-minute onset carries the unknown rule")
    if "point the same way: 6 of 8" not in B or '"unknown"' in B:
        fails.append("6 of 8 together and 2 trailing, none back, is not stated as "
                     "agreeing: %r" % B[-160:])
    if '"unknown"' not in C or "point the same way:" in C:
        fails.append("a 9 h spread with one early drop lost the unknown rule")
    if '"unknown"' not in Bb:
        fails.append("with a station back, the same onset is still called agreeing")

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
