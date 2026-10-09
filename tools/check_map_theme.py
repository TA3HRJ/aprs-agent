#!/usr/bin/env python3
"""Fail if the map's family light theme stops being light by default, or
stops being removable, or the old look stops being the dark theme.

2026-10-10: the map page took the aprsagent.com family's paper theme as its
default, with the look it had until then kept, unchanged, as the dark theme
behind the same button the other family sites carry. The operator asked that
it could be undone if anything went wrong; this is how that stays true.

What must hold in static/index.html:

  1. a first-paint script sets data-theme to "light" unless the visitor
     stored "dark"; the system's prefers-color-scheme is not consulted
  2. the light theme is one additive block: every rule in it is scoped to
     :root[data-theme="light"] (bar the .thm button itself), and it is the
     last thing in the stylesheet so it wins without !important wars
  3. the original :root palette - the dark theme - is unchanged
  4. the admin header and the public header each carry the theme button,
     and a click handler stores the choice under "theme"

Usage:  python tools/check_map_theme.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DARK = ("--bg:#242424", "--sidebar:#2b2b2b", "--view:#1e1e1e", "--fg:#fff",
        "--accent:#3584e4", "--r:10px")


def main() -> int:
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    fails = []
    head = page[:page.find("<style")]
    m = re.search(r"<script>\(function\(\)\{var t=null;try\{t=localStorage\.getItem\(\"theme\"\)\}catch\(e\)\{\}\s*"
                  r"var d=document\.documentElement;d\.dataset\.theme=t===\"dark\"\?\"dark\":\"light\"", head)
    if not m:
        fails.append("1: no first-paint script defaulting to light")
    if "prefers-color-scheme" in page:
        fails.append("1: the page consults prefers-color-scheme")

    css = page[page.find("<style"):page.find("</style>")]
    i = css.find("aprsagent.com family LIGHT theme")
    i = css.rfind("/*", 0, i) if i >= 0 else i     # from the comment that opens it
    if i < 0:
        fails.append("2: no family light theme block")
    else:
        block = css[i:]
        rules = re.findall(r"([^{}]+)\{[^{}]*\}", re.sub(r"/\*.*?\*/", "", block, flags=re.S))
        for sel in rules:
            for part in sel.split(","):
                part = part.strip()
                if part and not part.startswith(':root[data-theme="light"]') \
                        and not part.startswith(".thm") \
                        and not part.startswith(':root[data-theme="dark"] .thm') \
                        and not part.startswith(':root:not([data-theme="dark"]) .thm'):
                    fails.append("2: an unscoped rule in the light block: %r" % part[:60])
                    break
        if css.rstrip().endswith("}") is False:
            pass
    root = re.search(r":root\{([^}]*)\}", css)
    if not root or any(v not in root.group(1).replace(" ", "") for v in DARK):
        fails.append("3: the original :root (dark) palette changed")

    for where, pat in (("admin", r'class="hdr-btn thm"[^>]*data-thm'),
                       ("public", r'class="log-btn thm"[^>]*data-thm')):
        if not re.search(pat, page):
            fails.append("4: no theme button in the %s header" % where)
    if "localStorage.setItem('theme',n)" not in page:
        fails.append("4: the click does not store the choice")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    light by default, one removable block, the old look kept as dark")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
