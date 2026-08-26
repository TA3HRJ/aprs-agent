#!/usr/bin/env python3
"""Fail if a gate's own repeated distance can still manufacture an opening.

Born from F-2026-08-26-03. Some gates measure the same large distance every
time, because the error is a fixed coordinate rather than anything in the
traffic. Measured on the live feed:

    KC3WJU-2   793 links at 1250.5 km +/- 0.4 km
    LU9DCE     514 links at 1694.9 km, sigma exactly 0.0

No propagation produces that and no busy gate does either. It is one geometry,
repeated — and repeated is exactly what makes it dangerous at the grouping
stage, where two DISTINCT senders in one field become an opening. Audited over
14 days of stored events, 3 of 245 openings existed only because of such a
link. One carried the same pair three times:

    K4OZS-10 -> KC3WJU-2  1250.3 km
    K4OZS-10 -> KC3WJU-2  1250.3 km
    K4OZS-10 -> KC3WJU-2  1250.3 km
    N8NOE-15 -> K2GB-10    864.4 km

The second sender was real; the first was one fixed error, three times.

Assertions:

  1. a link on a signature gate's own repeated distance is excluded
  2. a link on that SAME gate at a DIFFERENT distance is NOT excluded - the
     rule is on the link, and a signature gate making a real observation is
     the one thing worth hearing from it
  3. an ordinary gate is never touched, however long the link
  4. a gate with a large mean but honest spread is never touched: spread is
     what separates a real DX gate from a fixed error
  5. a YOUNG gate with the signature IS caught, from
     PROP_GEOMETRY_MIN_SAMPLES upward. This is the half a 20-sample bar would
     miss, and it is the noisy half: until 20 samples the floor decides alone,
     so a misplaced young gate flags everything it carries. RA4NHY-1 produced
     19 identical records at 1170.6 km +/- 0.35 that way
  6. a gate under that bar is still never touched - three readings are not a
     repetition
  7. the band survives a sigma of exactly zero, which is a real value here
     and would otherwise make the test razor-thin

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402

FIXED = "YM1ABC-10"        # anonymised: house rule, no real callsigns
ZERO_SIGMA = "YM2ABC-10"
ORDINARY = "TA1ABC-10"
WIDE = "TA2ABC-10"
YOUNG = "TA3ABC-10"


def main() -> int:
    problems: list[str] = []
    db = station_db_module.StationDB()

    def plant(gate, samples, mean, sigma):
        db._gate_stats[gate] = [float(samples), float(mean), float(sigma) ** 2]

    # The live shapes, anonymised.
    plant(FIXED, 793, 1250.5, 0.4)      # KC3WJU-2
    plant(ZERO_SIGMA, 514, 1694.9, 0.0)  # LU9DCE
    plant(ORDINARY, 3000, 20.6, 15.0)    # the median gate hears 20.6 km
    plant(WIDE, 299, 2019.6, 1012.7)     # a real DX gate: cv 0.50
    plant(YOUNG, 12, 1900.0, 3.0)        # the shape, but not enough samples

    f = db.fixed_geometry_link

    # 1 - the repeated distance is excluded
    if not f(FIXED, 1250.3):
        problems.append(
            "a link at 1250.3 km on a gate whose 793 samples average 1250.5 km "
            "with sigma 0.4 is that gate's own geometry, and it is not "
            "excluded. Repeated, it supplies its own second sender")
    if not f(ZERO_SIGMA, 1694.9):
        problems.append(
            "sigma is exactly 0.0 on this gate — a real value, seen on 514 "
            "live samples — and the link on its own mean is not excluded. The "
            "band has to be floored or a zero sigma makes it razor-thin")

    # 2 - a different distance at the same gate is a real observation
    for km in (800.0, 2400.0):
        if f(FIXED, km):
            problems.append(
                "a link at %.0f km on the signature gate is excluded. Its "
                "repeated value is 1250.5 km; a different distance is the one "
                "observation worth hearing from such a gate, and the rule is "
                "on the link, not the gate" % km)
    # just outside the band: 1% of 1250.5 is 12.5 km
    if f(FIXED, 1250.5 + 20):
        problems.append(
            "1270.5 km is 20 km off a 1250.5 km mean, outside the 12.5 km "
            "band, and is excluded anyway — the band is wider than declared")
    if not f(FIXED, 1250.5 + 5):
        problems.append(
            "1255.5 km is 5 km off the mean, inside the 12.5 km band, and is "
            "not excluded — the band is narrower than declared")

    # 3 - an ordinary gate is never touched
    for km in (350.0, 1500.0, 4000.0):
        if f(ORDINARY, km):
            problems.append(
                "an ordinary gate (mean 20.6 km) has a %.0f km link excluded. "
                "This rule is about a gate that always measures the same far "
                "distance, not about long links" % km)

    # 4 - honest spread is what separates a DX gate from a fixed error
    if f(WIDE, 2019.6):
        problems.append(
            "a gate with mean 2019.6 km and sigma 1012.7 km has its own mean "
            "excluded. That spread is a real DX gate; silencing it removes "
            "exactly the openings this detector exists for")

    # 5 - the young half, which is the noisy one
    if not f(YOUNG, 1900.0):
        problems.append(
            "a gate with 12 samples averaging 1900 km at sigma 3.0 is not "
            "caught. Until 20 samples the 300 km floor decides alone, so a "
            "misplaced young gate flags EVERY link it carries — RA4NHY-1 "
            "produced 19 identical records at 1170.6 km this way. Waiting for "
            "an established mean leaves exactly the noisy half untouched")
    # the two live shapes with the fewest samples, from F-2026-08-26-04
    db._gate_stats["TA4ABC-10"] = [6.0, 1009.0, 0.30 ** 2]   # CE3RHA-7
    db._gate_stats["TA5ABC-10"] = [8.0, 1176.3, 0.0]         # BG6JDU
    for g, km in (("TA4ABC-10", 1009.0), ("TA5ABC-10", 1176.3)):
        if not f(g, km):
            problems.append(
                "%s has %d samples at a coefficient of variation under 0.001 "
                "and is not caught. These are the live shapes the sample bar "
                "was chosen to include" % (g, int(db._gate_stats[g][0])))

    # 6 - but three readings are not a repetition
    db._gate_stats["TA6ABC-10"] = [3.0, 1900.0, 0.0]
    if f("TA6ABC-10", 1900.0):
        problems.append(
            "a gate with 3 samples is treated as having an established "
            "geometry. One station beaconing three times from one spot is not "
            "evidence that this gate always measures the same distance")

    # 6 - and the guard that matters if someone widens this later
    if f(ORDINARY, 20.6):
        problems.append(
            "an ordinary gate's own mean is excluded, so the rule has lost "
            "its 1000 km condition and now fires on every gate on the feed")

    print("checked %d planted baselines against a %d-sample geometry bar, "
          "including the live shapes with sigma 0.4, 0.0 and 0.30"
          % (len(db._gate_stats), db.PROP_GEOMETRY_MIN_SAMPLES))
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
