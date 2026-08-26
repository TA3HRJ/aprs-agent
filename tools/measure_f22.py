#!/usr/bin/env python3
"""Measure whether grouping openings by receiving gate would find anything.

Not a check — it asserts nothing and never fails. It answers F-22, which was
declined on 2026-08-26 (F-2026-08-26-06) on one 7.74-hour window, with the
caveat that zero rested on a small basis. This is how to re-ask it.

For every anomalous link in the ring, the opening rule is evaluated twice
inside the same 30-minute window:

    field grouping   2+ distinct base senders sharing the link's midpoint field
    gate grouping    2+ distinct base senders arriving at the same gate

The gap — gate says yes, field says no — is what F-22 proposed to capture.
Then the question that actually decides it: do those links survive the
established filter the opening loop already applies? A link flagged by the
300 km floor alone is a measurement, not evidence of a band opening, and it
never becomes one however it is grouped.

Usage:
    python tools/measure_f22.py [--base http://127.0.0.1:8080]
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packet_parser import _latlon_to_locator  # noqa: E402

WINDOW_S = 1800


def _base(l: dict) -> str:
    return str(l.get("call", "")).split("-")[0]


def _field(l: dict) -> str:
    return _latlon_to_locator((l["s_lat"] + l["g_lat"]) / 2,
                              (l["s_lon"] + l["g_lon"]) / 2)[:2]


def _established(l: dict) -> bool:
    return bool((l.get("at_flag") or {}).get("established", True))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8080")
    args = ap.parse_args(argv[1:])

    try:
        with urllib.request.urlopen(args.base.rstrip("/") + "/api/prop",
                                    timeout=90) as r:
            raw = json.load(r)["links"]
    except Exception as e:
        print("cannot reach %s: %s" % (args.base, e))
        return 1

    links = [l for l in raw
             if l.get("s_lat") is not None and l.get("g_lat") is not None]
    if len(links) < 20:
        print("ring holds %d usable links — too few to measure. It refills at "
              "roughly 32 an hour and a restart empties it; wait, then re-run."
              % len(links))
        return 0

    ts = [l["ts"] for l in links]
    print("%d links, %.2f hours" % (len(links), (max(ts) - min(ts)) / 3600.0))

    both = field_only = gate_only = neither = 0
    gap: list[dict] = []
    for l in links:
        near = [x for x in links if abs(x["ts"] - l["ts"]) <= WINDOW_S]
        fs = {_base(x) for x in near if _field(x) == _field(l)}
        gs = {_base(x) for x in near if x.get("gate") == l.get("gate")}
        fr, gr = len(fs) >= 2, len(gs) >= 2
        if fr and gr:
            both += 1
        elif fr:
            field_only += 1
        elif gr:
            gate_only += 1
            gap.append(l)
        else:
            neither += 1

    n = len(links)
    print("\nopening rule evaluated two ways, per link:")
    print("  both agree            %4d  (%.1f%%)" % (both, 100.0 * both / n))
    print("  field yes, gate no    %4d  (%.1f%%)"
          % (field_only, 100.0 * field_only / n))
    print("  GATE yes, field no    %4d  (%.1f%%)   <- F-22's gap"
          % (gate_only, 100.0 * gate_only / n))
    print("  neither               %4d  (%.1f%%)"
          % (neither, 100.0 * neither / n))

    if not gap:
        print("\nno gap in this window. F-22 has nothing to capture here.")
        return 0

    print("\nthe gap, and whether it survives the established filter:")
    for l in gap:
        f = l.get("at_flag") or {}
        print("  %-12s -> %-12s %7.1f km  field=%s  established=%s  %s"
              % (l.get("call", ""), l.get("gate", ""), l.get("km", 0),
                 _field(l), f.get("established"), f.get("judged_by", "")))

    survive = [l for l in gap if _established(l)]
    print("\n  survive it: %d of %d" % (len(survive), len(gap)))

    by_gate: dict[str, list] = defaultdict(list)
    for l in survive:
        by_gate[l["gate"]].append(l)
    extra = 0
    for g, ls in by_gate.items():
        senders = sorted({_base(x) for x in ls})
        if len(senders) >= 2:
            extra += 1
            print("  would open at %s: senders=%s" % (g, senders))

    fields: dict[str, list] = defaultdict(list)
    for l in links:
        if _established(l):
            fields[_field(l)].append(l)
    found = sum(1 for _, ls in fields.items()
                if len({_base(x) for x in ls}) >= 2)

    print("\nADDITIONAL openings gate grouping would produce: %d" % extra)
    print("openings the field rule finds in the same ring : %d" % found)
    if extra == 0:
        print("\nSame answer as 2026-08-26. The two filters compose: gate "
              "grouping only diverges at young gates with scattered distant "
              "traffic, and those links are already excluded.")
    else:
        print("\nDIFFERENT from 2026-08-26, which measured zero. "
              "F-2026-08-26-06 was decided on that; re-open it.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
