#!/usr/bin/env python3
"""Fail if a question about nearby digipeaters is not answered from the
registry, with digipeaters heard recently.

2026-10-14 06:56: KR4OII-1 asked "igate near me" and was told the two
nearest igates. Twenty seconds later "digipeater near me" matched nothing,
went to the model, and came back "Sorry, I have no live data, so no
digipeater list" - from a gateway whose registry held 10,829 digipeaters,
the nearest heard that day 34 km from him. "Nearest digi" did match, but
the igate rule: it was answered with igates, under the word "igates".

What must hold:

  1. "digipeater near me", "nearest digi", "digis around" and "en yakin
     digi" are answered from the registry, no model call, naming
     digipeaters with distances and the word "digipeater"
  2. the registry is asked for type "digi" only
  3. a digipeater not heard for over a week is left out; none left means
     "no digipeater heard this week", not a stale call sign
  4. "igate near me" still names igates

No network and no provider: the registry and the model are stubbed.

Usage:  python tools/check_digi_near.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
       "api_keys": {"deepseek": "stub"}, "extra_sms": 2,
       "rate_burst": 0, "rate_refill_s": 0}
DAY = 86400

ASKER = {"callsign": "KR4OII-1", "lat": 33.56, "lon": -85.87,
         "locator": "EM73", "last_seen_ago_s": 60, "last_gate": "",
         "type": "car"}
# the live picture near KR4OII-1 on 2026-10-19, ages simplified
DIGIS = [({"callsign": "K4TH-1", "type": "digi", "last_seen_ago_s": 3600}, 34.0),
         ({"callsign": "N9HO-10", "type": "digi", "last_seen_ago_s": 7200}, 43.0),
         ({"callsign": "KR4ISQ-2", "type": "digi", "last_seen_ago_s": 56 * DAY}, 44.0)]
STALE_ONLY = [({"callsign": "KR4ISQ-2", "type": "digi",
                "last_seen_ago_s": 56 * DAY}, 44.0)]
IGATES = [({"callsign": "AJ4AR-10", "type": "igate", "last_seen_ago_s": 60}, 44.0)]


class FakeDB:
    def __init__(self, digis):
        self.digis = digis
        self.kinds = []

    def get_one(self, call):
        return dict(ASKER) if call.upper() == "KR4OII-1" else None

    def nearest_of_type(self, lat, lon, kinds, max_km=250.0, limit=3):
        self.kinds.append(tuple(kinds))
        if "digi" in kinds:
            return [(dict(r), km) for r, km in self.digis][:limit]
        if "igate" in kinds or "gateway" in kinds:
            return [(dict(r), km) for r, km in IGATES][:limit]
        return []

    def has_gated(self, call):
        return False

    def nearest_wx(self, lat, lon, radius):
        return None

    def prop_summary(self, max_links=200):
        return {"links": []}


async def ask(text, digis=DIGIS):
    sent, calls = [], {"n": 0}

    class Q:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    tmp = Path(tempfile.mkdtemp(prefix="check_digi_"))
    gw = AIGateway(dict(CFG), str(tmp / "aprsconfig.toml"))
    gw._own_writer = Q()
    db = FakeDB(digis)
    gw.set_station_db(db)

    async def stub(question, sender="", history=None):
        calls["n"] += 1
        return "Sorry, I have no live data."
    gw._ask_ai = stub
    await gw.handle("KR4OII-1>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s{7" % text)
    out = []
    for s in sent:
        body = s.split("::", 1)[1][9:].lstrip(":")
        if not body.startswith(("ack", "rej")):
            out.append(body.rsplit("{", 1)[0].replace(" --", "").strip())
    return " ".join(out), calls["n"], db.kinds


async def main() -> int:
    problems = []
    for q in ("digipeater near me", "nearest digi", "Any digis around here?",
              "en yakin digi"):
        a, n, kinds = await ask(q)
        print(f"  {q!r:26} -> {a!r}")
        if n:
            problems.append(f"{q!r} went to the model")
        if "digipeater" not in a.lower() or "K4TH-1" not in a or "34km" not in a:
            problems.append(f"{q!r} not answered with digipeaters: {a!r}")
        if "KR4ISQ-2" in a:
            problems.append(f"{q!r} named a digipeater silent for 56 days")
        if kinds and any(k != ("digi",) for k in kinds):
            problems.append(f"{q!r} asked the registry for {kinds}")
    a, n, _ = await ask("digipeater near me", STALE_ONLY)
    print(f"  {'(only a stale digi)':26} -> {a!r}")
    if n or "KR4ISQ-2" in a or "this week" not in a:
        problems.append(f"with only a stale digi: {a!r}")
    a, n, kinds = await ask("igate near me")
    print(f"  {'igate near me':26} -> {a!r}")
    if n or "AJ4AR-10" not in a or "igate" not in a.lower():
        problems.append(f"igate near me broke: {a!r} {kinds}")
    if problems:
        print("\nFAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
