#!/usr/bin/env python3
"""Fail if the admin page links to a visitor report that may not exist.

2026-10-07: the operator looked for his visitor report, could not find a
link to it anywhere, and asked whether one had been deleted. None had ever
existed: the report is a static file the web server in front of his panel
serves at /stats/, reached by bookmark. A link was then wanted in the panel.

The panel ships to every operator who runs the program, and /stats/ exists
only where someone set it up in front of the app. A fixed link would be a
dead button on every other install. So the button appears only when /stats/
answers on this origin - a HEAD probe, the redirect left unfollowed so a
login page does not count as the report.

What must hold:

  1. the header has a Stats button, hidden until the probe succeeds
  2. the probe is a HEAD of /stats/ with redirect:'manual', only off the
     public view, and reveals the button only on r.ok
  3. the button opens /stats/ in a new tab, without an opener
  4. the app itself has no /stats route and no catch-all, so on a plain
     install the probe meets a 404 and the button stays hidden
  5. the label is translated

Usage:  python tools/check_stats_link.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    fails = []
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<button[^>]*id="btn-stats"[^>]*>', page)
    if not m:
        fails.append("the header has no Stats button (#btn-stats)")
    else:
        tag = m.group(0)
        if "hidden" not in tag:
            fails.append("#btn-stats is not hidden by default")
        if "'/stats/'" not in tag or "noopener" not in tag or "_blank" not in tag:
            fails.append("#btn-stats does not open /stats/ in a new tab without an opener")
    probe = re.search(r"fetch\('/stats/',\{[^}]*\}\)[^;]*btn-stats", page)
    if not probe:
        fails.append("no probe of /stats/ reveals the button")
    else:
        p = probe.group(0)
        if "method:'HEAD'" not in p or "redirect:'manual'" not in p:
            fails.append("the probe is not a HEAD with redirect:'manual': %r" % p[:120])
        if "r.ok" not in p:
            fails.append("the button is not revealed on r.ok only")
        before = page[max(0, probe.start() - 120):probe.start()]
        if "!window.PUBLIC" not in before:
            fails.append("the probe also runs on the public view")
    for lang in ("btn_stats:\"Stats\"", "btn_stats:\"İstatistik\""):
        if lang not in page:
            fails.append("missing translation %s" % lang)
    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    if re.search(r"""routes\.\w+\(\s*["']/stats""", web):
        fails.append("the app serves /stats itself - the probe would always succeed")
    if re.search(r"""routes\.\w+\(\s*["'][^"']*\{(tail|path)[^}]*\}""", web) or "add_static(\"/\"" in web:
        fails.append("the app has a catch-all route - /stats/ would not 404 on a plain install")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    Stats button shown only where /stats/ answers, never on the public view")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
