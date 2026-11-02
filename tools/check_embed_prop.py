#!/usr/bin/env python3
"""Fail if /embed/prop is not a self-contained card of the propagation
openings stored near a square in the last week.

Asked for because a QRZ.com biography runs no script: a link to
/feed/prop.atom there shows nothing, the card shows the openings. What must
hold (the public app, driven in process, over a temporary history table):

  1. the openings of the last 7 days with an end within 400 km of the
     square, newest first, at most four rows, the count of all of them;
     one far away and one older than the week are left out
  2. one pair of links stored as several openings in a day is one row
     (the feed lists each; the rules that store them stay frozen)
  3. each row gives the time, longest link and senders and links to the map
     on the square of the longest link's midpoint, in a new tab
  4. ?grid=KM counts the field's openings; a far square says there are none
  5. ?lang=tr answers in Turkish; while deaf the card says so and the stored
     openings stay
  8. the head and the title name the band, VHF/UHF: "propagation" alone
     reads as HF to an amateur
  9. the top line links to the card builder filled in for this card
  6. the foot links to the feed for the same grid; the page refreshes
     itself, loads nothing from another host, no header forbids framing
  7. a malformed grid is a 400; no history table yet is an empty card

Usage:  python tools/check_embed_prop.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402

NOW = int(time.time())


def link(call, gate, km, s, g):
    return {"ts": NOW, "call": call, "gate": gate, "km": km,
            "s_lat": s[0], "s_lon": s[1], "g_lat": g[0], "g_lon": g[1],
            "suspect": ""}


def same_day(ts, dt):
    """ts + dt, or ts - dt when that would cross midnight UTC."""
    return ts + dt if time.gmtime(ts + dt).tm_yday == time.gmtime(ts).tm_yday \
        else ts - dt


IZMIR, ANTALYA = (38.4, 27.1), (36.9, 30.7)
# Anonymised calls. Five distinct openings near KM38, the newest first.
NEAR = [{"ts": NOW - 3600 * (i + 1) * 5, "region": "KM", "note": "",
         "links": [link("TA1A%s" % c, "TA2GW-10", 300.0 + 10 * i, IZMIR, ANTALYA),
                   link("TA3B%s" % c, "TA2GW-10", 280.0, (38.5, 27.0), ANTALYA)]}
        for i, c in enumerate("ABCDE")]
# The newest stored again 20 minutes apart the same day: one row.
DUP = dict(NEAR[0], ts=same_day(NEAR[0]["ts"], -1200))
FAR = {"ts": NOW - 1800, "region": "FN", "note": "",
       "links": [link("W1AAA", "K2GW", 260.0, (41.0, -74.0), (42.9, -71.5)),
                 link("W1BBB", "K2GW", 250.0, (41.1, -74.1), (42.9, -71.5))]}
OLD = dict(NEAR[1], ts=NOW - 8 * 86400)


def manager(path, deaf=0.0):
    return types.SimpleNamespace(
        get_config=lambda: {"public_base_url": "https://map.example.org/"},
        _station_db=types.SimpleNamespace(deaf_since=lambda: deaf),
        _sta_db_path=path)


async def page(path, qs, deaf=0.0):
    async with TestClient(TestServer(
            web_gui._build_public_app(manager(path, deaf)))) as c:
        r = await c.get("/embed/prop" + qs)
        return r.status, dict(r.headers), await r.text()


def text(h):
    h = re.sub(r"<style>.*?</style>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


def rows(h):
    return re.findall(r'<a class="r" href="([^"]+)"[^>]*>([^<]+)</a>', h)


async def main() -> int:
    p = []
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "t.sqlite")
        for ev in NEAR + [DUP, FAR, OLD]:
            station_db_module.record_prop_event(path, ev)

        st, hd, h = await page(path, "?grid=KM38")
        t, rs = text(h), rows(h)
        print(f"  KM38: {st} -> {t[:200]!r}")
        for r in rs:
            print(f"        {r}")
        if st != 200:
            print(h[:300])
            return 1
        if '<span class="dot"></span>VHF/UHF openings</div>' not in h or \
                "<title>KM38 · VHF/UHF propagation openings</title>" not in h:
            p.append("the head or the title does not name the band, VHF/UHF")
        if 'href="https://map.example.org/embed/?grid=KM38&amp;card=prop&amp;theme=auto"' \
                not in h:
            p.append("no link to the builder for this card")
        if "5 within 400 km in 7 days" not in t:
            p.append("count of the week's openings near KM38 (far, old and the "
                     "repeat must be left out)")
        if len(rs) != 4:
            p.append(f"{len(rs)} rows, expected the newest four")
        elif [r[1].split(" · ")[1] for r in rs] != \
                ["300 km, 2 senders", "310 km, 2 senders", "320 km, 2 senders",
                 "330 km, 2 senders"]:
            p.append(f"rows not newest first, or the repeat shown twice: {rs}")
        tm = time.gmtime(NEAR[0]["ts"])
        want = "%d %s %02d:%02d" % (tm.tm_mday, time.strftime("%b", tm),
                                    tm.tm_hour, tm.tm_min)
        if rs and not rs[0][1].startswith(want):
            p.append(f"first row's time {rs[0][1]!r}, expected {want}")
        if rs and rs[0][0] != "https://map.example.org/?q=KM47":
            p.append(f"row link {rs[0][0]}, expected the midpoint square KM47")
        if 'target="_blank"' not in h:
            p.append("rows do not open in a new tab")
        if 'href="https://map.example.org/feed/prop.atom?grid=KM38"' not in h:
            p.append("foot does not link to the feed for KM38")
        if 'http-equiv="refresh"' not in h:
            p.append("no self-refresh")
        if re.search(r'(src|href)="https?://(?!map\.example\.org/)', h):
            p.append("loads or links another host")
        if re.search(r"<(script|link)\b", h):
            p.append("carries a script or an external stylesheet")
        if any(k.lower() == "x-frame-options" for k in hd) or \
                "frame-ancestors" in hd.get("Content-Security-Policy", ""):
            p.append("a header forbids framing")

        st, _, h = await page(path, "?grid=KM")
        print(f"  KM  : {text(h)[60:140]!r}")
        if "5 in this field in 7 days" not in text(h):
            p.append("field KM")
        st, _, h = await page(path, "?grid=PM95")
        if "No openings within 400 km in 7 days" not in text(h) or rows(h):
            p.append("a far square must show none")

        st, _, h = await page(path, "?grid=km38nk&lang=tr")
        t = text(h)
        print(f"  tr  : {t[60:200]!r}")
        if 'embed/?grid=KM38&amp;card=prop&amp;lang=tr&amp;theme=auto"' not in h:
            p.append("the builder link drops the language")
        if "VHF/UHF açılımları" not in t or "7 günde ucu 400 km içinde 5 açılım" not in t \
                or "gönderen" not in t or "lang=tr" not in h:
            p.append("lang=tr not Turkish")

        st, _, h = await page(path, "?grid=KM38", deaf=NOW - 700)
        if "not hearing APRS-IS" not in text(h) or len(rows(h)) != 4:
            p.append("deaf: must say so and keep the stored openings")

        st, _, _ = await page(path, "?grid=ZZ99")
        if st != 400:
            p.append(f"malformed grid gave {st}")
        st, _, h = await page(str(Path(d) / "none.sqlite"), "?grid=KM38")
        if st != 200 or rows(h):
            p.append(f"no history table: {st}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
