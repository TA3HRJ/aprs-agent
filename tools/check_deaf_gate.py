#!/usr/bin/env python3
"""Fail if a gate that can no longer flag anything goes unreported.

Born from F-2026-08-26-01. A gate's bar is max(3*mean, mean + 4*sigma). Once
that passes PROP_MAX_KM nothing can ever clear it, because a longer link is
discarded as GPS garbage before the comparison is reached. The gate stops
flagging and no counter moves to say so.

That is the worst shape a fault can take here: from outside, a gate that has
gone deaf and a gate over a quiet band look identical — both report nothing.
On the live feed 25 of 7316 established gates were already in that state, and
two were watched crossing over inside one 7.4 h window:

    VE2SIL-1   10 flags of 10 links at samples 10-19,
               then samples 23, bar 5778 km, and nothing ever again

There is no state in between. A gate goes from flagging every link it carries
to flagging none, on the sample that makes it established.

Assertions:

  1. a gate whose bar passes the ceiling is reported
  2. it is reported with the numbers that put it there, so a reader can tell
     the two causes apart - a transient poisoning decays out, a wrong gate
     position never does
  3. the fixed-distance signature (large mean, almost no spread) is flagged,
     because that is the one that cannot recover
  4. a gate still under the ceiling is NOT reported - the direction this
     fails if someone widens it
  5. a young gate is never reported, however wild its numbers: under
     PROP_MIN_SAMPLES the floor decides and the gate's own bar is not used
  6. recovery is possible - a baseline that comes back down leaves the set,
     which is what DB0OAL did over ~1900 samples
  7. the set survives a restart, rebuilt from the restored baselines rather
     than waiting for each gate's next packet - and the quietest gates are
     exactly the ones that would wait longest

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402

DEAF = "YM1ABC-10"      # anonymised: house rule, no real callsigns in fixtures
HEALTHY = "TA1ABC-10"
YOUNG = "TA2ABC-10"
TRANSIENT = "TA3ABC-10"


def _set(db, gate, samples, mean, sigma):
    """Plant a baseline directly, the way a restart restores one."""
    db._gate_stats[gate] = [float(samples), float(mean), float(sigma) ** 2]
    db._update_gate_reach(gate, db._gate_stats[gate])


def main() -> int:
    problems: list[str] = []
    db = station_db_module.StationDB()
    ceiling = db.PROP_MAX_KM

    # A gate whose own position is wrong: every link the same wrong distance.
    _set(db, DEAF, 77, 4979.4, 4.7)
    # An ordinary gate.
    _set(db, HEALTHY, 3000, 96.8, 37.1)
    # Wild numbers but too few samples for its own bar to be used at all.
    _set(db, YOUNG, 8, 4900.0, 3.0)
    # Poisoned by a stream of bad senders - large mean AND large spread.
    _set(db, TRANSIENT, 40, 1518.6, 2167.5)

    rep = {r["gate"]: r for r in db.deaf_gates()}

    # 1 - reported at all
    if DEAF not in rep:
        problems.append(
            "%s has a bar of %.0f km against a %.0f km ceiling and is not "
            "reported. It can never flag again, and an unreported deaf gate "
            "is indistinguishable from a quiet band"
            % (DEAF, max(3 * 4979.4, 4979.4 + 4 * 4.7), ceiling))
        print("0 of the assertions below can run without this")
        print("1 problem")
        return 1

    # 2 - with the numbers that caused it
    for field in ("samples", "mean_km", "sigma_km", "bar_km"):
        if rep[DEAF].get(field) is None:
            problems.append(
                "%s is reported without %s, so a reader cannot tell a "
                "transient poisoning (which decays out) from a wrong gate "
                "position (which never does)" % (DEAF, field))
    if rep[DEAF].get("bar_km", 0) < ceiling:
        problems.append(
            "%s is reported with bar_km %.1f, below the ceiling it is "
            "supposed to have passed" % (DEAF, rep[DEAF].get("bar_km", 0)))

    # 3 - the signature that cannot recover
    if not rep[DEAF].get("fixed_distance"):
        problems.append(
            "%s shows mean 4979.4 km with sigma 4.7 km — the same wrong "
            "distance every time, which is a fixed coordinate and not "
            "propagation — and fixed_distance is not set" % DEAF)
    if rep.get(TRANSIENT, {}).get("fixed_distance"):
        problems.append(
            "%s has sigma 2167.5 km against mean 1518.6 km, which is spread, "
            "not a fixed geometry. Marking it fixed_distance would send a "
            "reader to reset a baseline that recovers on its own" % TRANSIENT)

    # 4 - a healthy gate is left alone
    if HEALTHY in rep:
        problems.append(
            "%s has a bar of 290.5 km, far under the ceiling, and is reported "
            "as unable to flag. This is the direction the check fails if the "
            "rule is widened" % HEALTHY)

    # 5 - a young gate is never judged by a bar it does not use
    if YOUNG in rep:
        problems.append(
            "%s has only 8 samples, so the 300 km floor decides and its own "
            "bar is never consulted. Reporting it as deaf describes a rule "
            "that did not run" % YOUNG)

    # 6 - recovery leaves the set
    _set(db, DEAF, 1935, 96.8, 37.1)
    if DEAF in {r["gate"] for r in db.deaf_gates()}:
        problems.append(
            "%s came back to mean 96.8 km / sigma 37.1 km and is still "
            "reported. DB0OAL did exactly this over ~1900 samples; a set that "
            "only grows would accuse a recovered gate forever" % DEAF)

    # 7 - the set survives a restart
    db2 = station_db_module.StationDB()
    n = db2.import_gate_stats({
        DEAF: [77.0, 4979.4, 4.7 ** 2],
        HEALTHY: [3000.0, 96.8, 37.1 ** 2],
    })
    after = {r["gate"] for r in db2.deaf_gates()}
    if n != 2:
        problems.append("import_gate_stats restored %d of 2 baselines" % n)
    if DEAF not in after:
        problems.append(
            "%s was deaf before the restart and is not reported after it. "
            "Rebuilding only when the next packet arrives leaves the quietest "
            "gates — the ones worth reporting — unreported longest" % DEAF)
    if HEALTHY in after:
        problems.append(
            "%s is reported as deaf after a restart but not before it, so the "
            "rebuild does not agree with the live path" % HEALTHY)

    print("checked 4 planted baselines and one restart against a %.0f km "
          "ceiling" % ceiling)
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
