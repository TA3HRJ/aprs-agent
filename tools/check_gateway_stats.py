#!/usr/bin/env python3
"""Fail if the gateway's own usage cannot be counted, or is counted wrong.

On 2026-09-20, the day the service was announced in two groups, the operator
asked how many people had used it and the only way to answer was an ad-hoc
query against the message table. That table keeps fourteen days and twenty
thousand rows, so "today" is free and "ever" is not: by the time the question
matters, the rows that would answer it are gone.

So the stations that ask are tallied as they are persisted - one row each,
first seen, last seen, how many questions - and the aggregate is what gets
published. Four things this holds:

  1. a station that asks is counted once, however many SSIDs it uses
  2. asking twice does not make two users, and does count two questions
  3. automatic stations (QRX and friends, no digit in the name) are not
     counted as operators, because they are not people
  4. today's number and the all-time number are both there, and the all-time
     one does not depend on rows that get pruned

No network: a scratch database is built, filled and thrown away.

Usage:  python tools/check_gateway_stats.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import station_db as sdb  # noqa: E402

NOW = int(time.time())
DAY0 = int(time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d")))


def msg(ts, direction, frm, to, text="q", channel="AI"):
    return {"ts": ts, "dir": direction, "from": frm, "to": to,
            "text": text, "msg_id": "", "channel": channel, "kind": "msg"}


def run() -> int:
    problems = []
    tmp = Path(tempfile.mkdtemp()) / "stats.db"
    path = str(tmp)

    rows = [
        # one operator, two SSIDs, three questions today
        msg(DAY0 + 100, "rx", "KC1MUR-5", "DMWGPT"),
        msg(DAY0 + 200, "rx", "KC1MUR-8", "DMWGPT"),
        msg(DAY0 + 300, "rx", "KC1MUR-8", "DMWGPT"),
        # a second operator, today
        msg(DAY0 + 400, "rx", "DL5XL-9", "DMWGPT"),
        # an automatic station - not a person
        msg(DAY0 + 500, "rx", "QRX", "DMWGPT"),
        # our own answers must not be counted as questions
        msg(DAY0 + 110, "tx", "DMWGPT", "KC1MUR-5"),
        # somebody else's traffic, not ours at all
        msg(DAY0 + 600, "rx", "W1AW-1", "N0CALL", "hi", "APRS"),
        # an operator from twenty days ago: gone from the message table by
        # then, and still part of "ever"
        msg(NOW - 20 * 86400, "rx", "YD6HTK", "DMWGPT"),
    ]
    sdb.record_gateway_users(path, rows)
    st = sdb.gateway_stats(path)

    if st.get("today") != 2:
        problems.append("today counted %r, expected 2 operators (two SSIDs "
                        "of one station are one person)" % st.get("today"))
    if st.get("total") != 3:
        problems.append("all-time counted %r, expected 3" % st.get("total"))
    if st.get("questions") != 5:
        problems.append("questions counted %r, expected 5 - only what was "
                        "asked, not what was answered" % st.get("questions"))
    if st.get("bots", 0) != 1:
        problems.append("automatic stations counted %r, expected 1 kept "
                        "apart from the operators" % st.get("bots"))

    # asking again is not a new user, and is a new question
    sdb.record_gateway_users(path, [msg(DAY0 + 700, "rx", "DL5XL-9", "DMWGPT")])
    st2 = sdb.gateway_stats(path)
    if st2.get("today") != 2:
        problems.append("a repeat visitor became a new user: %r"
                        % st2.get("today"))
    if st2.get("questions") != 6:
        problems.append("a second question was not counted: %r"
                        % st2.get("questions"))

    # the all-time tally survives the message table being emptied
    con = sdb._connect(path)
    try:
        con.execute("DELETE FROM message_history")
        con.commit()
    except Exception:
        pass
    finally:
        con.close()
    st3 = sdb.gateway_stats(path)
    if st3.get("total") != 3:
        problems.append("all-time tally depends on the pruned message table: "
                        "%r" % st3.get("total"))

    print("today %r | ever %r | questions %r | bots %r"
          % (st3.get("today"), st3.get("total"), st3.get("questions"),
             st3.get("bots")))
    for p in problems:
        print("FAIL: " + p)
    print("checked 4 cases - %d failed" % len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(run())
