#!/usr/bin/env python3
"""Fail if /embed/ does not hand a visitor the iframe code for cards of their
own square.

Asked for so that someone who sees the cards on a QRZ.com biography can put
them on their own page. What must hold (the public app, driven in process):

  1. without a square: the form, no code; /embed answers too
  2. a square (six characters too) gives a preview of the cards and the code,
     pointing at the public address, sized as the cards need, in the order
     status then openings
  3. card=prop / card=status give that card alone
  4. the code carries lang=tr and theme only when chosen; light is the
     default theme, "the reader's device" leaves it out
  5. lang=tr turns the page Turkish; the language link keeps the choices
  6. a malformed square is a 400 with the reason and no code, and what was
     typed is escaped
  7. the preview loads the cards from this server; nothing else is loaded
     from another host

Usage:  python tools/check_embed_builder.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import html
import re
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import web_gui  # noqa: E402

BASE = "https://map.example.org/"
STATUS = ('<iframe src="https://map.example.org/embed/status?grid=%s"\n'
          '        width="320" height="210" style="border:0" title="APRS-Agent %s"></iframe>')
PROP = ('<iframe src="https://map.example.org/embed/prop?grid=%s"\n'
        '        width="320" height="230" style="border:0" title="APRS-Agent %s"></iframe>')


def manager():
    return types.SimpleNamespace(get_config=lambda: {"public_base_url": BASE})


def code(h):
    m = re.search(r'<textarea id="code"[^>]*>(.*?)</textarea>', h, re.S)
    return html.unescape(m.group(1)) if m else None


def card(tpl, grid, q=""):
    return tpl % (grid + q, grid)


async def main() -> int:
    p = []
    async with TestClient(TestServer(web_gui._build_public_app(manager()))) as c:
        async def get(qs, path="/embed/"):
            r = await c.get(path + qs)
            return r.status, await r.text()

        for path in ("/embed/", "/embed"):
            st, h = await get("", path)
            print(f"  {path} -> {st}")
            if st != 200 or '<form method="get"' not in h or code(h) is not None:
                p.append(f"{path} without a square: {st}")

        st, h = await get("?grid=kn41ab")
        got = code(h)
        print(f"  kn41ab -> {st}\n{got}")
        want = card(STATUS, "KN41", "&theme=light") + "\n" + card(PROP, "KN41", "&theme=light")
        if st != 200 or got != want:
            p.append(f"both cards, light by default: got {got!r}")
        if '<iframe src="/embed/status?grid=KN41&amp;theme=light"' not in h or \
                '<iframe src="/embed/prop?grid=KN41&amp;theme=light"' not in h:
            p.append("preview does not load both cards from this server")

        st, h = await get("?grid=KM38&card=prop&lang=tr&theme=dark")
        got = code(h)
        if got != card(PROP, "KM38", "&lang=tr&theme=dark"):
            p.append(f"card=prop, Turkish, dark: {got!r}")
        if "Sayfanıza kart koyun" not in h or "Yapıştırılacak kod" not in h:
            p.append("lang=tr does not turn the page Turkish")
        if 'href="?grid=KM38&amp;card=prop&amp;theme=dark&amp;lang=en"' not in h:
            p.append("the language link drops the choices")

        st, h = await get("?grid=KM&card=status&theme=auto")
        if code(h) != card(STATUS, "KM"):
            p.append(f"card=status, a field, the reader's theme: {code(h)!r}")

        st, h = await get('?grid=KM38"><script>alert(1)</script>')
        print(f"  malformed -> {st}")
        if st != 400 or code(h) is not None or "Not a Maidenhead" not in h:
            p.append(f"malformed square: {st}")
        if "<script>alert" in h:
            p.append("what was typed is not escaped")

        st, h = await get("?grid=KM38")
        if re.search(r'(src|href)="https?://(?!map\.example\.org/)', h) or \
                re.search(r"<(script|link)[^>]+(src|href)=", h):
            p.append("loads something from another host")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
