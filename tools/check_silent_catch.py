#!/usr/bin/env python3
"""Fail if an empty catch in the page can swallow a fault in the page's own code.

v3.2.122 shipped `T[lang]` in a page whose translation table is `S`. The
ReferenceError sat inside the init block and took every line after it down.
v3.2.123 moved the line into `fillGateway()` and wrapped it in
`try{...}catch(e){}`, which contained the damage and hid the cause: the
gateway counter simply never appeared, and a swallowed exception looks exactly
like a line that chose not to render. It took until v3.2.124 to find.

The pattern was not unique to that function. The 5 s station poll wrapped
`renderMap()` in an empty catch, so a fault there would have stopped the map
updating with nothing said anywhere; so did the silence poll, the timeline,
the Messages tab and the init block.

The page's rule since then: a failed request is weather - the next poll asks
again, so it stays quiet. A failed render is a bug. Requests mark their own
failures (`netFail`), and `quiet(e)` lets only those through; anything else
reaches the console, and on the admin page the server journal.

What must hold:

  1. no `try{...}catch(x){}` with an empty handler has a try block that calls
     a function this page declares (`api`, `renderMap`, `fillGateway`, ...)
     or parses a response (`.json(`). Empty handlers around browser APIs -
     localStorage, the clipboard, the service worker - are allowed: nothing
     of ours can fail inside them.
  2. `quiet` exists, and stays silent only for errors `netFail` has marked
  3. `api()` marks both the request and the response parse
  4. `fillGateway`, whose catch hid v3.2.122, hands its error to `quiet`

Promise-style `.catch(function(){})` is not covered: its receiver is an
expression, not a block, and the three in the page are deliberate (a warm-up
fetch consumed later, the diagnostic report itself, a cache delete).

Usage:  python tools/check_silent_catch.py
Exit code 1 on failure.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "static" / "index.html"

# `$` is `document.getElementById`; it cannot throw.
HARMLESS = {"$"}


def script_text(html: str) -> tuple[str, int]:
    """The inline script, and the line it starts on."""
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    if not m:
        raise SystemExit("FAIL: no inline <script> in static/index.html")
    return m.group(1), html.count("\n", 0, m.start(1)) + 1


def code_mask(src: str) -> str:
    """The source with strings, template literals, regexes and comments blanked.

    Same length, newlines kept, so offsets and line numbers still line up.
    Good enough for this file; not a JavaScript parser.
    """
    out = list(src)
    i, n = 0, len(src)
    prev = ""                       # last significant character outside blanks

    def blank(a: int, b: int) -> None:
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
            continue
        if c in "'\"`":
            j = i + 1
            while j < n and src[j] != c:
                j += 2 if src[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
            prev = "a"
            continue
        after_word = re.search(r"(?<![\w$.])(return|typeof|case|throw|in|of|void)\s*$",
                               src[max(0, i - 12):i])
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};+-*%<>~^" or after_word):
            j = i + 1
            in_class = False
            while j < n and src[j] != "\n":
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == "[":
                    in_class = True
                elif src[j] == "]":
                    in_class = False
                elif src[j] == "/" and not in_class:
                    break
                j += 1
            blank(i, j + 1)
            i = j + 1
            prev = "a"
            continue
        if not c.isspace():
            prev = c
        i += 1
    return "".join(out)


def brace_pairs(code: str) -> dict[int, int]:
    """Closing brace offset -> its opening brace offset."""
    stack, pairs = [], {}
    for i, c in enumerate(code):
        if c == "{":
            stack.append(i)
        elif c == "}":
            if not stack:
                raise SystemExit(f"FAIL: unbalanced '}}' at offset {i}")
            pairs[i] = stack.pop()
    if stack:
        raise SystemExit(f"FAIL: {len(stack)} unclosed '{{'")
    return pairs


def main() -> int:
    html = PAGE.read_text(encoding="utf-8")
    src, first_line = script_text(html)
    code = code_mask(src)
    pairs = brace_pairs(code)

    declared = set(re.findall(r"\bfunction\s+([A-Za-z_$][\w$]*)\s*\(", code))
    declared -= HARMLESS
    if "api" not in declared or "renderMap" not in declared:
        print("FAIL: could not find the page's own functions - did the scanner break?")
        return 1
    calls = re.compile(r"(?<![\w$.])(" + "|".join(
        re.escape(f) for f in sorted(declared, key=len, reverse=True)) + r")\s*\(")

    problems: list[str] = []
    empty = allowed = 0
    for m in re.finditer(r"\}\s*catch\s*\(\s*[\w$]+\s*\)\s*\{(\s*)\}", code):
        close = m.start()
        opener = pairs.get(close)
        if opener is None or not re.search(r"\btry\s*$", code[:opener]):
            continue
        empty += 1
        body = code[opener + 1:close]
        hits = sorted(set(calls.findall(body)))
        if ".json(" in body:
            hits.append(".json")
        line = first_line + src.count("\n", 0, m.start())
        if hits:
            problems.append(f"line {line}: empty catch swallows a fault in "
                            f"{', '.join(hits)}")
        else:
            allowed += 1

    # 2 - quiet() exists and lets only marked errors through
    q = re.search(r"function quiet\s*\(\s*(\w+)\s*\)\s*\{", code)
    if not q:
        problems.append("quiet(e) is not defined")
    else:
        head = code[q.end():q.end() + 120]
        if not re.match(r"\s*if\s*\(\s*\w+\s*&&\s*\w+\.net\s*\)\s*return\b", head):
            problems.append("quiet() must return early only for errors marked .net")
    if not re.search(r"function netFail\s*\(\s*(\w+)\s*\)\s*\{[^}]*\.net\s*=\s*true",
                     code):
        problems.append("netFail(e) does not mark the error .net = true")

    # 3 - api() marks both the request and the parse
    a = re.search(r"async function api\s*\(", code)
    if a:
        end = next(c for c, o in sorted(pairs.items()) if o == code.index("{", a.end()))
        body = code[a.end():end]
        if not re.search(r"net\s*\(\s*fetch\s*\(", body):
            problems.append("api(): the fetch is not wrapped in net()")
        if not re.search(r"net\s*\(\s*\w+\.json\s*\(", body):
            problems.append("api(): the response parse is not wrapped in net()")

    # 4 - the catch that hid v3.2.122
    f = re.search(r"function fillGateway\s*\([^)]*\)\s*\{", code)
    if f:
        end = next(c for c, o in sorted(pairs.items()) if o == f.end() - 1)
        if not re.search(r"catch\s*\(\s*(\w+)\s*\)\s*\{\s*quiet\s*\(\s*\1\s*\)",
                         code[f.end():end + 1]):
            problems.append("fillGateway() does not hand its error to quiet()")
    else:
        problems.append("fillGateway() not found")

    print(f"{empty} empty catch blocks in the page, {allowed} around browser APIs only")
    for p in problems:
        print("  " + p)
    print(f"{len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
