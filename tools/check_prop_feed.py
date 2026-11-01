#!/usr/bin/env python3
"""Fail if /feed/prop.atom is not a valid Atom feed of the stored propagation
openings, or ignores its filters.

Asked for as a subscription (NEXT 6). A feed reader polls it, so nothing goes
out on the air. What must hold (the public app, driven in process, over a
temporary history table):

  1. well-formed Atom (application/atom+xml), with self and alternate links
  2. one entry per stored opening of the last 7 days, an older one left out;
     the title names the field, the distinct senders and the longest link
  3. the summary lists the links longest first, at most five and "+N more",
     and labels the AI reading as automated
  4. the entry links to the map on the square of the longest link's midpoint
  5. ?grid=KM keeps openings with an end in that field; ?grid=KM38 those with
     an end within 400 km of the square; a far square gives none; a
     malformed grid is a 400
  6. ?lang=tr answers in Turkish
  7. while deaf: an entry saying so, and the stored openings stay
  8. the public app serves it, the map page and llms.txt advertise it

Usage:  python tools/check_prop_feed.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
import types
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import station_db as station_db_module  # noqa: E402
import web_gui  # noqa: E402

A = "{http://www.w3.org/2005/Atom}"
NOW = int(time.time())


def link(call, gate, km, s, g):
    return {"ts": NOW, "call": call, "gate": gate, "km": km,
            "s_lat": s[0], "s_lon": s[1], "g_lat": g[0], "g_lon": g[1],
            "suspect": ""}


# Anonymised calls. Izmir -> Antalya, two senders: field KM.
KM_EV = {"ts": NOW - 3600, "region": "KM",
         "note": "[tropo/medium] Two long links at night.",
         "links": [link("TA1AAA-9", "TA2BBB-10", 281.0, (38.4, 27.1), (36.9, 30.7)),
                   link("TA3CCC", "TA2BBB-10", 330.4, (38.5, 27.0), (36.9, 30.7))]}
# Seven links over the eastern US: "+2 more".
FN_EV = {"ts": NOW - 7200, "region": "FN", "note": "",
         "links": [link("W1A%s" % c, "K2GATE", 260.0 + i, (41.0, -74.0), (42.9, -71.5))
                   for i, c in enumerate("ABCDEFG")]}
# Eight days old: outside the feed's week.
OLD_EV = {"ts": NOW - 8 * 86400, "region": "JN", "note": "",
          "links": [link("OE1AAA", "OK1GATE", 270.0, (48.2, 16.4), (50.1, 14.4)),
                    link("OE3BBB", "OK1GATE", 280.0, (48.3, 16.0), (50.1, 14.4))]}


def manager(path, deaf=0.0):
    return types.SimpleNamespace(
        get_config=lambda: {"public_base_url": "https://map.example.org/"},
        _station_db=types.SimpleNamespace(deaf_since=lambda: deaf),
        _sta_db_path=path)


async def fetch(c, qs=""):
    r = await c.get("/feed/prop.atom" + qs)
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
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "t.sqlite")
        for ev in (KM_EV, FN_EV, OLD_EV):
            station_db_module.record_prop_event(path, ev)

        async with TestClient(TestServer(web_gui._build_public_app(manager(path)))) as c:
            st, ct, text = await fetch(c)
            if st != 200:
                print(f"status {st}: {text[:200]}")
                return 1
            try:
                root, es = entries(text)
            except ET.ParseError as e:
                print("not XML:", e)
                return 1
            titles = [e["title"] for e in es]
            print(f"  all: {st} {ct.split(';')[0]} -> {titles}")
            if "application/atom+xml" not in ct:
                p.append(f"content-type {ct}")
            rels = {l.get("rel") for l in root.findall(A + "link")}
            if not {"self", "alternate"} <= rels or not root.findtext(A + "updated"):
                p.append(f"feed links/updated missing: {rels}")
            if len(es) != 2 or any(" JN" in t for t in titles):
                p.append(f"expected the two openings of the last week: {titles}")
            km = next((e for e in es if " KM" in e["title"]), None)
            if not km or "2 senders" not in km["title"] or "longest 330 km" not in km["title"]:
                p.append(f"KM title: {km and km['title']}")
            elif not km["summary"].startswith("TA3CCC → TA2BBB-10 330 km; TA1AAA-9"):
                p.append(f"KM links not longest first: {km['summary']}")
            elif "AI reading (automated): [tropo/medium]" not in km["summary"]:
                p.append(f"KM AI note not labelled: {km['summary']}")
            if km and km["link"] != "https://map.example.org/?q=KM47":
                p.append(f"KM link {km['link']}, expected the midpoint square KM47")
            fn = next((e for e in es if " FN" in e["title"]), None)
            if not fn or "(+2 more)" not in fn["summary"] or "7 senders" not in fn["title"]:
                p.append(f"FN entry: {fn}")
            elif "AI reading" in fn["summary"]:
                p.append("an opening without a note claims an AI reading")

            for qs, want in (("?grid=KM", [" KM"]), ("?grid=KM38", [" KM"]),
                             ("?grid=FN,KM", [" KM", " FN"]), ("?grid=PM95", [])):
                st, _, text = await fetch(c, qs)
                got = [e["title"] for e in entries(text)[1]]
                print(f"  {qs} -> {got}")
                if st != 200 or sorted(w for w in want if any(w in t for t in got)) \
                        != sorted(want) or len(got) != len(want):
                    p.append(f"{qs}: {got}")
            st, _, _ = await fetch(c, "?grid=KM38,ZZ")
            if st != 400:
                p.append(f"malformed grid gave {st}")

            st, _, text = await fetch(c, "?lang=tr&grid=KM")
            got = [e for e in entries(text)[1]]
            print(f"  lang=tr -> {[e['title'] for e in got]}")
            if not got or "üzerinde yayılım açılımı" not in got[0]["title"] \
                    or "otomatik" not in got[0]["summary"]:
                p.append(f"lang=tr not Turkish: {got}")

            r = await c.get("/llms.txt")
            if "feed/prop.atom" not in await r.text():
                p.append("llms.txt does not list the feed")

        async with TestClient(TestServer(
                web_gui._build_public_app(manager(path, deaf=NOW - 700)))) as c:
            st, _, text = await fetch(c)
            got = [e["title"] for e in entries(text)[1]]
            print(f"  deaf -> {got}")
            if not any("not hearing" in t for t in got) or len(got) != 3:
                p.append(f"deaf feed: {got}")

        async with TestClient(TestServer(
                web_gui._build_public_app(manager(str(Path(d) / "none.sqlite"))))) as c:
            st, _, text = await fetch(c)
            if st != 200 or entries(text)[1]:
                p.append(f"no history table: {st}")

    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if 'href="/feed/prop.atom"' not in page:
        p.append("map page does not advertise the feed")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
