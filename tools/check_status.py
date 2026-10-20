#!/usr/bin/env python3
"""Fail if DMWGPT's STATUS / DURUM does not report a square's silence state
and nearby quake rings from the facts the map is drawn from.

What must hold:

  1. "STATUS KM38" answers from the provider, no model call: an alerting
     cell names "regional silence", its start in UTC and k of n stations;
     an igate-caused one says igate fault; a quiet one says all on the air
  2. "DURUM" with no square uses the square of the sender's last beacon,
     and answers in Turkish
  3. no square and no known position: asks for a square
  4. "STATUS KM": the alerting squares of the field
  5. a quake ring near the square is appended, with its count
  6. the feed is deaf: status unknown, not "no silence"
  7. "status of my order" is a question for the model
  8. AgentManager._grid_status picks the square's cell, the episode start,
     the field's alerting cells, and only quake rings that reach the square

Usage:  python tools/check_status.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_gui  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
       "api_keys": {"deepseek": "stub"}, "extra_sms": 2,
       "rate_burst": 0, "rate_refill_s": 0}
SINCE = 1792000000       # 2026-10-15 ... a fixed UTC moment
SINCE_HM = time.strftime("%H:%M UTC", time.gmtime(SINCE))


class FakeDB:
    def __init__(self, pos=True):
        self.pos = pos

    def get_one(self, call):
        if self.pos and call.upper().startswith("TA1ABC"):
            return {"callsign": "TA1ABC-7", "lat": 38.45, "lon": 27.10}
        return None


async def ask(text, provider_result, pos=True):
    sent, calls, asked = [], {"n": 0}, []

    class Q:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), str(Path(tempfile.mkdtemp()) / "aprsconfig.toml"))
    gw._own_writer = Q()
    gw.set_station_db(FakeDB(pos))

    async def provider(grid):
        asked.append(grid)
        return provider_result

    gw.set_status_provider(provider)

    async def stub(question, sender="", history=None):
        calls["n"] += 1
        return "model answer"
    gw._ask_ai = stub
    await gw.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s{9" % text)
    out = []
    for s in sent:
        body = s.split("::", 1)[1][9:].lstrip(":")
        if not body.startswith(("ack", "rej")):
            out.append(body.rsplit("{", 1)[0].removesuffix(" --").strip())
    return " ".join(out), calls["n"], asked


ALERT = {"cell": {"baseline": 31, "silent": 9, "alert": True, "cause": "outage",
                  "since": SINCE}, "quakes": []}
IGATE = {"cell": {"baseline": 20, "silent": 6, "alert": True, "cause": "igate"},
         "quakes": []}
QUIET = {"cell": {"baseline": 31, "silent": 0, "alert": False, "cause": ""},
         "quakes": [{"mag": 6.4, "km": 120.0, "hours": 2.0, "measured": True,
                     "k": 7, "n": 40, "unusual": True}]}


async def main() -> int:
    p = []

    a, n, g = await ask("STATUS KM38", ALERT)
    print(f"  {'STATUS KM38 (alert)':24} -> {a!r}")
    if n or g != ["KM38"] or "regional silence since " + SINCE_HM not in a \
            or "9 of 31" not in a:
        p.append(f"alerting cell: {a!r} (model {n}, asked {g})")

    a, n, g = await ask("status km38nk?", IGATE)
    print(f"  {'status km38nk? (igate)':24} -> {a!r}")
    if n or g != ["KM38"] or "igate fault" not in a:
        p.append(f"igate cell: {a!r}")

    a, n, g = await ask("STATUS KM38", QUIET)
    print(f"  {'STATUS KM38 (quiet+quake)':24} -> {a!r}")
    if n or "all 31 fixed stations on the air" not in a \
            or "M6.4 quake 120 km away" not in a or "7 of 40" not in a \
            or "(unusual)" not in a:
        p.append(f"quiet cell with quake: {a!r}")

    a, n, g = await ask("DURUM", ALERT)
    print(f"  {'DURUM (own position)':24} -> {a!r}")
    if n or g != ["KM38"] or "bolgesel sessizlik" not in a:
        p.append(f"DURUM from own position: {a!r} asked {g}")

    a, n, g = await ask("STATUS", ALERT, pos=False)
    print(f"  {'STATUS (no position)':24} -> {a!r}")
    if n or g or "STATUS KM38" not in a:
        p.append(f"no position: {a!r} asked {g}")

    a, n, g = await ask("STATUS KM", {"field_alerts": [{"cell": "KM38"}, {"cell": "KM46"}],
                                      "quakes": []})
    print(f"  {'STATUS KM (field)':24} -> {a!r}")
    if n or g != ["KM"] or "KM38, KM46" not in a:
        p.append(f"field: {a!r}")

    a, n, g = await ask("STATUS KM38", {"deaf": True})
    print(f"  {'STATUS KM38 (deaf)':24} -> {a!r}")
    if n or "unknown" not in a.lower():
        p.append(f"deaf: {a!r}")

    a, n, g = await ask("status of my order", ALERT)
    print(f"  {'status of my order':24} -> model asked {n} time(s)")
    if n != 1 or g:
        p.append("'status of my order' did not go to the model")

    # 8 - the provider itself
    async def fake_cells(db, path=""):
        return [{"cell": "KM38", "baseline": 31, "silent": 9, "alert": True,
                 "cause": "outage"},
                {"cell": "KM46", "baseline": 12, "silent": 6, "alert": True,
                 "cause": "outage"},
                {"cell": "KN41", "baseline": 8, "silent": 0, "alert": False,
                 "cause": ""}]
    real = web_gui.silence_cells_cached
    web_gui.silence_cells_cached = fake_cells
    try:
        now = time.time()
        mgr = types.SimpleNamespace(
            _station_db=types.SimpleNamespace(deaf_since=lambda: 0.0),
            _sta_db_path="", _silence_active={"KM38": SINCE},
            _quake_watches={
                "near": {"alert": "orange", "ts": now - 3600, "lat": 38.3,
                         "lon": 26.5, "mag": 6.1, "radius_km": 150.0,
                         "result": {"k": 5, "n": 30, "unusual": True}},
                "far": {"alert": "red", "ts": now - 3600, "lat": 14.0,
                        "lon": 120.0, "mag": 7.5, "radius_km": 300.0},
                "green": {"alert": "green", "ts": now - 3600, "lat": 38.4,
                          "lon": 27.0, "mag": 5.6, "radius_km": 150.0}})
        st = await web_gui.AgentManager._grid_status(mgr, "KM38")
        fld = await web_gui.AgentManager._grid_status(mgr, "KM")
    finally:
        web_gui.silence_cells_cached = real
    print(f"  {'_grid_status KM38':24} -> {st}")
    print(f"  {'_grid_status KM':24} -> field {fld.get('field_alerts')}")
    c = st.get("cell") or {}
    if c.get("silent") != 9 or c.get("since") != SINCE:
        p.append(f"_grid_status cell: {c}")
    if [round(q["mag"], 1) for q in st.get("quakes", [])] != [6.1]:
        p.append(f"_grid_status quakes: {st.get('quakes')}")
    if [x["cell"] for x in fld.get("field_alerts", [])] != ["KM38", "KM46"]:
        p.append(f"_grid_status field: {fld}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
