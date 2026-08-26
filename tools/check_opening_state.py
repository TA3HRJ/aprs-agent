#!/usr/bin/env python3
"""Fail if an absent opening reads as a negative finding.

Born from F-09. The bundle published `opening: null` for three different
situations and six outside readings took all three to mean "this was not an
opening":

  * nothing else was heard in this field           - the absence it looks like
  * the rule IS met and no event was written       - the opposite
  * this process cannot answer                     - neither

The second happens when the episode was already open, or when a link was
excluded from the grouping - a contradicted position, or a gate's own repeated
geometry. The third happens after a restart, because the counts come from an
in-memory ring that a restart empties. A reader shown `null` in that state is
being told "no other sender was heard here" about a buffer that holds nothing
at all.

Assertions:

  1. a stored event reads as `recorded`
  2. two distinct senders in the field with no stored event read as
     `rule_met_not_recorded` - NOT as an absence
  3. one sender reads as `single_sender`
  4. an empty buffer reads as `unknown`, never `single_sender`. This is the
     restart case and the one that turns a fact about the process into a
     claim about the band
  5. a link with no usable positions reads as `unknown`
  6. the counts carry the window and the buffer size, so a zero is qualified
     rather than absolute

Exit code 1 if any assertion fails.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402

GATE = "YM1ABC-10"


def _link(ts, call, km=500.0, s_lat=39.0, s_lon=32.0):
    return {"ts": ts, "call": call, "gate": GATE, "km": km,
            "s_lat": s_lat, "s_lon": s_lon, "g_lat": 41.0, "g_lon": 29.0}


def main() -> int:
    problems: list[str] = []
    state = web_gui._prop_opening_status

    # ── 2 · two senders, nothing written ───────────────────────────────────
    db = station_db_module.StationDB()
    a = _link(1000, "TA1ABC-9")
    db._prop_links.append(a)
    db._prop_links.append(_link(1100, "TA2ABC-7", km=600.0, s_lat=39.5))
    ctx = db.prop_link_context(a)
    st = state(None, ctx)
    if st["state"] != "rule_met_not_recorded":
        problems.append(
            "two distinct senders in one field inside the window, with no "
            "stored event, reads as '%s'. That is the state a reader is most "
            "likely to misread as a negative finding, and it is the opposite "
            "of one" % st["state"])

    # ── 1 · a stored event ─────────────────────────────────────────────────
    st = state({"ts": 1000, "region": "KN", "links": [a]}, ctx)
    if st["state"] != "recorded":
        problems.append("a stored event reads as '%s'" % st["state"])

    # ── 3 · genuinely one sender ───────────────────────────────────────────
    db2 = station_db_module.StationDB()
    b = _link(1000, "TA1ABC-9")
    db2._prop_links.append(b)
    db2._prop_links.append(_link(1200, "TA1ABC-9", km=505.0))   # same operator
    ctx2 = db2.prop_link_context(b)
    st = state(None, ctx2)
    if st["state"] != "single_sender":
        problems.append(
            "one sender, twice, reads as '%s'. Two records of one operator "
            "are not two senders" % st["state"])

    # ── 4 · an empty buffer is not an absence ──────────────────────────────
    db3 = station_db_module.StationDB()
    ctx3 = db3.prop_link_context(_link(1000, "TA1ABC-9"))
    st = state(None, ctx3)
    if st["state"] == "single_sender":
        problems.append(
            "an EMPTY buffer reads as 'single_sender'. After a restart the "
            "ring holds nothing, so this reports a fact about the process as "
            "a claim about the band — which is the whole defect F-09 is "
            "about, moved one level down")
    if st["state"] != "unknown":
        problems.append("an empty buffer reads as '%s', expected 'unknown'"
                        % st["state"])

    # ── 5 · no positions, no field, no answer ──────────────────────────────
    db4 = station_db_module.StationDB()
    c = {"ts": 1000, "call": "TA1ABC-9", "gate": GATE, "km": 500.0}
    db4._prop_links.append(c)
    st = state(None, db4.prop_link_context(c))
    if st["state"] != "unknown":
        problems.append(
            "a link with no usable positions reads as '%s'. No field can be "
            "computed from it, so the rule was never evaluated" % st["state"])

    # ── 6 · a zero has to be qualified ─────────────────────────────────────
    buf = ctx.get("buffer") or {}
    for field in ("anomalous_links_held", "window_s"):
        if buf.get(field) is None:
            problems.append(
                "context.buffer has no %s, so 'no other sender' is stated "
                "without saying over what span or against how much data"
                % field)
    for key in ("in_field", "at_this_gate", "this_pair",
                "gate_anomalous_share"):
        if key not in ctx:
            problems.append("context is missing %s" % key)

    # A bare label is a worse null than the one it replaced: it looks like an
    # answer. Every state has to carry its own sentence.
    for ev, c, name in ((None, ctx, "rule_met_not_recorded"),
                        ({"ts": 1, "region": "KN", "links": []}, ctx,
                         "recorded"),
                        (None, ctx2, "single_sender"),
                        (None, ctx3, "unknown")):
        r = state(ev, c)
        if not r.get("reading"):
            problems.append("state '%s' is published with no reading beside "
                            "it" % r.get("state", name))

    print("checked the four opening states against planted buffers")
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
