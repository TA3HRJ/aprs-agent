#!/usr/bin/env python3
"""Fail if a callsign sign-off can reach the air, or if plain Turkish is eaten.

Measured live on the public service. Asked "Test", the model replied:

    Test received. 73 de TA3HRJ-10 gateway.

TA3HRJ-10 is the station that ASKED. The gateway signed itself with somebody
else's callsign, on the air, days after the service was announced publicly.
The system prompt forbids exactly this, in as many words, and the model did
it anyway — so the rule moved out of the prompt and into the code, which is
the same conclusion §G and §H reached before it.

Two ways this can go wrong, and both are held here:

  it lets a sign-off through
    1. the observed case, with trailing words after the callsign
    2. an answer that is ONLY a sign-off — the whole transmission would be a
       false identification, and an early version returned it untouched
    3. "de CALL" and "73 CALL" as well as "73 de CALL"

  it cuts something it should not
    4. Turkish "de"/"da" is one of the commonest words in the language and is
       NOT a sign-off cue. "Ben de oyle dusunuyorum" must survive intact
    5. a callsign in the body of an answer is normal — the position lookup
       answers with one — and must survive
    6. an ordinary answer with no callsign at all is never touched

Usage:  python tools/check_signature.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.ai_gateway_ext import _strip_signature  # noqa: E402

# (label, input, must_not_contain, must_equal or None)
CASES = [
    # ── must be stripped ──────────────────────────────────────────────
    ("live case",       "Test received. 73 de TA3HRJ-10 gateway.",
     "TA3HRJ", "Test received."),
    ("trailing 73 de",  "A dipole works well on 40m. 73 de TA1ABC",
     "TA1ABC", "A dipole works well on 40m."),
    ("only a sign-off", "73 de TA1ABC", "TA1ABC", "73"),
    ("bare de",         "de TA1ABC-9", "TA1ABC", "73"),
    ("73 without de",   "73 TA1ABC-9", "TA1ABC", "73"),
    ("sign-off first",  "73 de TA1ABC and good luck with the antenna",
     "TA1ABC", "and good luck with the antenna"),
    ("no full stop",    "Use a 1:1 balun 73 de TA9XYZ-7",
     "TA9XYZ", "Use a 1:1 balun."),

    # ── must survive untouched ────────────────────────────────────────
    ("turkish de",      "Ben de oyle dusunuyorum.", None, None),
    ("turkish da",      "Ankara da guzel bir sehir, orada da APRS var.",
     None, None),
    ("plain answer",    "SWR is the ratio of forward to reflected power.",
     None, None),
    ("position lookup",
     "TA1ABC-7: 38.457,27.099 (KM38nk) 3d ago via YM3KC-8. My own feed only",
     None, None),
    ("weather lookup",
     "TA1ABC-13 12km away, 4min ago: 26.1C, 47%RH. My own feed only",
     None, None),
    ("callsign in body",
     "YM1ABC-10 is the gate that heard you, ask them about the antenna.",
     None, None),
]


def main() -> int:
    problems: list[str] = []

    for label, text, forbidden, expect in CASES:
        got = _strip_signature(text)

        if forbidden and forbidden in got:
            problems.append("%s: sign-off survived -> %r" % (label, got))
        if expect is not None and got != expect:
            problems.append("%s: got %r, expected %r" % (label, got, expect))
        if expect is None and forbidden is None and got != text:
            problems.append("%s: changed an answer it should not touch\n"
                            "        %r\n     -> %r" % (label, text, got))

        mark = "kesti" if got != text else "-"
        print("  %-17s %-5s %r" % (label, mark, got[:52]))

    # Nothing may ever come back empty: an empty answer is not transmitted at
    # all, which would turn a misbehaving model into total silence.
    for label, text, _f, _e in CASES:
        if not _strip_signature(text).strip():
            problems.append("%s: stripped to nothing" % label)

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
