#!/usr/bin/env python3
"""Fail if DMWGPT's delivery tally is wrong: how many parts of each fresh
answer the recipient's station acknowledged.

What must hold (gateway driven in process, resend gaps shortened):

  1. a two-part answer with both parts acked is recorded as (2, 2)
  2. one acked, one given up on after the resends: (2, 1)
  3. a replay of a cached answer is not a new answer and is not recorded
  4. AgentManager keeps per-day [answers, fully acked, parts, parts acked],
     persists them in meta, and /api/counters sums the last 30 days

Usage:  python tools/check_delivery.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.ai_gateway_ext as aig  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402
import station_db  # noqa: E402
import web_gui  # noqa: E402

aig._RF_TURNAROUND_S = 0.0
aig._PART_GAP_S = 0.05
aig._RETRY_GAPS_S = (0.2, 0.2, 0.2)

CFG = {"enabled": True, "callsign": "DMWGPT", "provider": "deepseek",
       "api_keys": {"deepseek": "stub"}, "extra_sms": 2,
       "rate_burst": 0, "rate_refill_s": 0}
LONG = ("An answer long enough to need two APRS message parts, so the second "
        "part follows the first after a short gap.")


def gateway(sent, recorded):
    class Q:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8").strip())
    gw = AIGateway(dict(CFG), str(Path(tempfile.mkdtemp()) / "aprsconfig.toml"))
    gw._own_writer = Q()
    gw.set_delivery_recorder(lambda n, a: recorded.append((n, a)))

    async def stub(question, sender="", history=None):
        return LONG
    gw._ask_ai = stub
    return gw


def mids(sent, call):
    return [s.rsplit("{", 1)[1] for s in sent
            if "::" + call in s and ":ack" not in s and "{" in s]


async def main() -> int:
    p = []
    # 1 - both acked
    sent, rec = [], []
    gw = gateway(sent, rec)
    await gw.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :question one{1")
    await asyncio.sleep(0.15)
    for m in mids(sent, "TA1ABC-7"):
        await gw.handle(f"TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :ack{m}")
    await asyncio.sleep(0.1)
    print(f"  both acked     -> {rec}")
    if rec != [(2, 2)]:
        p.append(f"both acked recorded {rec}")

    # 2 - one acked, one exhausted
    sent, rec = [], []
    gw = gateway(sent, rec)
    await gw.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :question two{2")
    await asyncio.sleep(0.15)
    first = mids(sent, "TA1ABC-7")[0]
    await gw.handle(f"TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :ack{first}")
    await asyncio.sleep(1.0)
    print(f"  one of two     -> {rec}")
    if rec != [(2, 1)]:
        p.append(f"one acked recorded {rec}")

    # 3 - a replay (same question again after it was answered) is not counted
    sent, rec = [], []
    gw = gateway(sent, rec)
    await gw.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :question three{3")
    await asyncio.sleep(0.15)
    for m in mids(sent, "TA1ABC-7"):
        await gw.handle(f"TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :ack{m}")
    aig._clock_saved = aig._clock
    aig._clock = lambda: time.time() + 60          # past the replay minimum age
    await gw.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::DMWGPT   :question three{3")
    aig._clock = aig._clock_saved
    await asyncio.sleep(1.0)
    print(f"  with a replay  -> {rec}")
    if rec != [(2, 2)]:
        p.append(f"a replay changed the tally: {rec}")

    # 4 - the manager's daily counts, meta, and the counters endpoint
    db_path = str(Path(tempfile.mkdtemp()) / "aprs_stations.db")
    mgr = types.SimpleNamespace(_delivery={}, _sta_db_path=db_path)
    web_gui.AgentManager._record_delivery(mgr, 2, 2)
    web_gui.AgentManager._record_delivery(mgr, 3, 1)
    web_gui.AgentManager._record_delivery(mgr, 1, 1)
    old = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 40 * 86400))
    mgr._delivery[old] = [50, 10, 60, 20]          # outside the 30 days
    summ = web_gui.AgentManager._delivery_summary(mgr, 30)
    stored = json.loads(station_db.load_meta(db_path, "gateway_delivery", "{}"))
    print(f"  summary        -> {summ}")
    if (summ["answers"], summ["acked"], summ["parts"], summ["parts_acked"]) != (3, 2, 6, 4):
        p.append(f"summary {summ}")
    if sum(v[0] for v in stored.values()) != 3:
        p.append(f"meta not persisted: {stored}")
    if "gateway_delivery" not in Path(web_gui.__file__).read_text(encoding="utf-8").split(
            "async def counters", 1)[1].split("@routes", 1)[0]:
        p.append("/api/counters does not carry gateway_delivery")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
