#!/usr/bin/env python3
"""Fail if /feed/silence.atom is not a valid Atom feed of the announced
silence alerts and PAGER yellow+ quake rings, or ignores its filters.

What must hold (the public app, driven in process):

  1. well-formed Atom (application/atom+xml), with self and alternate links
  2. an alerting cell is an entry only once announced (episode start known);
     its summary carries k of n, its link opens the map on the square
  3. quake rings PAGER yellow and above are entries, green ones are not;
     a counted ring says k of n and whether it is unusual
  4. ?grid=KM keeps that field's cells and only rings that reach it;
     a malformed grid is a 400
  5. ?lang=tr answers in Turkish
  6. while deaf: an entry saying so, no silence entries (quake rings stay)
  7. the map page advertises the feed and opens ?q=<locator>

Usage:  python tools/check_atom_feed.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import time
import types
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import web_gui  # noqa: E402

A = "{http://www.w3.org/2005/Atom}"
NOW = time.time()
CELLS = [
    {"cell": "KM38", "baseline": 31, "silent": 9, "alert": True, "cause": "outage"},
    {"cell": "KM46", "baseline": 12, "silent": 6, "alert": True, "cause": "outage"},
    {"cell": "FN31", "baseline": 40, "silent": 12, "alert": True, "cause": "outage"},
    {"cell": "KN41", "baseline": 8, "silent": 0, "alert": False, "cause": ""},
]
WATCHES = {
    "near": {"id": "us7000near", "alert": "orange", "ts": NOW - 3600, "lat": 38.3,
             "lon": 26.5, "mag": 6.1, "place": "Aegean Sea", "radius_km": 150.0,
             "result": {"k": 5, "n": 30, "unusual": True,
                        "measured_until": int(NOW - 600)}},
    "far": {"id": "us7000far", "alert": "red", "ts": NOW - 7200, "lat": 14.0,
            "lon": 120.0, "mag": 7.5, "place": "Luzon", "radius_km": 300.0},
    "green": {"id": "us7000green", "alert": "green", "ts": NOW - 3600, "lat": 38.4,
              "lon": 27.0, "mag": 5.6, "place": "Izmir", "radius_km": 150.0},
}


def manager(deaf=0.0):
    return types.SimpleNamespace(
        get_config=lambda: {"public_base_url": "https://map.example.org/"},
        _station_db=types.SimpleNamespace(deaf_since=lambda: deaf),
        _sta_db_path="",
        # KM46 alerts but is not announced yet: no episode start
        _silence_active={"KM38": NOW - 1800, "FN31": NOW - 900},
        _quake_watches=WATCHES)


async def fetch(c, qs=""):
    r = await c.get("/feed/silence.atom" + qs)
    return r.status, r.headers.get("Content-Type", ""), await r.text()


def entries(text):
    root = ET.fromstring(text)
    out = []
    for e in root.findall(A + "entry"):
        out.append({k: (e.findtext(A + k) or "") for k in ("id", "title", "summary")}
                   | {"link": e.find(A + "link").get("href")})
    return root, out


async def main() -> int:
    p = []

    async def fake_cells(db, path=""):
        return [dict(c) for c in CELLS]
    web_gui.silence_cells_cached = fake_cells

    async with TestClient(TestServer(web_gui._build_public_app(manager()))) as c:
        st, ct, text = await fetch(c)
        try:
            root, es = entries(text)
        except ET.ParseError as e:
            print("not XML:", e)
            return 1
        titles = [e["title"] for e in es]
        print(f"  all: {st} {ct.split(';')[0]} -> {titles}")
        if st != 200 or "application/atom+xml" not in ct:
            p.append(f"status/content-type {st} {ct}")
        rels = {l.get("rel") for l in root.findall(A + "link")}
        if not {"self", "alternate"} <= rels or not root.findtext(A + "updated"):
            p.append(f"feed links/updated missing: {rels}")
        km38 = next((e for e in es if e["title"].startswith("KM38")), None)
        if not km38 or "9 of 31" not in km38["summary"] \
                or km38["link"] != "https://map.example.org/?q=KM38":
            p.append(f"KM38 entry: {km38}")
        if any(e["title"].startswith("KM46") for e in es):
            p.append("an alert not yet announced is in the feed")
        if any("Izmir" in e["title"] for e in es):
            p.append("a green PAGER quake is in the feed")
        near = next((e for e in es if "Aegean" in e["title"]), None)
        if not near or "5 of 30" not in near["summary"] or "(unusual)" not in near["summary"]:
            p.append(f"near quake entry: {near}")
        far = next((e for e in es if "Luzon" in e["title"]), None)
        if not far or "Not counted" not in far["summary"]:
            p.append(f"uncounted quake entry: {far}")

        st, ct, text = await fetch(c, "?grid=KM")
        _, es = entries(text)
        titles = [e["title"] for e in es]
        print(f"  grid=KM -> {titles}")
        if any(t.startswith("FN31") or "Luzon" in t for t in titles) \
                or not any(t.startswith("KM38") for t in titles) \
                or not any("Aegean" in t for t in titles):
            p.append(f"grid filter: {titles}")
        st, _, _ = await fetch(c, "?grid=KM38,ZZ")
        if st != 400:
            p.append(f"malformed grid gave {st}")

        st, ct, text = await fetch(c, "?lang=tr&grid=KM38")
        _, es = entries(text)
        print(f"  lang=tr -> {[e['title'] for e in es]}")
        if not any("bölgesel sessizlik" in e["title"] for e in es):
            p.append("lang=tr not Turkish")

    async with TestClient(TestServer(web_gui._build_public_app(manager(deaf=NOW - 700)))) as c:
        st, ct, text = await fetch(c)
        _, es = entries(text)
        print(f"  deaf -> {[e['title'] for e in es]}")
        # quake rings come from USGS and stay; silence is not judged
        if not any("not hearing" in e["title"] for e in es) \
                or any("regional silence" in e["title"] for e in es):
            p.append(f"deaf feed: {[e['title'] for e in es]}")

    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if 'type="application/atom+xml"' not in page or "get('q')" not in page:
        p.append("map page lacks the feed link or the ?q= handler")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
