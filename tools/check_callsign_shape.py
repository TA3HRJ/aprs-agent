#!/usr/bin/env python3
"""Fail if a wildcard station filter can admit something that is not a station.

Seen live on 2026-09-06, in the first three minutes of message history that
v3.2.101 ever wrote:

    14:45  YM2KY-1    -> BLN2LOCAL   Save lives, stay at home! ...
    14:48  YM2KY-1    -> BLN1LOCAL   Keep your distance ...
    14:48  KA7EZO-7   -> TACTICAL    KA7EZO-7=MPSar

The third row is American traffic, stored because the operator's filter is
`TA*` and **TACTICAL starts with TA**. It is a group addressee, not a Turkish
station. The same trap is recorded in this repository already — "an APRS
object named TABOR is not a Turkish station" — but only where callsign regions
are judged, not where the filter is applied.

A wildcard is a prefix and a prefix cannot tell a callsign from a group name.
The digit does: every amateur callsign has one in the right place and none of
TACTICAL, ANSRVR, BLN2LOCAL, TABOR, KTB7, 3X7, TAT or TX7 does.

Three places apply the filter, and all three are held here:

  1. message history — what gets archived for fourteen days
  2. the AI gateway whitelist — **who gets answered**, which spends money and
     puts a transmission on a shared channel
  3. the silence sensor filter — what is allowed to count as a station that
     fell silent, which is F-2026-08-26-07 arriving through the filter rather
     than through the feed

And one place that must NOT be changed:

  4. the APRS-IS server-side filter in aprs_connection, which speaks the
     network's own `p/` syntax and cannot express "must contain a digit".
     Narrowing it locally would ask the server for less than we want.

An exact filter entry is honoured as written in all three: naming an
identifier is meaning it.

Usage:  python tools/check_callsign_shape.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packet_parser import looks_like_callsign          # noqa: E402
from station_db import StationDB                       # noqa: E402
from web_gui import AgentManager                       # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


# ── the shape test itself ─────────────────────────────────────────────
REAL = ["TA3HRJ-7", "TA3HRJ", "YM3KC-8", "W3AKU", "2E0ABC", "KH7EH-04",
        "9W2JVA-7", "KE9AEK-5", "VK2AHB-7"]
NOT_REAL = ["TACTICAL", "ANSRVR", "BLN2LOCAL", "TABOR", "KTB7", "3X7", "TAT",
            "TX7", "NWS-WARN", "RGSTRY", "OTA"]
bad = [c for c in REAL if not looks_like_callsign(c)]
if bad:
    fail("real callsigns pass", f"rejected {bad}")
else:
    ok(f"{len(REAL)} real callsigns pass, SSIDs and 2-character prefixes included")
bad = [c for c in NOT_REAL if looks_like_callsign(c)]
if bad:
    fail("group and object names fail", f"accepted {bad}")
else:
    ok(f"{len(NOT_REAL)} group/object identifiers are rejected")


# ── 1. message history ────────────────────────────────────────────────
class _Probe(AgentManager):
    def __init__(self, cfg):
        self._cfg = cfg

    def get_config(self):
        return self._cfg


p = _Probe({"allowed_callsigns": ["TA*", "TB*"],
            "extensions": {"ai_gateway": {"callsign": "DMWGPT"}}})


def msg(frm, to):
    return {"from": frm, "to": to, "text": "x", "ts": 1, "msg_id": "1"}


if p._msg_kept(msg("KA7EZO-7", "TACTICAL")):
    fail("history: TACTICAL", "the live case is still archived")
else:
    ok("history: KA7EZO-7 -> TACTICAL is not archived")
if not p._msg_kept(msg("TA3HRJ-7", "ANSRVR")):
    fail("history: real station", "a genuine TA station stopped being kept")
else:
    ok("history: a genuine TA station is still kept")
if not p._msg_kept(msg("KO6FFZ", "DMWGPT")):
    fail("history: gateway", "the gateway's own traffic stopped being kept — "
                             "DMWGPT is not callsign-shaped and must not need to be")
else:
    ok("history: the gateway is kept although its name is not a callsign")

exact = _Probe({"allowed_callsigns": ["TACTICAL"],
                "extensions": {"ai_gateway": {"callsign": "DMWGPT"}}})
if not exact._msg_kept(msg("KA7EZO-7", "TACTICAL")):
    fail("history: exact entry", "an exact filter entry was overruled")
else:
    ok("history: an exact filter entry is honoured as written")


# ── 3. silence sensor filter ──────────────────────────────────────────
db = StationDB.__new__(StationDB)
db.feed_filter = ["TA*", "YM*"]
if db._matches_feed("TACTICAL"):
    fail("sensors: TACTICAL", "a group addressee can be a silence sensor")
else:
    ok("sensors: TACTICAL cannot be a silence sensor")
if not db._matches_feed("TA3HRJ-7"):
    fail("sensors: real station", "a genuine station stopped matching the feed")
else:
    ok("sensors: a genuine station still matches the feed")
db.feed_filter = ["TACTICAL"]
if not db._matches_feed("TACTICAL"):
    fail("sensors: exact entry", "an exact feed entry was overruled")
else:
    ok("sensors: an exact feed entry is honoured as written")


# ── 2. the AI gateway whitelist, read from the source ─────────────────
# Building a live AIGateway needs a provider key and an event loop, so the
# guard is asserted structurally: the wildcard branch must consult the shape.
src = (ROOT / "extensions" / "ai_gateway_ext.py").read_text(encoding="utf-8")
m = re.search(r"if not any\((.{0,400}?)\bfor w in whitelist", src, re.S)
if not m:
    fail("whitelist: found", "the whitelist test is no longer recognisable")
elif "looks_like_callsign" not in m.group(1):
    fail("whitelist: shape applied",
         "the wildcard branch admits anything with the right prefix — "
         "a station calling itself TACTICAL would be answered")
elif "sender_base == w" not in m.group(1):
    fail("whitelist: exact entry", "an exact whitelist entry no longer matches")
else:
    ok("whitelist: the wildcard branch requires a callsign, the exact one does not")


# ── 4. the server-side filter must be left alone ──────────────────────
conn = (ROOT / "aprs_connection.py").read_text(encoding="utf-8")
if "looks_like_callsign" in conn:
    fail("server filter untouched",
         "the APRS-IS p/ filter cannot express this and must not try")
else:
    ok("the APRS-IS server-side filter is deliberately left alone")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
