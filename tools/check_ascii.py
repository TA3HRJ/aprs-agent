#!/usr/bin/env python3
"""Fail if the gateway's ASCII folding drops a letter instead of its accent.

APRS messages are ASCII, so replies are folded before they go out. The first
folding mapped the Turkish letters and a handful of accents by hand, then
discarded everything else outside 32..126 — which deleted the letter rather
than the mark. Measured on the live gateway, answering in Portuguese:

    português  -> portugus       informação -> informaco
    notícias   -> notcias        rádio      -> rdio

Four broken words in one conversation, and it would have done the same to
every Latin-script language except Turkish and English. The cases below are
the ones that actually went out on the air, plus the Turkish letters that must
keep working and the dash that made "TA3HRJ—more" look like a callsign.

Usage:  python tools/check_ascii.py
Exit code 1 if any case fails.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GW = ROOT / "extensions" / "ai_gateway_ext.py"

CASES = [
    # (input, expected) — the four that broke in production
    ("português",            "portugues"),
    ("informação",      "informacao"),
    ("notícias",             "noticias"),
    ("rádio",                "radio"),
    # other Latin script
    ("é um transceptor",     "e um transceptor"),
    ("lançamento",           "lancamento"),
    ("España",               "Espana"),
    ("Grüße",           "Grusse"),
    # Turkish must survive the NFD pass: dotless i has no decomposition
    ("Türkçe ışık", "Turkce isik"),
    ("İstanbul",             "Istanbul"),
    # a dash straight after a callsign read as an SSID
    ("TA3HRJ—more at x",     "TA3HRJ - more at x"),
    ("café — more",     "cafe - more"),
]


def _load_folder():
    """Pull _to_ascii out of the extension without importing its dependencies."""
    src = io.open(GW, encoding="utf-8").read()
    head = src[src.index("_TR_MAP"):src.index("def _split_message")]
    ns: dict = {"__name__": "gw"}
    exec(compile("import re, unicodedata\n" + head, str(GW), "exec"), ns)
    return ns["_to_ascii"]


def main() -> int:
    fold = _load_folder()
    bad = 0
    for src_text, want in CASES:
        got = fold(src_text)
        if got != want:
            bad += 1
            print("FAIL  %r -> %r, expected %r" % (src_text, got, want))
    print("checked %d cases — %d failed" % (len(CASES), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
