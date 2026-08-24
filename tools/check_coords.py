#!/usr/bin/env python3
"""Fail if a position that is not on Earth can enter the agent.

A propagation evidence bundle reported DG2MMB-12 -> DB0OAL at 4646.2 km. Every
other part of it was sound: the threshold arithmetic checked to the decimal,
the baseline was flag-time and labelled as such, the multiplier divided by the
threshold. The sender's position was **lat 93.093, lon 986.8757**.

Reproduced straight from the parser:

    _ddmm_to_decimal("93",  "05.58", "N")  -> 93.093
    _ddmm_to_decimal("986", "52.54", "E")  -> 986.87567

APRS sends DDMM.mm / DDDMM.mm and the pattern reading it matches the digit
shape, never the range. So a corrupt packet produced a clean number, and the
locator, the haversine, the gate's distance baseline and the map all worked on
a point that does not exist. It was flagged as an anomalous RF link and
published as evidence.

The detection rule does claim to exclude "GPS garbage" — but by an upper
distance bound only. This link came in at 4646 km against a 5000 km ceiling,
so nothing tested it; it was let through by luck. **Range is not validity.**

What this holds:

  1. the exact live failure is rejected — no lat, no lon, no locator
  2. it is rejected on the compressed path too, not just the uncompressed one
  3. the boundary is inclusive: 90 and 180 are real places, 90.001 is not
  4. the rest of the packet survives — the symbol and comment are still true,
     and throwing the whole packet away would lose facts we do have
  5. an ordinary position is untouched, which is the way this check fails if
     somebody makes the test too strict

Callsigns here are anonymised, as every fixture in this directory is.

Usage:  python tools/check_coords.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packet_parser import parse_packet, _on_earth, _ddmm_to_decimal  # noqa: E402

HDR = "TA1ABC-12>APRS,TCPIP*,qAC,T2X:"

CASES = [
    # label,                 payload,                        on_earth
    ("live failure",         "!9305.58N/98652.54E>rig",      False),
    ("lat just over",        "!9000.01N/02706.00E>rig",      False),
    ("lon just over",        "!3826.00N/18000.01E>rig",      False),
    ("lat exactly 90",       "!9000.00N/02706.00E>rig",      True),
    ("lon exactly 180",      "!3826.00N/18000.00E>rig",      True),
    ("ordinary position",    "!3826.00N/02706.00E>rig",      True),
    ("southern/western",     "!3826.00S/02706.00W>rig",      True),
]


def main() -> int:
    problems: list[str] = []

    # The arithmetic that produced the live values, kept so the origin of this
    # check stays legible if the parser is ever rewritten.
    if abs(_ddmm_to_decimal("93", "05.58", "N") - 93.093) > 1e-4:
        problems.append("the DDMM decoder no longer reproduces the live case; "
                        "this check's premise needs re-deriving")

    for label, payload, should_be_on_earth in CASES:
        r = parse_packet(HDR + payload)
        has_pos = r.get("lat") is not None and r.get("lon") is not None
        flagged = bool(r.get("position_invalid"))

        if should_be_on_earth and not has_pos:
            problems.append("%s: a real position was thrown away -> %r"
                            % (label, payload))
        if should_be_on_earth and flagged:
            problems.append("%s: a real position was marked invalid" % label)

        if not should_be_on_earth:
            if has_pos:
                problems.append(
                    "%s: accepted lat=%s lon=%s — every distance measured to "
                    "it is arithmetic on garbage"
                    % (label, r.get("lat"), r.get("lon")))
            if r.get("locator"):
                problems.append("%s: built a locator (%s) from a point that is "
                                "not on Earth" % (label, r.get("locator")))
            if not flagged:
                problems.append("%s: dropped silently — nothing downstream can "
                                "tell this apart from a packet that simply "
                                "carried no position" % label)
            # 4 — the rest of the packet is still true
            if r.get("symbol") != ">":
                problems.append("%s: threw away the whole packet; the symbol "
                                "and comment were never in doubt" % label)

        print("  %-19s konum=%-5s isaretli=%-5s locator=%s"
              % (label, has_pos, flagged, r.get("locator")))

    # 2 — the compressed path shares nothing with the one above
    for la, lo, want in ((0.0, 0.0, True), (90.0, 180.0, True),
                         (-90.0, -180.0, True), (93.093, 986.8757, False),
                         (45.0, 200.0, False), (-91.0, 10.0, False)):
        if _on_earth(la, lo) != want:
            problems.append("_on_earth(%s, %s) said %s"
                            % (la, lo, not want))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
