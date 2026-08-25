#!/usr/bin/env python3
"""Fail if the evidence endpoint answers with a link other than the one asked for.

Born from a live failure, 2026-08-25. `check_prop_bundle.py` went green on
2026-08-22 and red three days later without a line of detector code changing
in between. Nothing had regressed: the check samples the top --max links, and
on the 22nd none of them happened to come from a pair that beacons quickly.

What it found when the sample did include one:

    SV6NMP-9 -> SV1TNT-10: asked for the link at ts 1787652150
                           and the bundle answered with the one at 1787652439

The endpoint matched on `abs(l["ts"] - want_ts) <= 300` while walking the ring
NEWEST-FIRST. A sender beaconing every 15 s puts about twenty records for one
pair inside that tolerance, so the answer was the newest of them — a different
event, carrying a different baseline. Every assertion a reader then made
compared two things that were never the same link. That is precisely the
circle §B was built to close, arriving through the door the fix missed:
v3.2.81 taught the CHECK to send a timestamp and refuse on a mismatch, and
stopped there. The server was never taught to honour it.

Two lessons this file exists to hold:

  * A check whose sample is chosen by luck reports the weather, not the code.
    `check_prop_bundle` needs a live API and a repeating pair in its window.
    This one is offline and builds the burst itself, so it cannot go green by
    being asked an easy question.

  * Nearest is not newest. The 300 s tolerance is there for a ts that came
    from a stored event (rounded to the event, not the link), and that is a
    fair thing to want. Taking the newest match rather than the nearest is
    what turned a reasonable tolerance into a wrong answer.

Assertions:

  1. an exact ts must come back as itself, for every record in a fast burst
  2. a ts with no exact match resolves to the NEAREST record within 300 s
  3. no ts at all still answers with the most recent, as it always did
  4. a ts outside the tolerance is a 404, not the nearest thing to hand
  5. the stored-event door obeys 1 and 2 as well — one rule, both entrances

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import make_mocked_request  # noqa: E402

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402

CALL = "TA1ABC-9"          # anonymised: house rule, no real callsigns in fixtures
GATE = "YM1ABC-10"
T0 = 1787650000
STEP = 15                  # the burst cadence that exposed this
N = 20                     # ~5 minutes of it, so the whole tolerance is full


def _link(ts: int, km: float = 4984.0) -> dict:
    """One anomalous link, shaped like the ones the ring actually holds."""
    return {
        "ts": ts, "call": CALL, "gate": GATE, "km": km,
        "s_lat": 38.4232, "s_lon": 22.4882,
        "g_lat": 39.9208, "g_lon": 32.8541,
        "at_flag": {
            "samples": ts - T0,          # distinct per record — this is the tell
            "ema_km": 4988.0, "sigma_km": 12.0, "gate_bar_km": None,
            "threshold_km": 300.0, "times_threshold": round(km / 300.0, 1),
            "established": False, "judged_by": "300 km floor alone",
            "gate_decided": False,
        },
    }


class _StubManager:
    """Only what get_prop_evidence touches."""

    def __init__(self, db, db_path: str) -> None:
        self._station_db = db
        self._sta_db_path = db_path

    def get_config(self) -> dict:
        return {}


def _ask(mgr, ts: int | None, blind: bool = False):
    """Call the real handler and return (status, bundle)."""
    q = f"call={CALL}&gate={GATE}"
    if ts is not None:
        q += f"&ts={ts}"
    if blind:
        q += "&blind=1"
    req = make_mocked_request("GET", f"/api/prop/evidence?{q}",
                              app={"manager": mgr})
    resp = asyncio.run(web_gui.get_prop_evidence(req))
    return resp.status, json.loads(resp.body.decode("utf-8"))


def main() -> int:
    problems: list[str] = []

    db = station_db_module.StationDB()
    burst = [_link(T0 + i * STEP) for i in range(N)]
    for l in burst:
        db._prop_links.append(l)
    # A path that does not exist, so find_prop_event returns None and the ring
    # is the only door under test here.
    mgr = _StubManager(db, str(Path(__file__).parent / "_no_such_db.sqlite"))

    # ── 1 · an exact ts comes back as itself ───────────────────────────────
    for l in burst:
        want = l["ts"]
        status, ev = _ask(mgr, want)
        if status != 200:
            problems.append(f"ts {want}: status {status}, expected 200")
            continue
        got = (ev.get("link") or {}).get("ts")
        if got != want:
            problems.append(
                f"asked for the link at ts {want} and the bundle answered with "
                f"the one at {got} — {got - want:+d} s, a different event with "
                f"a different baseline")
        # and the baseline published must be the one that link carries
        base = ev.get("gate_baseline") or {}
        if base.get("samples") not in (None, l["at_flag"]["samples"]):
            problems.append(
                f"ts {want}: gate_baseline.samples is {base.get('samples')}, "
                f"but this link was flagged at {l['at_flag']['samples']} — the "
                f"bundle is publishing another link's history")

    # ── 2 · no exact match resolves to the NEAREST, not the newest ─────────
    # 7 s after the third record: nearest is that record, newest in tolerance
    # is the last one of the burst.
    target = burst[2]["ts"]
    status, ev = _ask(mgr, target + 7)
    got = (ev.get("link") or {}).get("ts")
    if status != 200:
        problems.append(f"near-miss ts: status {status}, expected 200")
    elif got != target:
        newest_in_tol = max(l["ts"] for l in burst
                            if abs(l["ts"] - (target + 7)) <= 300)
        how = "the newest in tolerance" if got == newest_in_tol else "neither"
        problems.append(
            f"a ts 7 s from record {target} resolved to {got} ({how}). The "
            f"tolerance exists for a ts rounded to a stored event; it has to "
            f"land on the closest link, not the latest one")

    # ── 3 · no ts at all still answers with the most recent ────────────────
    status, ev = _ask(mgr, None)
    got = (ev.get("link") or {}).get("ts")
    if got != burst[-1]["ts"]:
        problems.append(
            f"with no ts the endpoint answered {got}, expected the most recent "
            f"{burst[-1]['ts']} — this is the one case where newest is right")

    # ── 4 · outside the tolerance is a 404, not the nearest thing to hand ──
    status, ev = _ask(mgr, T0 - 10_000)
    if status != 404:
        got = (ev.get("link") or {}).get("ts")
        problems.append(
            f"a ts 10 000 s before the burst returned {status} with link {got}. "
            f"Out of range has to be an absence, not the closest match — a "
            f"silent substitution is how this whole class of fault reads")

    # ── 5 · the stored-event door obeys the same rule ──────────────────────
    # The ring is emptied, so the only remaining source is the stored opening.
    db2 = station_db_module.StationDB()
    mgr2 = _StubManager(db2, "unused")
    want = burst[5]["ts"]
    event = {"ts": T0, "region": "KM38", "note": "", "links": burst,
             "link_count": len(burst),
             "distinct_senders": [CALL.split("-")[0]],
             "max_km": 4984.0}
    orig = station_db_module.find_prop_event
    station_db_module.find_prop_event = lambda *a, **k: event
    web_gui.station_db_module.find_prop_event = lambda *a, **k: event
    try:
        status, ev = _ask(mgr2, want)
        got = (ev.get("link") or {}).get("ts")
        if status != 200:
            problems.append(f"stored-event door: status {status}, expected 200")
        elif got != want:
            problems.append(
                f"stored-event door: asked for ts {want}, got {got}. The ring "
                f"was taught to match exactly and this entrance was not — a "
                f"validity rule enforced at one door is not enforced")
    finally:
        station_db_module.find_prop_event = orig
        web_gui.station_db_module.find_prop_event = orig

    print(f"checked a {N}-record burst at {STEP}s spacing "
          f"({(N - 1) * STEP}s span, tolerance is 300s)")
    for p in problems:
        print("FAIL  " + p)
    print(f"{len(problems)} problem{'' if len(problems) == 1 else 's'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
