#!/usr/bin/env python3
"""Replay a raw packet log through the live ingest and opening rules.

AUDIT-2026-10-08 F5. Built twice before and thrown away twice
(F-2026-10-06-02, F-2026-10-08-01); kept here so the next measurement does
not start from nothing. Checked against the live record on 2026-10-08: in
the hours the agent listened, live 27 openings, replay 30.

    python tools/replay_feed.py SEED.db packets.log[.gz] [more logs...]
        [--utc-offset 2]

SEED.db is a backup taken before the log starts: it supplies station
positions and gate baselines. Log lines are `YYYY-MM-DDTHH:MM:SS <raw>` in
the host's local time (CEST = +2, CET = +1). Prints flagged links, suspect
share and openings a day under four rules: floor 300/250 km x suspect links
in/out of grouping. Read-only; nothing is written anywhere.

As a module: replay() and openings(), used by tools/check_feed_replay.py.
"""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import json
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402
from packet_parser import _latlon_to_locator  # noqa: E402


def replay(lines: Iterable[str], db, utc_offset_h: float = 2.0) -> dict:
    """Feed timestamped log lines to db.ingest() on the lines' own clock.

    Returns {"links": [...], "lines": n, "errors": {type: count},
    "t_start", "t_end"}. Every flagged link is kept (the live ring holds 500)
    with what the opening watch needs: suspect, fixed geometry, a position
    contradicting the callsign, and whether its gate was established.
    """
    tz = dt.timezone(dt.timedelta(hours=utc_offset_h))
    clock = [0.0]
    real_time = time.time
    links: list = []

    class Recorder(collections.deque):
        def append(self, x):
            links.append(x)
            super().append(x)

    db._prop_links = Recorder(maxlen=500)
    errors: collections.Counter = collections.Counter()
    n, t_start = 0, None
    time.time = lambda: clock[0]
    try:
        for line in lines:
            if len(line) < 21 or line[4] != "-" or line[10] != "T":
                continue
            try:
                ts = dt.datetime.strptime(line[:19], "%Y-%m-%dT%H:%M:%S") \
                    .replace(tzinfo=tz).timestamp()
            except ValueError:
                continue
            clock[0] = ts
            t_start = t_start or ts
            before = len(links)
            try:
                db.ingest(line[20:].rstrip("\r\n"))
            except Exception as e:
                errors[type(e).__name__] += 1
                continue
            for l in links[before:]:
                l["_fixed"] = db.fixed_geometry_link(l.get("gate", ""),
                                                     l.get("km", 0))
                sp = station_db_module.position_corroboration(
                    l.get("call"), l.get("s_lat"), l.get("s_lon"))
                gp = station_db_module.position_corroboration(
                    l.get("gate"), l.get("g_lat"), l.get("g_lon"))
                l["_contra"] = (sp.get("consistent") is False
                                or gp.get("consistent") is False)
                l["established"] = (l.get("at_flag") or {}).get(
                    "established", True)
                l["field"] = _latlon_to_locator(
                    (l["s_lat"] + l["g_lat"]) / 2,
                    (l["s_lon"] + l["g_lon"]) / 2)[:2]
            n += 1
    finally:
        time.time = real_time
    return {"links": links, "lines": n, "errors": dict(errors),
            "t_start": t_start or 0.0, "t_end": clock[0]}


def openings(links: list, t_start: float, t_end: float,
             keep_suspects: bool = False, min_km: float = 0.0,
             scan_s: int = 300, window_s: int = 1800) -> list:
    """The live opening watch (AgentManager._prop_watch) over replayed links.

    Every scan_s: links of the last window_s, minus contradicted positions,
    fixed geometry and (unless keep_suspects) suspect ones, grouped by the
    midpoint's field; a field opens an episode when its established links
    come from >= 2 base callsigns and it is not open already; a field with
    no kept link in the window closes. Returns [(ts, field, n_suspect)].
    """
    L = sorted((l for l in links if l.get("km", 0) >= min_km),
               key=lambda l: l["ts"])
    active, events, i = set(), [], 0
    recent: collections.deque = collections.deque()
    t = (int(t_start) // scan_s + 1) * scan_s
    while t <= t_end:
        while i < len(L) and L[i]["ts"] <= t:
            recent.append(L[i])
            i += 1
        while recent and recent[0]["ts"] <= t - window_s:
            recent.popleft()
        groups = collections.defaultdict(list)
        for l in recent:
            if l["_contra"] or l["_fixed"]:
                continue
            if l.get("suspect") and not keep_suspects:
                continue
            groups[l["field"]].append(l)
        for f, ls in groups.items():
            ls = [l for l in ls if l["established"]]
            if len({l["call"].split("-")[0] for l in ls}) < 2 or f in active:
                continue
            active.add(f)
            events.append((t, f, sum(1 for l in ls if l.get("suspect"))))
        active &= set(groups)
        t += scan_s
    return events


def _lines(paths):
    for p in paths:
        opener = gzip.open if p.endswith(".gz") else open
        with opener(p, "rt", encoding="utf-8", errors="replace") as f:
            yield from f


def main(argv: Optional[list] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    off = 2.0
    if "--utc-offset" in args:
        k = args.index("--utc-offset")
        off = float(args[k + 1])
        del args[k:k + 2]
    if len(args) < 2:
        print(__doc__)
        return 2
    seed, logs = args[0], args[1:]
    db = station_db_module.StationDB()
    print("seed stations", db.load_sqlite(seed))
    print("seed gates", db.import_gate_stats(json.loads(
        station_db_module.load_meta(seed, "prop_gate_stats", "{}"))))
    r = replay(_lines(logs), db, off)
    links, hours = r["links"], max(1e-9, (r["t_end"] - r["t_start"]) / 3600)
    sus = collections.Counter(l.get("suspect") for l in links if l.get("suspect"))
    print("lines %d over %.1f h, ingest errors %s" % (r["lines"], hours, r["errors"]))
    print("flagged links %d, suspect %d %s" % (len(links), sum(sus.values()), dict(sus)))
    for floor in (300.0, 250.0):
        for keep in (True, False):
            ev = openings(links, r["t_start"], r["t_end"], keep, floor)
            print("floor %3.0f km, suspects %-3s: %4d openings, %5.1f a day"
                  % (floor, "in" if keep else "out", len(ev), len(ev) / hours * 24))
    return 0


if __name__ == "__main__":
    sys.exit(main())
