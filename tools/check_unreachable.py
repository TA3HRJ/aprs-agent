#!/usr/bin/env python3
"""Fail on statements that can never run.

Written after the AI Gateway stopped answering for a day. Inserting two new
methods between a constructor's body and its tail left three assignments and a
log line stranded below a `return` — syntactically perfect, silently dead. The
gateway then raised `'AIGateway' object has no attribute '_provider'` on every
message it received, and the only sign anything was wrong was the absence of a
log line nobody was looking for.

This is the second severing of its kind (the first cut a string literal in
half, v3.2.26), so it gets a check rather than more care.

Usage:  python tools/check_unreachable.py [path ...]      (default: repo root)
Exit code 1 if anything is found.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

TERMINAL = (ast.Return, ast.Raise, ast.Continue, ast.Break)


def scan(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
    except SyntaxError as e:
        return ["%s:%s: cannot parse — %s" % (path, e.lineno, e.msg)]

    found: list[str] = []

    def check_body(body: list[ast.stmt], where: str) -> None:
        for i, node in enumerate(body[:-1]):
            if isinstance(node, TERMINAL):
                dead = body[i + 1]
                found.append(
                    "%s:%d: unreachable after %s in %s — %s"
                    % (path, dead.lineno, type(node).__name__.lower(), where,
                       ast.dump(dead, annotate_fields=False)[:70])
                )
                break

    for node in ast.walk(tree):
        name = getattr(node, "name", None)
        where = name or type(node).__name__
        for field in ("body", "orelse", "finalbody"):
            body = getattr(node, field, None)
            if isinstance(body, list) and body and isinstance(body[0], ast.stmt):
                check_body(body, where)
    return found


def main(argv: list[str]) -> int:
    roots = [Path(a) for a in argv[1:]] or [Path(__file__).resolve().parent.parent]
    files: list[Path] = []
    for r in roots:
        files.extend([r] if r.is_file() else sorted(r.rglob("*.py")))
    files = [f for f in files if ".venv" not in f.parts and "venv" not in f.parts
             and "build" not in f.parts and "dist" not in f.parts]

    problems: list[str] = []
    for f in files:
        problems.extend(scan(f))

    for p in problems:
        print(p)
    print("checked %d files — %d unreachable %s"
          % (len(files), len(problems), "block" if len(problems) == 1 else "blocks"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
