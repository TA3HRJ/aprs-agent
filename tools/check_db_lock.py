#!/usr/bin/env python3
"""Fail if a database write can be lost to the registry flush, or if a longer
wait for the lock can stall the event loop.

Measured on the live VPS 2026-09-15. Over seven days the journal logged 247
propagation openings and `prop_history` held 234 of them. The 13 missing are
exactly the 13 `[prop] history write failed: database is locked` lines, each
about six seconds after its OPENING line.

The cause was measured on a consistent copy of the live database:

    save_sqlite, 252,427 rows, once a minute    9.95 s / 14.79 s / 18.24 s
    Python's default sqlite3 busy timeout        5 s

Every minute the registry flush rewrites the whole table and holds the write
lock for ten to eighteen seconds. Fourteen of sixteen `sqlite3.connect` calls
waited the default five, so any write landing in that window was dropped.

What must hold:

  behaviour
    1. a propagation event written while another connection holds the write
       lock for six seconds is stored, not dropped

  structure
    2. station_db.py opens the database in exactly one place, so no call site
       can quietly fall back to the default timeout again
    3. no async function in web_gui.py calls a database function directly.
       A longer busy timeout is only safe off the event loop: two endpoints and
       the silence assessment were reading SQLite on the loop itself, and with
       a lock wait long enough to outlast the flush they would freeze every
       request for as long as it waits. on_shutdown is the one exemption; it
       flushes once as the process exits.

Usage:  python tools/check_db_lock.py
Exit code 1 on failure.
"""
from __future__ import annotations

import ast
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import station_db as sdb  # noqa: E402

FAIL = 0
HOLD_S = 6.0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


# ── 1: a write survives a lock held longer than the old default ───────
def _hold_write_lock(path: str, started: threading.Event) -> None:
    con = sqlite3.connect(path, isolation_level=None)
    con.execute("BEGIN IMMEDIATE")
    con.execute("CREATE TABLE IF NOT EXISTS holder (x INTEGER)")
    con.execute("INSERT INTO holder VALUES (1)")
    started.set()
    time.sleep(HOLD_S)
    con.execute("COMMIT")
    con.close()


with tempfile.TemporaryDirectory() as tmp:
    db = str(Path(tmp) / "lock.db")
    sqlite3.connect(db).close()
    started = threading.Event()
    holder = threading.Thread(target=_hold_write_lock, args=(db, started))
    holder.start()
    started.wait(5)
    t0 = time.time()
    try:
        sdb.record_prop_event(db, {"ts": int(time.time()), "region": "JN",
                                   "note": "", "links": [{"call": "TA1ABC"}]})
        waited = time.time() - t0
        holder.join()
        con = sqlite3.connect(db)
        n = con.execute("SELECT COUNT(*) FROM prop_history").fetchone()[0]
        con.close()
        if n != 1:
            fail("write survives the lock", f"call returned but {n} rows stored")
        else:
            ok(f"an opening written under a {HOLD_S:.0f} s lock is stored "
               f"(waited {waited:.1f} s)")
    except sqlite3.OperationalError as e:
        holder.join()
        fail("write survives the lock",
             f"{e} after {time.time() - t0:.1f} s - the 2026-09-15 fault: the "
             f"flush holds the lock for 10-18 s and this write gave up")


# ── 2: one place opens the database ───────────────────────────────────
tree = ast.parse((ROOT / "station_db.py").read_text(encoding="utf-8"))
parents = {}
for node in ast.walk(tree):
    for child in ast.iter_child_nodes(node):
        parents[child] = node


def _enclosing_def(node):
    p = parents.get(node)
    while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef)):
        p = parents.get(p)
    return p


sites = [n for n in ast.walk(tree)
         if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
         and n.func.attr == "connect" and isinstance(n.func.value, ast.Name)
         and n.func.value.id == "sqlite3"]
outside = [f"line {n.lineno} in {getattr(_enclosing_def(n), 'name', '?')}"
           for n in sites if getattr(_enclosing_def(n), "name", "") != "_connect"]
if outside:
    fail("one place opens the database",
         f"{len(outside)} sqlite3.connect call(s) outside _connect: "
         + "; ".join(outside[:4]) + (" ..." if len(outside) > 4 else ""))
elif not sites:
    fail("one place opens the database", "no _connect helper found")
else:
    ok("station_db.py opens SQLite only through _connect")

# ── 3: no database call on the event loop ─────────────────────────────
_DB_MODULE_FUNCS = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)
                    and any(isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_connect"
                            for c in ast.walk(n))}
_DB_METHODS = {"save_sqlite", "load_sqlite", "record_silence_history", "silence_cells"}
_DB_SELF = {"_history_context"}

web = ast.parse((ROOT / "web_gui.py").read_text(encoding="utf-8"))
wparents = {}
for node in ast.walk(web):
    for child in ast.iter_child_nodes(node):
        wparents[child] = node

on_loop = []
for call in ast.walk(web):
    if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
        continue
    f = call.func
    name = f.attr
    is_db = ((isinstance(f.value, ast.Name) and f.value.id == "station_db_module"
              and (name in _DB_MODULE_FUNCS or not _DB_MODULE_FUNCS))
             or name in _DB_METHODS
             or (isinstance(f.value, ast.Name) and f.value.id == "self" and name in _DB_SELF))
    if not is_db:
        continue
    p = wparents.get(call)
    while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        p = wparents.get(p)
    if isinstance(p, ast.AsyncFunctionDef) and p.name != "on_shutdown":
        on_loop.append(f"{p.name}() line {call.lineno}: {name}")
if on_loop:
    fail("no database call on the event loop", "; ".join(on_loop))
else:
    ok("web_gui.py reads and writes SQLite only off the event loop")

if FAIL:
    print(f"\n{FAIL} failure(s)")
    sys.exit(1)
print("\nall clear")
