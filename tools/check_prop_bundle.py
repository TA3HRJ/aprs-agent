#!/usr/bin/env python3
"""Fail if a propagation bundle judges an event with numbers the event wrote.

Written before the fix, and expected to fail until it lands. An outside
reading of EA5URX-7 ⇄ EA5JFX-10 computed a threshold, a margin and a
confident verdict from a baseline the judged link had itself produced:

    at_flag        40 samples, ema 0.1 km      <- what the decision used
    gate_baseline  41 samples, mean 27.0 km,   <- what the bundle published
                   threshold 508.3 km

41 = 40 + 1, and the extra sample is the link. The EMA confirms it exactly:
0.95 x 0.1 + 0.05 x 538.2 = 27.0. The reader was not careless; the file
handed it a circle.

Three assertions, in the order they matter:

  1. every anomalous link carries at_flag at all
  2. gate_baseline.samples never exceeds at_flag.samples - if it does, the
     baseline was read after the event it is being used to judge
  3. at_flag carries the sigma and the threshold, not just the mean, so the
     bundle can show what the decision actually compared against

It also reports the multiplier the popup would print. The denominator is an
EMA that hugs zero on gates which mostly hear stations beside them, so the
same 539 km read 5382x against one gate and would have read 2696x against its
neighbour. A ratio whose denominator can approach zero is not a measure of
anything.

Usage:
    python tools/check_prop_bundle.py [--base http://127.0.0.1:8080] [--max 15]

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request

PROP_MIN_KM = 300.0          # the absolute floor a link must clear to be flagged


def _get(base: str, path: str, timeout: float = 60.0):
    url = base.rstrip("/") + path
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    ap.add_argument("--max", type=int, default=15,
                    help="how many links to fetch evidence for")
    args = ap.parse_args(argv[1:])

    try:
        prop = _get(args.base, "/api/prop")
    except Exception as e:
        print("cannot reach %s: %s" % (args.base, e))
        return 1

    links = prop.get("links", [])
    if not links:
        print("no anomalous links right now — nothing to check")
        return 0

    problems: list[str] = []
    ratios: list[tuple[float, str]] = []
    checked = 0

    # ── 1 · at_flag present at all ─────────────────────────────────────────
    missing = [l for l in links if not l.get("at_flag")]
    if missing:
        problems.append(
            "%d of %d links carry no at_flag, so nothing records what the "
            "decision used" % (len(missing), len(links)))

    for link in links[:args.max]:
        flag = link.get("at_flag") or {}
        call, gate = link.get("call", ""), link.get("gate", "")
        km = float(link.get("km") or 0)

        # ── 3 · the decision's full triple ─────────────────────────────────
        for field in ("sigma_km", "threshold_km"):
            if field not in flag:
                problems.append(
                    "%s -> %s: at_flag has no %s, so the bundle cannot show "
                    "what the distance was compared against"
                    % (call, gate, field))

        # what the popup would print
        ema = flag.get("ema_km")
        if ema:
            ratios.append((km / float(ema), "%s -> %s" % (call, gate)))
            if float(ema) < PROP_MIN_KM:
                problems.append(
                    "%s -> %s: the published multiplier divides %.1f km by an "
                    "ema of %.1f km — a denominator below the %.0f km floor "
                    "cannot bound the result (%.0fx here)"
                    % (call, gate, km, float(ema), PROP_MIN_KM, km / float(ema)))

        # ── 2 · the baseline must predate the event ────────────────────────
        q = urllib.parse.urlencode({"call": call, "gate": gate})
        try:
            ev = _get(args.base, "/api/prop/evidence?" + q)
        except Exception as e:
            problems.append("%s -> %s: evidence fetch failed: %s" % (call, gate, e))
            continue
        checked += 1

        base = ev.get("gate_baseline") or {}
        flag_n = flag.get("samples")
        base_n = base.get("samples")
        if isinstance(flag_n, int) and isinstance(base_n, int) and base_n > flag_n:
            problems.append(
                "%s -> %s: gate_baseline has %d samples against at_flag's %d. "
                "The extra %d arrived after the flag, so the baseline offered "
                "as this gate's own history includes the event it is judging"
                % (call, gate, base_n, flag_n, base_n - flag_n))

    print("checked %d of %d anomalous links against %s"
          % (checked, len(links), args.base))
    if ratios:
        ratios.sort(reverse=True)
        worst, who = ratios[0]
        print("largest published multiplier: %.0fx  (%s)" % (worst, who))

    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
