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

  4. the multiplier the bundle publishes divides by that threshold, and the
     threshold is at or above the 300 km floor

Assertion 4 was written the other way round on 2026-08-17: it read at_flag's
ema_km and failed if THAT was below the floor, because the popup at the time
divided by it. That was a proxy for the real question, and it is worth being
plain about why it changed while the fix was being written — moving a check's
goalposts to make it pass is the one edit that can make this file worthless.

What it asserts now is strictly more. Before: one number the popup happened to
use was in range. Now: the bundle publishes its own multiplier at all
(times_threshold), its denominator is named (threshold_km), that denominator
clears the floor, and the published figure actually equals km/denominator. A
client computing km/ema_km again would fail the first of those, because the
bundle would carry no multiplier of its own to match.

The reason the denominator moved: an EMA hugs zero on gates which mostly hear
stations beside them, so the same 539 km read 5382x against one gate and would
have read 2696x against its neighbour. A ratio whose denominator can approach
zero is not a measure of anything. threshold_km folds the 300 km floor in, so
it cannot.

Assertion 2 has a blind spot worth knowing: on a quiet gate the flag-time and
export-time sample counts are equal, and a bundle that had silently gone back
to publishing the live baseline would pass it by luck. So the flag-time block
must also say so — read_at — and the live one must still be published beside
it under its own name.

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
        # Not a pass. The ring buffer lives in memory, so a restart empties it
        # and the very command used to prove a deploy would print a clean bill
        # of health having examined nothing. On the live feed it refills at
        # roughly 25 anomalous links an hour; wait, then run it again.
        print("NOTHING CHECKED: no anomalous links in the buffer. A check "
              "that examined nothing has verified nothing — this is a "
              "failure, not a pass. After a restart the ring refills at "
              "roughly 25 links an hour.")
        return 1

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

        # ── 4 · the multiplier the bundle publishes, and what it divides by
        mult, den = flag.get("times_threshold"), flag.get("threshold_km")
        if mult is None:
            problems.append(
                "%s -> %s: at_flag publishes no times_threshold, so the "
                "multiplier shown to a reader is computed client-side from "
                "whatever field is to hand — which is how it came to divide "
                "by the ema" % (call, gate))
        elif den is None:
            problems.append(
                "%s -> %s: a multiplier of %sx is published with no "
                "threshold_km to say what it divided by"
                % (call, gate, mult))
        else:
            ratios.append((float(mult), "%s -> %s" % (call, gate)))
            if float(den) < PROP_MIN_KM:
                problems.append(
                    "%s -> %s: the published multiplier divides %.1f km by "
                    "%.1f km — a denominator below the %.0f km floor cannot "
                    "bound the result (%sx here)"
                    % (call, gate, km, float(den), PROP_MIN_KM, mult))
            elif abs(km / float(den) - float(mult)) > 0.06:
                problems.append(
                    "%s -> %s: publishes %sx, but %.1f / %.1f = %.2f. The "
                    "figure and the denominator beside it do not agree"
                    % (call, gate, mult, km, float(den), km / float(den)))

        # ── 2 · the baseline must predate the event ────────────────────────
        # ts matters. The same sender->gate pair is flagged again every time
        # the sender beacons from the same spot — 19 records for one pair on
        # the live feed — and without a timestamp the evidence endpoint
        # answers with the most RECENT one. This check then compared link A's
        # at_flag against link B's baseline and called it drift. Invisible
        # while gate_baseline was read live, because it was larger either way.
        q = urllib.parse.urlencode({"call": call, "gate": gate,
                                    "ts": link.get("ts", 0)})
        try:
            ev = _get(args.base, "/api/prop/evidence?" + q)
        except Exception as e:
            problems.append("%s -> %s: evidence fetch failed: %s" % (call, gate, e))
            continue
        checked += 1

        got = ev.get("link") or {}
        if got.get("ts") and link.get("ts") and got["ts"] != link["ts"]:
            problems.append(
                "%s -> %s: asked for the link at ts %s and the bundle "
                "answered with the one at %s, so every assertion below "
                "compares two different events"
                % (call, gate, link.get("ts"), got.get("ts")))
            continue

        base = ev.get("gate_baseline") or {}
        flag_n = flag.get("samples")
        base_n = base.get("samples")
        if isinstance(flag_n, int) and isinstance(base_n, int) and base_n > flag_n:
            problems.append(
                "%s -> %s: gate_baseline has %d samples against at_flag's %d. "
                "The extra %d arrived after the flag, so the baseline offered "
                "as this gate's own history includes the event it is judging"
                % (call, gate, base_n, flag_n, base_n - flag_n))
        # A quiet gate passes the count test whether the block is flag-time or
        # live, so the block has to say which it is.
        if base.get("read_at") != "flag time":
            problems.append(
                "%s -> %s: gate_baseline does not declare read_at: 'flag "
                "time'. On a quiet gate the sample counts match either way, "
                "so without this the name still cannot be trusted"
                % (call, gate))
        if not ev.get("gate_baseline_now"):
            problems.append(
                "%s -> %s: the current baseline is not published beside the "
                "flag-time one, so how far the gate has moved since is not "
                "visible" % (call, gate))

    print("checked %d of %d anomalous links against %s"
          % (checked, len(links), args.base))
    if ratios:
        ratios.sort(reverse=True)
        worst, who = ratios[0]
        print("largest published multiplier: %.0fx  (%s)" % (worst, who))

    if not checked:
        problems.append(
            "no link's evidence could be fetched, so assertions 2 and 4 "
            "never ran — a green here would mean nothing")

    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
