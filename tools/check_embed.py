#!/usr/bin/env python3
"""Fail if /embed/status is not a self-contained, embeddable card of a
square's silence state, nearby quake ring and propagation openings.

What must hold (the public app, driven in process):

  1. a quiet square: "All on the air" and its station count; an alerting one:
     "Regional silence" with its start; igate-caused: "Igate fault"
  2. Turkish with ?lang=tr; a field (?grid=KM) lists its alerting squares
  3. a quake ring reaching the square is shown with its count
  4. propagation: links with an end within 400 km in the last 3 h are counted,
     suspect, old and far links are not
  5. a deaf feed says the status is unknown
  6. the page links to /?q=<square>, refreshes itself, loads nothing from
     another host, and the app sends no header that forbids framing
  7. a malformed grid is a 400

Usage:  python tools/check_embed.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import web_gui  # noqa: E402

NOW = time.time()
LINKS = [
    # near KM38 (Izmir), recent: counted
    {"ts": NOW - 600, "km": 812.0, "s_lat": 38.4, "s_lon": 27.1, "g_lat": 41.0, "g_lon": 35.0},
    {"ts": NOW - 900, "km": 455.0, "s_lat": 37.0, "s_lon": 30.0, "g_lat": 38.5, "g_lon": 27.2},
    # suspect, old, far: not counted
    {"ts": NOW - 300, "km": 2900.0, "suspect": True, "s_lat": 38.4, "s_lon": 27.1, "g_lat": 45, "g_lon": 50},
    {"ts": NOW - 5 * 3600, "km": 990.0, "s_lat": 38.4, "s_lon": 27.1, "g_lat": 45, "g_lon": 30},
    {"ts": NOW - 300, "km": 700.0, "s_lat": 50.0, "s_lon": 5.0, "g_lat": 52.0, "g_lon": 10.0},
]


def manager(status):
    async def grid_status(grid):
        return status(grid) if callable(status) else status
    return types.SimpleNamespace(
        get_config=lambda: {"public_base_url": "https://map.example.org/"},
        _grid_status=grid_status,
        _station_db=types.SimpleNamespace(prop_summary=lambda n=200: {"links": LINKS}))


async def page(status, qs):
    async with TestClient(TestServer(web_gui._build_public_app(manager(status)))) as c:
        r = await c.get("/embed/status" + qs)
        return r.status, dict(r.headers), await r.text()


def text(html_):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html_))


async def main() -> int:
    p = []
    quiet = {"cell": {"baseline": 31, "silent": 0, "alert": False, "cause": ""},
             "quakes": [{"mag": 6.1, "km": 48.0, "hours": 1.0, "measured": True,
                         "k": 5, "n": 30, "unusual": True}]}
    st, hd, h = await page(quiet, "?grid=KM38")
    t = text(h)
    print(f"  quiet KM38: {st} -> {t[:220]!r}")
    if st != 200 or "All on the air" not in t or "31 fixed stations · 0 quiet" not in t:
        p.append("quiet square")
    if "M6.1 quake 48 km away" not in t or "5 of 30 stations quiet (unusual)" not in t:
        p.append("quake line")
    if "2 propagation opening(s) nearby in 3 h, longest 812 km" not in t:
        p.append("propagation count (suspect/old/far must be left out)")
    if 'href="https://map.example.org/?q=KM38"' not in h:
        p.append("map link")
    if 'http-equiv="refresh"' not in h:
        p.append("no self-refresh")
    if re.search(r'(src|href)="https?://(?!map\.example\.org)', h.replace(
            'href="https://map.example.org/', "")):
        p.append("loads or links another host")
    if re.search(r'<(script|link)[^>]+(src|href)=', h):
        p.append("loads an external script or stylesheet")
    if any(k.lower() in ("x-frame-options",) for k in hd) or \
            "frame-ancestors" in hd.get("Content-Security-Policy", ""):
        p.append("a header forbids framing")

    alert = {"cell": {"baseline": 31, "silent": 9, "alert": True, "cause": "outage",
                      "since": 1792000000}, "quakes": []}
    st, _, h = await page(alert, "?grid=km38nk&lang=tr")
    t = text(h)
    print(f"  alert tr  : {st} -> {t[:160]!r}")
    if "Bölgesel sessizlik" not in t or "31 sabit istasyon · 9 sessiz" not in t \
            or time.strftime("%H:%M UTC", time.gmtime(1792000000)) not in t:
        p.append("alerting square, Turkish")

    igate = {"cell": {"baseline": 20, "silent": 6, "alert": True, "cause": "igate"}}
    st, _, h = await page(igate, "?grid=KM38")
    if "Igate fault" not in text(h):
        p.append("igate cause")

    fld = {"field_alerts": [{"cell": "KM38"}, {"cell": "KM46"}], "quakes": []}
    st, _, h = await page(fld, "?grid=KM")
    print(f"  field KM  : {st} -> {text(h)[:120]!r}")
    if "Regional silence in 2 square(s): KM38, KM46" not in text(h):
        p.append("field")

    st, _, h = await page({"deaf": True}, "?grid=KM38")
    if "Status unknown" not in text(h):
        p.append("deaf")

    st, _, h = await page(quiet, "?grid=KM38&theme=dark")
    if 'data-theme="dark"' not in h:
        p.append("theme=dark")

    some = {"cell": {"baseline": 29, "silent": 3, "alert": False, "cause": ""}}
    st, _, h = await page(some, "?grid=KM38")
    if "No regional silence" not in text(h) or "All on the air" in text(h):
        p.append("a few quiet stations without an alert must not read 'All on the air'")

    st, _, _ = await page(quiet, "?grid=ZZ99")
    if st != 400:
        p.append(f"malformed grid gave {st}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
