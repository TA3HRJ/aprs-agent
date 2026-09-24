#!/usr/bin/env python3
"""Fail if a reader of the database can be made to wait for the registry flush.

Measured 2026-09-24 from outside, against the public map: `/api/silence/range`
answered in 0.2-1 s on 29 of 30 requests and in 8.0 s on the thirtieth, and a
page load in the browser saw it take 9.0 s and 8.6 s. The query itself runs in
4 ms on the live database. The rest was waiting.

The wait is the flush. Once a minute `save_sqlite` rewrites the registry,
252,427 rows, holding the write lock for 10-18 s (measured 2026-09-15). The
database ran in rollback-journal mode, where a writer that spills its cache
or commits takes an EXCLUSIVE lock and every reader queues behind it. Since
F-2026-09-15-01 the queue is off the event loop and nothing is dropped — the
journal shows 0 "database is locked" lines in 48 hours — so what remained was
the delay, and it landed on whoever opened the map at the wrong second.

In WAL mode readers read the last committed state and do not wait for a
writer at all. The mode is stored in the file, so it is set once, by the
first writable connection, and survives every restart after.

What must hold:

  1. a database written through station_db is in WAL mode
  2. a read through station_db completes in under 1 s while another
     connection holds an EXCLUSIVE lock for 4 s
  3. a read-only connection, the kind the backup and the check scripts use,
     can still open it
  4. SQLite's online backup of it, the nightly backup's method, passes
     integrity_check

Usage:  python tools/check_db_wal.py
Exit code 1 on failure.
"""
from __future__ import annotations

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
HOLD_S = 4.0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


def _hold_exclusive(path: str, started: threading.Event) -> None:
    con = sqlite3.connect(path, isolation_level=None, timeout=30)
    con.execute("BEGIN EXCLUSIVE")
    con.execute("INSERT INTO silence_history (ts, cell) VALUES (99, 'ZZ')")
    started.set()
    time.sleep(HOLD_S)
    con.execute("COMMIT")
    con.close()


with tempfile.TemporaryDirectory() as tmp:
    db = str(Path(tmp) / "wal.db")

    # The way the agent first touches a database: the registry flush, then a
    # silence snapshot. Both go through station_db's own connections.
    reg = sdb.StationDB()
    reg.save_sqlite(db)
    reg.record_silence_history(db, {}, {})
    con = sdb._connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS silence_history (ts INTEGER, "
                "cell TEXT, baseline INTEGER, silent INTEGER, ratio REAL, "
                "alert INTEGER, cause TEXT, silent_calls TEXT, since INTEGER, "
                "ai_note TEXT, PRIMARY KEY (ts, cell))")
    con.execute("INSERT OR REPLACE INTO silence_history (ts, cell) "
                "VALUES (1, 'AA')")
    con.commit()
    con.close()

    # ── 1 ──
    raw = sqlite3.connect(db)
    mode = raw.execute("PRAGMA journal_mode").fetchone()[0]
    raw.close()
    if mode != "wal":
        fail("1 mode", f"journal_mode is {mode!r}")
    else:
        ok("1 journal_mode is wal")

    # ── 2 ──
    started = threading.Event()
    th = threading.Thread(target=_hold_exclusive, args=(db, started))
    th.start()
    started.wait(10)
    t0 = time.monotonic()
    rng = sdb.silence_history_range(db)
    took = time.monotonic() - t0
    th.join()
    if took >= 1.0:
        fail("2 reader", f"silence_history_range waited {took:.2f} s behind "
                         f"a {HOLD_S:.0f} s writer")
    elif rng != {"min": 1, "max": 1}:
        fail("2 reader", f"answered in {took:.2f} s but with {rng}")
    else:
        ok(f"2 reader answered in {took * 1000:.0f} ms behind a "
           f"{HOLD_S:.0f} s writer, with the last committed state")

    # ── 3 ──
    try:
        ro = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
        n = ro.execute("SELECT COUNT(*) FROM silence_history").fetchone()[0]
        ro.close()
        ok(f"3 read-only connection opens it ({n} rows)")
    except sqlite3.Error as e:
        fail("3 read-only", str(e))

    # ── 4 ──
    copy = str(Path(tmp) / "copy.db")
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=10)
    dst = sqlite3.connect(copy)
    src.backup(dst)
    src.close()
    dst.close()
    c = sqlite3.connect(copy)
    verdict = c.execute("PRAGMA integrity_check").fetchone()[0]
    n = c.execute("SELECT COUNT(*) FROM silence_history").fetchone()[0]
    c.close()
    if verdict != "ok" or n != 2:
        fail("4 backup", f"integrity_check {verdict!r}, {n} rows")
    else:
        ok("4 online backup passes integrity_check, both rows present")


print()
print("FAIL" if FAIL else "PASS", f"— {FAIL} problem(s)")
sys.exit(1 if FAIL else 0)
