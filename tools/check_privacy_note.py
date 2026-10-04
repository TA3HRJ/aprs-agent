#!/usr/bin/env python3
"""Fail if the public page's data note can show without a contact, or carry
an operator's address in the code.

2026-09-30: the public map stores what other people broadcast - station
records with no time limit, messages for 14 days - and said nothing about
it. The note added then is configuration-driven, because the page ships to
every operator who runs the program: a contact address written into the
code would appear on all of their pages.

What must hold:

  1. config.py has public_contact_email, empty by default, and the template
     documents it
  2. /api/info hands it to the page
  3. the About box's data note is hidden by default and shown only on the
     public page with a contact set
  4. the note states the retention the code enforces (14 days, matching
     station_db._HISTORY_RETENTION_S) and that station records have no limit

The About box already names the developers with their addresses; that is
authorship, not the data contact, and is left alone.

Usage:  python tools/check_privacy_note.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    fails = []
    import config
    if config.DEFAULTS.get("public_contact_email", None) != "":
        fails.append("config default public_contact_email is missing or not empty")
    tpl = (ROOT / "aprsconfig.toml.template").read_text(encoding="utf-8")
    if not re.search(r"^public_contact_email\s*=\s*\"\"", tpl, re.M):
        fails.append("template does not document public_contact_email")
    web = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    if '"public_contact_email": cfg.get("public_contact_email"' not in web:
        fails.append("/api/info does not pass public_contact_email")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<div[^>]*id="about-data"[^>]*>', page)
    if not m:
        fails.append("About box has no data note (#about-data)")
    elif "hidden" not in m.group(0):
        fails.append("#about-data is not hidden by default")
    if not re.search(r"window\.PUBLIC[^;]*public_contact_email|public_contact_email[\s\S]{0,200}about-data",
                     page):
        fails.append("the note is not tied to the contact setting")
    from station_db import StationDB
    days = StationDB._HISTORY_RETENTION_S // 86400
    for lang in ("en", "tr"):
        blk = re.search(r'about_data_txt:"([^"]*)"', page[page.find(
            "about_title:" if lang == "en" else 'about_title:"APRS-Agent Hakk'):])
        if not blk:
            fails.append("%s: about_data_txt missing" % lang)
            continue
        txt = blk.group(1)
        if str(days) not in txt:
            fails.append("%s: note does not state the %d-day retention" % (lang, days))
        if not re.search(r"time limit|süre sınırı", txt):
            fails.append("%s: note does not say station records have no limit" % lang)
        if "NOLOOKUP" not in txt:
            fails.append("%s: note does not mention NOLOOKUP" % lang)
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    data note: config-driven, hidden without a contact, states the retention")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
