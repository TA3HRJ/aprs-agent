#!/usr/bin/env python3
"""Fail if the gateway refuses what its own registry can answer, or explains
a refusal with a reason that is not the true one.

2026-09-20, KE4PIC, an hour after the service was announced:

    16:01  de Frank EM97xe
    16:04  what is my distance to fairfax, va
    16:04  No live position data, so I cannot calculate that.
    16:09  what is my nearest igate
    16:09  I have no live station or igate data.

Both refusals were untrue. His position was in the registry - the map was
drawing him at that moment - and the registry classifies igates and records
which one gated each station. What was missing was a place-name lookup, which
the gateway genuinely does not have and never claimed not to have.

KR4MVP-5 had asked "Propagation near me" the same afternoon and been sent to
hamqsl.com by a program that keeps a list of the propagation openings it has
just measured.

So: infrastructure questions are answered from the registry; a third party's
position is answered the way the map already shows it, unless that station has
asked to be left out; and each refusal names its own reason - no data, no
place names, or not allowed.

No network and no provider: the registry and the model are stubbed.

Usage:  python tools/check_lookup.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 0,          # limiter off: this is about answers
    "rate_refill_s": 0,
}

MODEL = "Model answer."
NOW = time.time()

# KE4PIC in Georgia, an igate 18 km away, another station 341 km off
STATIONS = {
    "KE4PIC": {"callsign": "KE4PIC", "lat": 33.95, "lon": -83.99,
               "locator": "EM84va", "last_seen_ago_s": 40,
               "last_gate": "", "type": "walker"},
    "W4ABC-10": {"callsign": "W4ABC-10", "lat": 34.05, "lon": -84.12,
                 "locator": "EM84ub", "last_seen_ago_s": 120,
                 "last_gate": "", "type": "igate"},
    "W1ABC-9": {"callsign": "W1ABC-9", "lat": 36.9, "lon": -84.2,
                "locator": "EM76ux", "last_seen_ago_s": 300,
                "last_gate": "W4ABC-10", "type": "car"},
}


class FakeDB:
    def get_one(self, call):
        return dict(STATIONS.get(call.upper(), {})) or None

    def nearest_of_type(self, lat, lon, kinds, max_km=250.0, limit=3):
        if "igate" not in kinds and "gateway" not in kinds:
            return []
        return [(dict(STATIONS["W4ABC-10"]), 18.4)]

    def has_gated(self, call):
        return call.upper() == "W4ABC-10"

    def nearest_wx(self, lat, lon, radius):
        return None

    def prop_summary(self, max_links=200):
        return {"links": [
            # 612 km, one end 30 km from KE4PIC, eight minutes ago
            {"ts": NOW - 480, "call": "N4XYZ-7", "gate": "W4ABC-10",
             "km": 612.4, "s_lat": 39.3, "s_lon": -84.4,
             "g_lat": 34.1, "g_lon": -84.0},
            # far away, must not be reported as near
            {"ts": NOW - 300, "call": "VK2ZZZ", "gate": "VK2AAA",
             "km": 980.0, "s_lat": -33.8, "s_lon": 151.2,
             "g_lat": -35.3, "g_lon": 149.1},
        ]}


def line(sender: str, text: str, path: str = "APDR16,TCPIP*,qAR,W4ABC-10"):
    return "%s>%s::DMWGPT   :%s" % (sender, path, text)


def new_gateway(sent: list, calls: dict, tmp: Path):
    class Queue:
        async def put(self, b: bytes) -> None:
            sent.append(b.decode("utf-8", "replace").strip())

    gw = AIGateway(dict(CFG), str(tmp / "aprsconfig.toml"))
    gw._own_writer = Queue()
    gw.set_station_db(FakeDB())

    async def stub(question: str, sender: str = "", history=None) -> str:
        calls["n"] += 1
        return MODEL

    gw._ask_ai = stub
    return gw


async def ask(gw, sent: list, sender: str, text: str, path: str = "APDR16,TCPIP*,qAR,W4ABC-10") -> str:
    before = len(sent)
    await gw.handle(line(sender, text, path))
    out = []
    for s in sent[before:]:
        body = s.split("::", 1)[1][9:].lstrip(":")
        if body.startswith(("ack", "rej")):
            continue
        out.append(body.rsplit("{", 1)[0].replace(" --", "").strip())
    return " ".join(out)


async def run() -> int:
    problems = []
    tmp = Path(__file__).resolve().parent.parent / ".check_lookup_tmp"
    tmp.mkdir(exist_ok=True)
    for f in tmp.iterdir():
        f.unlink()

    # 1 - the nearest igate, from the registry
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "what is my nearest igate")
    if "W4ABC-10" not in a:
        problems.append("nearest igate not named: %r" % a[:80])
    if "18" not in a:
        problems.append("nearest igate has no distance: %r" % a[:80])
    if calls["n"]:
        problems.append("the nearest-igate question cost a model call")

    # 2 - which igate is hearing me, from the packet itself
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "which igate hears me")
    if "W4ABC-10" not in a:
        problems.append("the igate from the packet path is not named: %r" % a[:80])
    if calls["n"]:
        problems.append("the which-igate question cost a model call")

    # 3 - ... and a sender who is on the internet is told so
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "which igate hears me",
                  path="APDR16,TCPIP*,qAC,T2CHILE")
    if "igate" not in a.lower() or "internet" not in a.lower():
        problems.append("an internet-connected sender was not told no igate "
                        "is hearing them: %r" % a[:80])

    # 4 - a third party's position, as the map already shows it
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "where is W1ABC-9")
    if "36.9" not in a and "EM76" not in a.upper():
        problems.append("a third party's public position was refused: %r" % a[:80])
    if "km" not in a.lower():
        problems.append("no distance from the asker: %r" % a[:80])
    if calls["n"]:
        problems.append("a registry lookup cost a model call")

    # 5 - unless that station asked to be left out, and the refusal says why
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "W1ABC-9", "NOLOOKUP")
    if not a or "lookup" not in a.lower():
        problems.append("NOLOOKUP was not confirmed: %r" % a[:80])
    b = await ask(gw, sent, "KE4PIC", "where is W1ABC-9")
    if "36.9" in b or "EM76" in b.upper():
        problems.append("an opted-out station was still located: %r" % b[:80])
    if "asked" not in b.lower() and "opted" not in b.lower():
        problems.append("the refusal does not say the station opted out: %r" % b[:80])
    # and it survives a restart
    gw2 = new_gateway(sent, {"n": 0}, tmp)
    c = await ask(gw2, sent, "KE4PIC", "where is W1ABC-9")
    if "36.9" in c or "EM76" in c.upper():
        problems.append("the opt-out was forgotten on restart: %r" % c[:80])
    d = await ask(gw2, sent, "W1ABC-9", "LOOKUP")
    if not d or "lookup" not in d.lower():
        problems.append("LOOKUP was not confirmed: %r" % d[:80])
    # a different wording, or the dedup cache would simply replay the
    # refusal above and prove nothing
    e = await ask(gw2, sent, "KE4PIC", "where is W1ABC-9 now")
    if "36.9" not in e and "EM76" not in e.upper():
        problems.append("opting back in did not restore the lookup: %r" % e[:80])

    # 6 - a place name is refused for the right reason
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "what is my distance to fairfax, va")
    low = a.lower()
    if "place name" not in low and "yer ad" not in low:
        problems.append("the place-name refusal does not say what is missing: "
                        "%r" % a[:80])
    if "no live position" in low or "no position" in low:
        problems.append("the refusal still claims to have no position for a "
                        "station it can see: %r" % a[:80])

    # 7 - propagation near me, from the openings just measured
    sent, calls = [], {"n": 0}
    gw = new_gateway(sent, calls, tmp)
    a = await ask(gw, sent, "KE4PIC", "Propagation near me")
    if "612" not in a:
        problems.append("a measured opening 30km away was not reported: %r" % a[:80])
    if "VK2" in a:
        problems.append("an opening on the other side of the world was "
                        "reported as near: %r" % a[:80])
    if calls["n"]:
        problems.append("the propagation question cost a model call")

    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()

    for p in problems:
        print("FAIL: " + p)
    print("checked 7 cases - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
