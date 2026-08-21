#!/usr/bin/env python3
"""Fail if the packet feed can reach journald, or if it stops reaching the GUI.

Measured on the live VPS in World Mode: 310,328 of 319,051 journal lines an
hour were packet log lines, ~47 MB, and they pushed journald's stock 4 GB
ring over in 16 hours. Nobody had configured a limit — the feed simply
outran everything else in it, so every diagnostic line the agent wrote was
evicted within a day. A question about how often the AI gateway signs with a
false callsign turned out to be unanswerable for exactly that reason.

What makes this subtle is that the mechanism was deliberate. `Extension._emit`
writes to the real stderr on purpose, and its comment says why: so an
operator could confirm from journalctl that an extension had started. That
fix is what made journalctl useless for the same purpose.

So the boundary this check defends is narrow and easy to erase by accident:

  1. a packet line reaches the Web GUI Live Log (sys.stderr)
  2. a packet line does NOT reach the real stderr journald captures
  3. startup, warnings and errors still DO reach it — that was the point of
     the original fix and it must survive this one
  4. with log_file set, packets land in the file
  5. with log_file unset, no file is written and nothing raises
  6. an unwritable path degrades to Live-Log-only instead of killing the agent

Usage:  python tools/check_feedlog.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.logger_ext import Logger  # noqa: E402

PACKET = ("TA1ABC-9>APDR16,TCPIP*,qAC,T2X:!3826.00N/02706.00E>"
          "test packet, not a real station")


class Capture:
    """Stands in for both stderr streams so we can tell them apart."""

    def __init__(self):
        self.gui = io.StringIO()
        self.journal = io.StringIO()

    def __enter__(self):
        self._real, self._orig = sys.stderr, sys.__stderr__
        sys.stderr = self.gui
        sys.__stderr__ = self.journal
        return self

    def __exit__(self, *a):
        sys.stderr, sys.__stderr__ = self._real, self._orig


def cfg(**kw) -> dict:
    base = {"enabled": True, "log_comments": True,
            "filter_by_message_type": [], "exclude_by_message_type": [],
            "keyword_filter": []}
    base.update(kw)
    return base


async def run() -> int:
    problems: list[str] = []
    tmp = tempfile.mkdtemp(prefix="aprs-feedlog-")
    path = os.path.join(tmp, "packets.log")

    # 1 + 2 + 4 — a packet, with a file configured
    with Capture() as cap:
        lg = Logger(cfg(log_file=path))
        await lg.handle(PACKET)
    if "test packet" not in cap.gui.getvalue():
        problems.append("packet never reached the Web GUI Live Log")
    if "test packet" in cap.journal.getvalue():
        problems.append("packet reached the real stderr journald captures — "
                        "this is the 47 MB/hour path")
    on_disk = io.open(path, encoding="utf-8").read() if os.path.exists(path) else ""
    if "test packet" not in on_disk:
        problems.append("packet did not reach log_file")
    print("  %-28s gui=%s journald=%s dosya=%s"
          % ("paket (log_file ayarli)",
             "test packet" in cap.gui.getvalue(),
             "test packet" in cap.journal.getvalue(),
             "test packet" in on_disk))

    # 3 — an error must still be visible to a server-side operator
    with Capture() as cap:
        lg = Logger(cfg(log_file=path))
        lg.error("provider unreachable")
    if "provider unreachable" not in cap.journal.getvalue():
        problems.append("an error no longer reaches journald — that was the "
                        "whole point of the mechanism this change narrows")
    print("  %-28s gui=%s journald=%s"
          % ("hata satiri",
             "provider unreachable" in cap.gui.getvalue(),
             "provider unreachable" in cap.journal.getvalue()))

    # 5 — no file configured
    with Capture() as cap:
        lg = Logger(cfg())
        await lg.handle(PACKET)
    if "test packet" not in cap.gui.getvalue():
        problems.append("no log_file: packet stopped reaching the Live Log")
    if "test packet" in cap.journal.getvalue():
        problems.append("no log_file: packet fell back to journald")
    print("  %-28s gui=%s journald=%s"
          % ("paket (log_file yok)",
             "test packet" in cap.gui.getvalue(),
             "test packet" in cap.journal.getvalue()))

    # 6 — an unusable path must degrade, not crash
    bad = os.path.join(tmp, "packets.log", "nested.log")   # a file as a dir
    try:
        with Capture() as cap:
            lg = Logger(cfg(log_file=bad))
            await lg.handle(PACKET)
        ok = "test packet" in cap.gui.getvalue()
    except Exception as e:
        ok = False
        problems.append("an unwritable log_file raised: %s: %s"
                        % (type(e).__name__, e))
    if not ok:
        problems.append("an unwritable log_file stopped the Live Log too")
    print("  %-28s hala calisiyor=%s" % ("bozuk log_file yolu", ok))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
