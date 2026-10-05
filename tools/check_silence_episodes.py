#!/usr/bin/env python3
"""Fail if a silence alert opens on a passing flicker, or re-opens on a dip.

F-2026-10-05-05: about 127 alert onsets a day, many lasting one scan and
many re-opening within hours as a cell flickered across the threshold -
KM59 alerted five times on 2026-10-03 with the same three habitual
stations. Replayed over two weeks, requiring the alert to hold (A) and
holding an episode across a dip of up to an hour (B) cut onsets 38 %, at
about ten minutes of delay. The operator chose A + B 1 h.

What must hold (AgentManager._silence_episodes, driven with a fake clock):

  1. a cell that meets the alert rule opens an episode only once it has met
     it on every scan for _SILENCE_CONFIRM_S (600 s); one scan is not enough
  2. a cell that drops below before then never opens, and its pending start
     is forgotten - a later crossing starts the wait again
  3. the episode's start is when the cell first met the rule, not when it
     was confirmed
  4. an open episode survives a dip shorter than _SILENCE_HOLD_S (3600 s):
     coming back inside the hour continues it, with no second opening
  5. a dip longer than the hold clears the episode, and a crossing after
     that is a new episode

Usage:  python tools/check_silence_episodes.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import web_gui  # noqa: E402


def mgr():
    return types.SimpleNamespace(_silence_active={}, _silence_pending_since={},
                                 _silence_dip={}, _silence_seen={},
                                 _silence_ai_notes={})


def step(m, alerting, t):
    return web_gui.AgentManager._silence_episodes(m, set(alerting), t)


def main() -> int:
    fails = []
    if not hasattr(web_gui.AgentManager, "_silence_episodes"):
        print("  FAIL  no AgentManager._silence_episodes")
        print("\n1 failure(s)")
        return 1
    if getattr(web_gui, "_SILENCE_CONFIRM_S", None) != 600 or \
            getattr(web_gui, "_SILENCE_HOLD_S", None) != 3600:
        fails.append("confirm/hold are not 600 s / 3600 s")

    # 1 + 3: opens after 600 s of every scan alerting, dated from the first
    m = mgr(); t = 1000.0
    o, c = step(m, {"KM59"}, t)
    if o:
        fails.append("opened on the first scan")
    o, c = step(m, {"KM59"}, t + 300)
    if o:
        fails.append("opened after 300 s")
    o, c = step(m, {"KM59"}, t + 600)
    if o != ["KM59"]:
        fails.append("did not open after 600 s of alerting: %r" % o)
    elif m._silence_active.get("KM59") != t:
        fails.append("episode start %r, expected the first crossing %r"
                     % (m._silence_active.get("KM59"), t))

    # 2: a flicker never opens, and the wait restarts
    m = mgr()
    step(m, {"FF91"}, t)
    step(m, set(), t + 300)
    o, _ = step(m, {"FF91"}, t + 600)
    if o or m._silence_pending_since.get("FF91") != t + 600:
        fails.append("a one-scan flicker opened, or its pending start was kept")

    # 4: a dip under an hour continues the episode
    m = mgr()
    for k in range(3):
        step(m, {"GF25"}, t + 300 * k)
    o, c = step(m, set(), t + 900)
    if c:
        fails.append("cleared on the first scan below the threshold")
    o, c = step(m, {"GF25"}, t + 900 + 1800)
    if o or c or "GF25" not in m._silence_active:
        fails.append("a 30 min dip did not continue the episode: opened %r cleared %r" % (o, c))
    if "GF25" in m._silence_dip:
        fails.append("the dip mark survived the return")

    # 5: a dip over an hour clears, and the next crossing is new
    m = mgr()
    for k in range(3):
        step(m, {"OK12"}, t + 300 * k)
    step(m, set(), t + 900)
    o, c = step(m, set(), t + 900 + 3600)
    if c != ["OK12"] or "OK12" in m._silence_active:
        fails.append("a dip of an hour did not clear: %r" % c)
    o, _ = step(m, {"OK12"}, t + 900 + 3900)
    if o:
        fails.append("re-opened at once after clearing, without the 600 s wait")

    for f in fails:
        print("  FAIL  " + f)
    if fails:
        print("\n%d failure(s)" % len(fails))
        return 1
    print("  ok    alerts open after 10 min held, survive a dip under an hour")
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
