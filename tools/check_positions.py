#!/usr/bin/env python3
"""Fail if a placeholder or a misread latitude becomes a place on the map.

2026-10-10 (F-2026-10-10-03): 63 stations stood north of 84 N, none of them
there. Some send "no position" in a position field - 9000.00N/18000.00E, and
1,787 records sat at 0/0. The others are real stations whose malformed
latitude our unanchored pattern read from the middle: KC8HFO-D's 38806.60N
became 88 06.60 N. One day of feed: 3,298 position packets (0.07 %) from 54
sources were matched inside a longer digit run - but not all wrongly: an
object timestamp missing its z (F4ETJ-1, NEVAMO) or one leading zero
(K2ILH-2) still give the right place.

What must hold:

  1. a match inside a digit run is a position only after a valid 6-digit
     timestamp missing its letter, or after one leading 0; otherwise the
     packet has no position and is marked unreadable
  2. 0/0 (within half a degree), the 90/180 placeholder and anything north
     of what Mercator draws (85.0511 N) are no position; the South Pole is
     one (NZSP sends -90/0 from Amundsen-Scott); 84 N is still drawn
  3. at load, a stored position the new rules reject - a placeholder, or the
     very value the old rule read from the stored packet text - is dropped,
     the station marked unreadable where it was misread, and every dropped
     position kept in meta `positions_voided` so it can be put back
  4. a station marked unreadable loses the mark when a good position comes
  5. the search says "position unreadable" apart from "no position", in both
     languages; the map shows a scale, and stations stacked on one point are
     listed by name

Usage:  python tools/check_positions.py
Exit code 1 on failure.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import packet_parser as pp  # noqa: E402
import station_db as sdb  # noqa: E402

LINES = {
    # call: (info, expected lat or None, unreadable)
    "KC8HFO-D": ("!38806.60ND08113.80W&/A=000000 MMDVM Voice", None, True),
    "I4IFL-D": ("!4420668800.00ND01202.18E&/A=000000 MMDVM", None, True),
    "EA5HJU-D": ("!373618.60ND05829.40W&/A=000000 MMDVM", None, True),
    "F4ETJ-1": (";F5KLJ    *0915514526.39N\\00023.46W-Bienvenue", 45 + 26.39 / 60, False),
    "K2ILH-2": (";IRLP-4591*111111z04257.33NI07848.97W0-444.000MHz", 42 + 57.33 / 60, False),
    "NEVAMO": (";443.975-X*1111113751.65N/09422.93WrT001 R55m", 37 + 51.65 / 60, False),
    "KK7MFU-10": ("!9000.00NR18000.00E&zz iGate", None, False),
    "QFD136960": (";QFD136960*090340z9000.00S/18000.00EfRTC - Going", None, False),
    "NZSP": ("@181750z9000.00S/00000.00E_080/009g...t...h..b09526", -90.0, False),
    "KC5SQD-8": ("/000000z0000.00N/00000.00E>Old Man", None, False),
    "VA3OTL-B": ("!8418.84ND04631.43W&RNG0030 440 Voice", 84 + 18.84 / 60, False),
    "XX0NOR": ("!8606.00N/01000.00E-north of Mercator", None, False),
    "TA3HX-5": ("!3827.37N/02706.25ExAPRS-Agent iGate", 38 + 27.37 / 60, False),
}


def main() -> int:
    fails = []
    for call, (info, lat, unread) in LINES.items():
        p = pp.parse_packet("%s>APRS,TCPIP*,qAC,T2TEST:%s" % (call, info))
        got = p.get("lat")
        if lat is None and got is not None:
            fails.append("1/2: %s read as %.3f, expected no position" % (call, got))
        elif lat is not None and (got is None or abs(got - lat) > 1e-3):
            fails.append("1/2: %s read as %r, expected %.3f" % (call, got, lat))
        if bool(p.get("position_unreadable")) != unread:
            fails.append("1: %s unreadable=%r, expected %r"
                         % (call, p.get("position_unreadable"), unread))

    # 3: load-time cleanup on a constructed database
    tmp = Path(tempfile.mkdtemp()) / "s.db"
    con = sqlite3.connect(tmp)
    cols = sdb.StationDB._SQL_COLS
    con.execute("CREATE TABLE stations (%s)" % ",".join(cols))
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")

    def row(call, lat, lon, comment):
        d = dict.fromkeys(cols)
        d.update(callsign=call, first_seen=1.0, last_seen=2.0, packet_count=9,
                 lat=lat, lon=lon, locator="XX00", comment=comment)
        con.execute("INSERT INTO stations VALUES (%s)" % ",".join("?" * len(cols)),
                    [d[c] for c in cols])
    row("KC8HFO-D", 88 + 6.60 / 60, -(81 + 13.80 / 60), LINES["KC8HFO-D"][0])
    row("KK7MFU-10", 90.0, 180.0, LINES["KK7MFU-10"][0])
    row("KC5SQD-8", 0.0, 0.0, LINES["KC5SQD-8"][0])
    row("NZSP", -90.0, 0.0, LINES["NZSP"][0])
    row("TA3HX-5", 38.456, 27.104, LINES["TA3HX-5"][0])
    # stored from an earlier good packet; the latest text is malformed: keep
    row("KD5NDU-B", 34.180, -89.324, "!34410.80ND08919.46W&RNG0001")
    con.commit()
    con.close()
    db = sdb.StationDB()
    db.load_sqlite(str(tmp))
    s = db._stations
    for call in ("KC8HFO-D", "KK7MFU-10", "KC5SQD-8"):
        if s[call].lat is not None:
            fails.append("3: %s kept its stored position %r" % (call, s[call].lat))
    for call in ("NZSP", "TA3HX-5", "KD5NDU-B"):
        if s[call].lat is None:
            fails.append("3: %s lost a position the rules accept" % call)
    if not getattr(s["KC8HFO-D"], "position_unreadable", False):
        fails.append("3: KC8HFO-D is not marked unreadable after its misread was dropped")
    con = sqlite3.connect(tmp)
    got = con.execute("SELECT value FROM meta WHERE key='positions_voided'").fetchone()
    con.close()
    voided = json.loads(got[0]) if got else {}
    if set(voided) != {"KC8HFO-D", "KK7MFU-10", "KC5SQD-8"}:
        fails.append("3: positions_voided holds %r" % sorted(voided))
    elif abs(voided["KC8HFO-D"][0] - 88.11) > 0.01:
        fails.append("3: the voided KC8HFO-D row does not keep its old latitude")

    # 4: a good position clears the mark
    r = s["KC8HFO-D"]
    r.update_from_parsed(pp.parse_packet(
        "KC8HFO-D>APRS,TCPIP*,qAC,T2TEST:!3806.60ND08113.80W&MMDVM"))
    if r.lat is None or abs(r.lat - 38.11) > 0.01 or getattr(r, "position_unreadable", True):
        fails.append("4: a good packet did not restore the position and clear the mark "
                     "(lat %r, unreadable %r)" % (r.lat, getattr(r, "position_unreadable", None)))

    # 5: search and map
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if page.count("ms_unreadable:") != 2:
        fails.append("5: ms_unreadable is not in both languages")
    if "position_unreadable" not in page:
        fails.append("5: the map search does not read position_unreadable")
    if "L.control.scale" not in page:
        fails.append("5: the map has no scale")
    if "function stackPopup" not in page:
        fails.append("5: stations stacked on one point are not listed by name")
    src = (ROOT / "station_db.py").read_text(encoding="utf-8")
    if '"position_unreadable"' not in src:
        fails.append("5: the search result does not carry position_unreadable")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    placeholders and misreads are no position; the rest stay")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
