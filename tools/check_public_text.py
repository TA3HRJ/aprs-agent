#!/usr/bin/env python3
"""Fail if the public repository carries what only belongs to its makers.

Everything committed here is published on GitHub, and the README, HELP,
LICENSE and the page the app serves are read by people who run the
software. 2026-10-07: the README's feature rows had grown into development
history ("before they did, no gate ever reached...", figures from a single
day's feed), the config template quoted a finding id, and an internal note
about a past README decision sat in docs/ as if it were documentation.

The project's authors are credited by name and link in the README, LICENSE
and About box on purpose. That is not what (1) is for.

What must hold:

  1. no tracked text file contains an identifier the operator has asked to
     keep out of the repository (a login, a private address). The list is held
     as SHA-256 hashes of the normalised text (lower case, accents and
     spaces dropped), so the check does not publish what it guards; any run
     of one to four consecutive words is tested, which catches "Name
     Surname", "NameSurname" and a URL path alike. To add one:
         python tools/check_public_text.py --hash "Name Surname"
  2. the files written for users - README.md, HELP.html, LICENSE and
     aprsconfig.toml.template - carry no internal
     markers: finding ids (F-YYYY-MM-DD-NN), the project's working notes by
     name, server paths and hosts of the live instance, or the assistant
  3. no README line is a wall: a feature row past 2,000 characters is where
     development history went last time

Usage:  python tools/check_public_text.py
Exit code 1 on failure.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# sha256(normalised identifier). Keep a comment-free list: a label here would
# say what is being hidden.
_PRIVATE = {
    "088f594a97cff1bcb8e593602ffb181368eba7dcaa3d2b3e18b03a060a173847",
    "53d25056b3235900b43b9c1dc7f8a0e445c3bf018901920a285e2abfd71ec7c9",
    "7ecbaaec647426fe103e805bdeb2c87c099de8220d15fdebadf1075480bbdf84",
    "98e804fb219435bb3ba4dedb99f61e66fd3bcfef5e3935757d44299f5550ede7",
    "aecf87881c5f723fc7088278520c1b595137fee28e66077f054c59354a53d573",
    "e4efa34744d1c46d4c17e9db6734a04e0de7bb68c370034dba17c759223ca80f",
}

# static/index.html is left out of the marker test: its finding ids sit in
# JS and HTML comments, read by whoever edits the page, as in the Python.
_USER_FACING = ["README.md", "HELP.html", "LICENSE", "aprsconfig.toml.template"]

_INTERNAL = [
    (r"\bF-20\d\d-\d\d-\d\d-\d\d\b|\bF-\d\d\b", "a finding id"),
    (r"\b(HANDOFF|FINDINGS|NEXT)\.md\b|SESSION-HANDOFF", "a working note by name"),
    (r"/etc/aprs-agent|aprs_stations\.db\?mode", "the live instance's server path"),
    (r"\bvmi\d{5,}\b|contaboserver|duckdns|webmin|\bwg44\b", "a host of the live instance"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "an IP address"),
    (r"\bClaude Code\b|\bthis session\b|\bthe operator (?:chose|asked|said|wanted|approved)\b",
     "the assistant or a working conversation"),
]
_IP_OK = {"127.0.0.1", "0.0.0.0"}
_MAX_LINE = 2000


def norm(s: str) -> str:
    s = s.lower().replace("ı", "i")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c))


def h(s: str) -> str:
    return hashlib.sha256(norm(s).encode("utf-8")).hexdigest()


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout.split("\n")
    return [ROOT / p for p in out if p]


def private_hits(text: str) -> int:
    words = [norm(w) for w in re.findall(r"\w+", text)]
    words = [w for w in words if w]
    n = 0
    for i in range(len(words)):
        acc = ""
        for j in range(i, min(i + 4, len(words))):
            acc += words[j]
            if hashlib.sha256(acc.encode("utf-8")).hexdigest() in _PRIVATE:
                n += 1
    return n


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--hash":
        print(h(sys.argv[2]))
        return 0
    fails = []
    for p in tracked():
        if p.suffix.lower() in (".png", ".ico", ".jpg", ".zip", ".pyc", ".db"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        n = private_hits(text)
        if n:
            # The file and the count only: printing the match would publish it
            # in every CI log.
            fails.append("%s: %d private identifier(s)" % (p.relative_to(ROOT), n))
    for rel in _USER_FACING:
        p = ROOT / rel
        if not p.exists():
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for pat, what in _INTERNAL:
                for m in re.finditer(pat, line):
                    if what == "an IP address" and m.group(0) in _IP_OK:
                        continue
                    fails.append("%s:%d: %s (%s)" % (rel, ln, what, m.group(0)))
            if rel == "README.md" and len(line) > _MAX_LINE:
                fails.append("%s:%d: %d characters on one line - user documentation, "
                             "not development history" % (rel, ln, len(line)))
    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    no private identifiers; user-facing files carry no internal notes")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
