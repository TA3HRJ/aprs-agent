#!/usr/bin/env python3
"""Fail if the public map page reaches a third-party host for its own code,
or lacks what a crawler and a lost visitor read.

2026-10-15. The page loaded Leaflet from unpkg.com, so every visitor's
address went to a CDN in the US, and a first visit paid a second DNS lookup
and TLS handshake (0.25-0.4 s measured from Turkey) for 46 KB. The same
review found no robots.txt, sitemap.xml, llms.txt or canonical URL, and a
mistyped address answered "404: Not Found" in plain text.

What must hold (the public app, driven in process):

  1. static/index.html loads no script or stylesheet from another host
  2. /leaflet-1.9.4.js and .css are served gzipped, cached for a year, and
     are byte-identical to Leaflet 1.9.4 (its published SRI hashes)
  3. /robots.txt keeps crawlers off /api/ and /ws and names the sitemap;
     with public_base_url set, the sitemap and the page's canonical link use
     it; without it there is no canonical and the request's host is used
  4. /llms.txt says what the page is and carries the configured contact
  5. a mistyped page address gets an HTML 404 page; an unknown /api/ path
     keeps its plain 404

Usage:  python tools/check_public_site.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import web_gui  # noqa: E402

SRI = {"leaflet-1.9.4.js": "20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=",
       "leaflet-1.9.4.css": "p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY="}


class _Mgr:
    def __init__(self, cfg):
        self._cfg = cfg

    def get_config(self):
        return self._cfg


async def run(cfg, problems, label):
    app = web_gui._build_public_app(_Mgr(cfg))
    async with TestClient(TestServer(app)) as c:
        # 2
        for name, sri in SRI.items():
            r = await c.get("/" + name, headers={"Accept-Encoding": "gzip"},
                            auto_decompress=False)
            body = await r.read()
            enc = r.headers.get("Content-Encoding", "")
            raw = gzip.decompress(body) if enc == "gzip" else body
            digest = base64.b64encode(hashlib.sha256(raw).digest()).decode()
            cc = r.headers.get("Cache-Control", "")
            if r.status != 200:
                problems.append(f"{label}: /{name} -> {r.status}")
                continue
            if enc != "gzip":
                problems.append(f"{label}: /{name} not gzipped")
            if "max-age=31536000" not in cc:
                problems.append(f"{label}: /{name} cache {cc!r}")
            if digest != sri:
                problems.append(f"{label}: /{name} is not Leaflet 1.9.4")
            print(f"  {label}: /{name} {r.status} {enc or 'plain'} "
                  f"{len(body)} B, {cc}")
        # 3
        r = await c.get("/robots.txt")
        robots = await r.text()
        if r.status != 200 or "Disallow: /api/" not in robots \
                or "Disallow: /ws" not in robots or "Sitemap:" not in robots:
            problems.append(f"{label}: robots.txt {r.status} {robots!r}")
        r = await c.get("/sitemap.xml")
        sm = await r.text()
        locs = re.findall(r"<loc>([^<]+)</loc>", sm)
        r = await c.get("/")
        page = await r.text()
        canon = re.findall(r'<link rel="canonical" href="([^"]+)">', page)
        base = cfg.get("public_base_url", "")
        if base:
            if locs != [base] or f"Sitemap: {base}sitemap.xml" not in robots:
                problems.append(f"{label}: sitemap/robots ignore the base "
                                f"({locs}, robots {robots!r})")
            if canon != [base]:
                problems.append(f"{label}: canonical {canon}, want [{base!r}]")
        else:
            if canon:
                problems.append(f"{label}: a canonical with no base set: {canon}")
            if not locs or not locs[0].startswith("http://127.0.0.1"):
                problems.append(f"{label}: sitemap without a base {locs}")
        print(f"  {label}: sitemap {locs}, canonical {canon}")
        # 4
        r = await c.get("/llms.txt")
        llms = await r.text()
        if r.status != 200 or "APRS" not in llms:
            problems.append(f"{label}: llms.txt {r.status}")
        mail = cfg.get("public_contact_email", "")
        if mail and mail not in llms:
            problems.append(f"{label}: llms.txt lacks the contact")
        # 5
        r = await c.get("/no-such-page")
        t = await r.text()
        if r.status != 404 or "text/html" not in r.headers.get("Content-Type", "") \
                or "<html" not in t:
            problems.append(f"{label}: /no-such-page -> {r.status} "
                            f"{r.headers.get('Content-Type')}")
        r = await c.get("/api/no-such-thing")
        t = await r.text()
        if r.status != 404 or "<html" in t:
            problems.append(f"{label}: /api/no-such-thing should stay a plain 404")
        print(f"  {label}: /no-such-page 404 html, /api/no-such-thing {r.status} plain")


async def main() -> int:
    problems = []
    # 1
    index = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    for m in re.finditer(r'<(script|link)\b[^>]*\b(?:src|href)="(https?://[^"]+)"', index):
        tag, url = m.group(1), m.group(2)
        if tag == "script" or "stylesheet" in m.group(0):
            problems.append(f"index.html loads {url} from another host")
    print(f"  index.html: {'no' if not problems else 'SOME'} third-party "
          "scripts or stylesheets")
    await run({"public_title": "APRS-Agent",
               "public_base_url": "https://map.example.org/",
               "public_contact_email": "ops@example.org"}, problems, "base set")
    await run({}, problems, "no base")
    if problems:
        print("\nFAIL")
        for p in problems:
            print("  - " + p)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
