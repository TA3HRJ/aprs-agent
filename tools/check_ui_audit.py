#!/usr/bin/env python3
"""Fail if the interface fixes of AUDIT-2026-10-08 (U1-U7) come undone.

Measured on the public map on 2026-10-08 at 800x600 and 375x812: the world
view was zoom 0, a world 256 px wide in a 1280 x 413 box with dark bands
around it; the tab caption showed half of its second line at every width;
the amber bar took 102 px of a phone screen; the stats bar left Lifetime
alone on a second row; half the propagation lines were suspect ones with
no way to hide them; 1,601 missing stations had only a time order; and
HELP never said how an alert is decided.

What must hold in static/index.html and HELP.html:

  U1  the map's least zoom is computed from its box (fitWorldZoom), on
      start and on every resize, and dragging stops at the poles
  U2  the caption collapses to one line with an ellipsis at every width -
      not -webkit-line-clamp, not only under 700 px
  U3  on a phone the amber bar is one line until tapped
  U4  on a phone the public stats bar hides this run's uptime
  U5  a legend checkbox hides suspect links, remembered per browser
  U7  the missing list can be grouped by square
  U6  HELP carries the rules in both languages, with their numbers

Usage:  python tools/check_ui_audit.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def body_of(src: str, name: str) -> str:
    m = re.search(r"function\s+%s\s*\([^)]*\)\s*\{" % re.escape(name), src)
    if not m:
        return ""
    i, depth = m.end(), 1
    while i < len(src) and depth:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        i += 1
    return src[m.start():i]


def main() -> int:
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    help_ = (ROOT / "HELP.html").read_text(encoding="utf-8")
    fails = []

    fw = body_of(page, "fitWorldZoom")
    if "setMinZoom" not in fw or "Math.log2" not in fw:
        fails.append("U1: no least zoom computed from the map's box")
    init = body_of(page, "initMap")
    if init.count("fitWorldZoom()") < 2 or "maxBounds" not in init:
        fails.append("U1: fitWorldZoom not run on start and resize, or no pole limit")

    m = re.search(r"\.tab-caption\.clamp\{([^}]*)\}", page)
    if not m or "line-clamp" in m.group(1) or "text-overflow:ellipsis" not in m.group(1):
        fails.append("U2: the caption still clamps with -webkit-line-clamp")
    if "innerWidth<=700" in body_of(page, "updCaption"):
        fails.append("U2: the caption collapses only under 700 px")

    if not re.search(r"\.deaf-bar:not\(\.open\)\{[^}]*text-overflow:ellipsis", page):
        fails.append("U3: the amber bar is not one line on a phone")
    if "classList.toggle('open')" not in body_of(page, "renderDeaf"):
        fails.append("U3: the amber bar does not open on a tap")

    if "body.public .stat-bar .cell.up{display:none}" not in page \
            or 'class="cell up"' not in page:
        fails.append("U4: the public phone bar still shows this run's uptime")

    rp = body_of(page, "renderProp")
    if 'id="leg-suspect"' not in page or "propShowSuspect" not in rp \
            or "aprs.showSuspect" not in page:
        fails.append("U5: no remembered toggle for suspect links")

    rm = body_of(page, "renderMissing")
    if "missByCell" not in rm or "miss-cellhdr" not in rm or "aprs.missByCell" not in page:
        fails.append("U7: the missing list cannot be grouped by square")

    for lang, words in (("tr", ("3 katı", "10 dakika", "24 saat", "250 km", "bir beacon aralığı")),
                        ("en", ("3 times", "10 minutes", "24 hours", "250 km", "one beacon"))):
        m = re.search(r'id="rules-%s".*?</div>\s*\n\s*\n' % lang, help_, re.S)
        if not m:
            fails.append("U6: HELP has no rules card (%s)" % lang)
            continue
        missing = [w for w in words if w not in m.group(0)]
        if missing:
            fails.append("U6: HELP rules (%s) lack %s" % (lang, missing))

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    U1-U7 in place: world fills the map, one-line caption and "
          "amber bar, one-row stats, suspect toggle, grouping, HELP rules")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
