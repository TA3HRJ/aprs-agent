#!/usr/bin/env python3
"""Fail if a silence episode can come back from a restart without its note.

Measured live. After the v3.2.99 restart on 2026-08-31, 8 cells were
alerting and 7 of them carried no AI note — and three consecutive scans
produced no new ALERT line, so none of the seven would ever get one.

The cause was an asymmetry between two halves of the same checkpoint:

    _silence_active    saved AND restored (inside a 30-minute grace window)
    _silence_ai_notes  saved nowhere, restored nowhere

An episode restored as already-open never opens again, and the note is only
written on opening, so `_assess_silence` was unreachable for it. The note
stayed empty until the cell recovered and opened a fresh episode.

What must hold:

  1. the notes are written to the checkpoint beside the episodes
  2. they are read back inside the SAME grace window — a note is a claim
     about a live episode and must go stale with it
  3. only notes whose episode also came back are kept: a note without its
     episode is a verdict about something that is no longer happening
  4. empty notes are not restored as if they were answers
  5. the meta channel actually round-trips a notes dict

Usage:  python tools/check_notes_survive.py
Exit code 1 on failure.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
tree = ast.parse(src)


def find_func(name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


# ── 1. saved beside the episodes ──────────────────────────────────────
save = find_func("_save_uptime")
if save is None:
    fail("save found", "_save_uptime is gone")
else:
    body = ast.dump(save)
    if "silence_notes" not in body:
        fail("notes saved", "_save_uptime does not write a silence_notes key")
    elif "_silence_ai_notes" not in body:
        fail("notes saved", "silence_notes is written from something other "
                            "than _silence_ai_notes")
    else:
        ok("the notes are written to the checkpoint")

# ── 2-4. restored, in the grace window, filtered ──────────────────────
# The restore lives inline in __init__, inside `if ckpt and ... <= 1800:`.
restored_in_window = False
filtered = False
drops_empty = False
for node in ast.walk(tree):
    if not isinstance(node, ast.If):
        continue
    guard = ast.dump(node.test)
    if "ckpt" not in guard or "1800" not in guard:
        continue
    block = ast.dump(ast.Module(body=node.body, type_ignores=[]))
    if "silence_notes" in block and "_silence_ai_notes" in block:
        restored_in_window = True
        if "_silence_active" in block.split("silence_notes", 1)[1]:
            filtered = True
        # `if k in self._silence_active and v` — the trailing truth test is
        # what keeps an empty string from being restored as an answer.
        for sub in ast.walk(node):
            if isinstance(sub, ast.comprehension) and len(sub.ifs) == 1:
                if isinstance(sub.ifs[0], ast.BoolOp) and len(sub.ifs[0].values) == 2:
                    drops_empty = True

if not restored_in_window:
    fail("notes restored", "the notes are not read back inside the same "
                           "30-minute grace window as the episodes")
else:
    ok("the notes are restored inside the episodes' grace window")
    if not filtered:
        fail("filtered to live episodes",
             "restored notes are not filtered against _silence_active")
    else:
        ok("only notes whose episode also came back are kept")
    if not drops_empty:
        fail("empty notes dropped",
             "an empty note is restored as though it were an answer")
    else:
        ok("empty notes are not restored as answers")

# ── 5. the meta channel round-trips the dict ──────────────────────────
import station_db as station_db_module  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    path = str(Path(d) / "t.db")
    payload = {"KP23": "[power_outage/high] four of seven gone",
               "JP78": "[unknown/low] one site"}
    try:
        station_db_module.save_meta(path, "silence_notes", json.dumps(payload))
        back = json.loads(station_db_module.load_meta(path, "silence_notes", "{}"))
    except Exception as e:
        back = None
        fail("meta round-trip", f"{type(e).__name__}: {e}")
    if back is not None:
        if back != payload:
            fail("meta round-trip", f"got {back!r}")
        else:
            ok("the checkpoint round-trips a notes dict intact")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
