#!/usr/bin/env python3
"""Fail if a page of the public app outside the map ignores the aprsagent.com
family's theme rule.

Seen live 2026-11-02: from aprsagent.com in its light theme, the "status
card" link opened the card builder dark - the builder and the 404 page took
the device's dark setting, which the family does not read. The rule (site
standard 1.3, as the map page keeps it):

  1. light unless the visitor chose dark: the page sets data-theme before
     first paint from localStorage "theme" (the map's own key), and nothing
     reads prefers-color-scheme
  2. the dark colours apply under :root[data-theme="dark"] only
  3. the builder has the family's theme button, which stores the choice;
     the 404 page follows the choice without a button, as aprsagent.com's

The embed cards are not checked here: without ?theme= they follow the
reader's device on purpose, an option the builder offers.

Usage:  python tools/check_family_theme.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import web_gui  # noqa: E402

HEAD = re.compile(
    r'<script>\(function\(\)\{var t=null;try\{t=localStorage\.getItem\("theme"\)\}'
    r'catch\(e\)\{\}document\.documentElement\.dataset\.theme=t==="dark"\?"dark":"light";')


def manager():
    return types.SimpleNamespace(
        get_config=lambda: {"public_base_url": "https://map.example.org/"})


async def main() -> int:
    p = []
    async with TestClient(TestServer(web_gui._build_public_app(manager()))) as c:
        pages = {}
        for name, path in (("builder", "/embed/"), ("builder with a square", "/embed/?grid=KM38"),
                           ("404", "/no-such-page")):
            r = await c.get(path, headers={"Accept": "text/html"})
            pages[name] = h = await r.text()
            print(f"  {path} -> {r.status}")
            if "prefers-color-scheme" in h:
                p.append(f"{name}: reads the device's dark setting")
            m = HEAD.search(h)
            if not m or m.start() > h.find("<body"):
                p.append(f"{name}: no first-paint theme from localStorage \"theme\"")
            if ':root[data-theme="dark"]{--bg:#1b1a16' not in h:
                p.append(f"{name}: dark colours not under :root[data-theme=\"dark\"]")
        for name in ("builder", "builder with a square"):
            h = pages[name]
            if not re.search(r'<button class="thm" type="button" data-thm', h) or \
                    'localStorage.setItem("theme",n)' not in h:
                p.append(f"{name}: no theme button that stores the choice")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
