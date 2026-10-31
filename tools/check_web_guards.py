#!/usr/bin/env python3
"""Fail if one of the web_gui guards from the 2026-10-31 review is gone.

An outside review of web_gui.py v3.2.205, each item confirmed against the
code before it was fixed (F-2026-10-31-01 .. -04). What must hold (no
network, no server):

  1. a state-changing request with `Origin: null` is refused like any
     foreign origin - a sandboxed frame sends exactly that, and an empty
     netloc was read as "no Origin"; our own origin and no Origin at all
     still pass
  2. when silence_state() raises, the still-off-the-air list is left as it
     is - an empty answer read as every station gone from the registry,
     emptied the list and logged a "back on the air" for each; when it
     answers, a station heard again still leaves and a silent one stays
  3. a young gate's "would it be flagged if established" uses the bar an
     established gate is held to, max(3*mean, mean + 4*sigma), not 3*mean
  4. a monitor notification with an smtp_server that has no port is
     refused with a clear line, not handed to smtplib with an empty host
  5. /api/missing and the grid status iterate snapshots of dicts another
     thread changes
  6. one unreadable quake watch does not stop the others being restored
  7. a station that falls silent while its cell's episode is already open
     reaches the still-off-the-air list, not only those silent when it
     opened (F-2026-10-31-05: 461 in a week were not); a cell still waiting
     out its confirm delay adds nobody, and an entry keeps its first date

Usage:  python tools/check_web_guards.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import web_gui as wg  # noqa: E402


async def origin_status(origin: str | None, host: str = "127.0.0.1:8080") -> int:
    from aiohttp import web
    from aiohttp.test_utils import make_mocked_request
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    req = make_mocked_request("POST", "/api/stop", headers=headers)

    async def handler(_r):
        return web.Response(text="ok")
    try:
        with redirect_stderr(io.StringIO()):
            r = await wg._same_origin_only(req, handler)
        return r.status
    except web.HTTPForbidden:
        return 403


class FakeDb:
    def __init__(self, state=None, boom=False):
        self.state, self.boom = state or {}, boom

    def silence_state(self, calls):
        if self.boom:
            raise RuntimeError("registry busy")
        return {c: self.state[c] for c in calls if c in self.state}


def manager(db, missing):
    m = wg.AgentManager.__new__(wg.AgentManager)
    m._station_db = db
    m._missing = dict(missing)
    return m


def main() -> int:
    p = []

    # 1
    for origin, want in (("null", 403), ("https://evil.example", 403),
                         ("http://127.0.0.1:8080", 200), (None, 200)):
        got = asyncio.run(origin_status(origin))
        print(f"  1 Origin {origin!r} -> {got}")
        if got != want:
            p.append(f"1: Origin {origin!r} answered {got}, expected {want}")

    # 2
    missing = {c: {"cell": "JN27", "flagged": 1.0} for c in ("A-1", "B-2", "C-3")}
    prune = getattr(wg.AgentManager, "_prune_missing", None)
    if prune is None:
        p.append("2: no AgentManager._prune_missing - the pruning cannot be tested")
    else:
        with redirect_stderr(io.StringIO()):
            m = manager(FakeDb(boom=True), missing)
            m._prune_missing()
        print(f"  2 silence_state raises -> {len(m._missing)} of 3 kept")
        if len(m._missing) != 3:
            p.append(f"2: silence_state raising emptied the list to {len(m._missing)}")
        state = {"A-1": {"silent": False}, "B-2": {"silent": True},
                 "C-3": {"silent": False, "unknown": True}}
        with redirect_stderr(io.StringIO()):
            m = manager(FakeDb(state), missing)
            m._prune_missing()
        print(f"  2 heard/silent/unknown -> kept {sorted(m._missing)}")
        if sorted(m._missing) != ["B-2", "C-3"]:
            p.append(f"2: the answered case kept {sorted(m._missing)}, expected B-2, C-3")

    # 3  young gate, mean 300 km, sigma 400 km, link 1000 km: 3*mean is
    # 900 km, but the established bar is 300 + 1600 = 1900 km
    link = {"km": 1000.0, "at_flag": {"samples": 6, "ema_km": 300.0,
                                     "sigma_km": 400.0, "established": False,
                                     "threshold_km": 250.0,
                                     "times_threshold": 4.0}}
    r = wg._prop_vs_baseline(link, {"samples": 6, "established": False},
                             {"min_km": 250.0, "gate_min_samples": 20})
    print(f"  3 young gate -> bar {r.get('established_threshold_km')}, "
          f"flagged {r.get('would_flag_if_gate_established')}")
    if r.get("established_threshold_km") != 1900.0:
        p.append(f"3: established bar {r.get('established_threshold_km')}, expected 1900.0")
    if r.get("would_flag_if_gate_established") is not False:
        p.append("3: a 1000 km link was said to clear a 1900 km bar")
    if "would still be flagged" in r.get("reading", ""):
        p.append("3: the reading says the link would still be flagged")

    # 4
    import smtplib
    calls = []

    class FakeSMTP:
        def __init__(self, host="", port=0, **k):
            calls.append((host, port))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def sendmail(self, *a):
            pass
    real = smtplib.SMTP
    smtplib.SMTP = FakeSMTP
    err = io.StringIO()
    try:
        cfg = {"extensions": {"smtp": {
            "smtp_server": "smtp.gmail.com", "smtp_username": "u",
            "from_email": "u@example.com",
            "allowed_receiver_emails": ["op@example.com"]}}}
        with redirect_stderr(err):
            try:
                asyncio.run(wg.AgentManager._send_notification("x", "smtp", cfg))
            except Exception as e:
                print(f"raised {type(e).__name__}: {e}", file=err)
    finally:
        smtplib.SMTP = real
    print(f"  4 smtp_server without port -> smtplib {calls}, said {err.getvalue().strip()[:70]!r}")
    if calls:
        p.append(f"4: handed to smtplib as {calls}")
    if "host:port" not in err.getvalue():
        p.append("4: no line saying the server needs host:port")

    # 5
    src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    gm = src[src.find("async def get_missing"):src.find("async def get_missing") + 2500]
    if not re.search(r"for call, meta in list\(mgr\._missing\.items\(\)\)", gm):
        p.append("5: /api/missing iterates mgr._missing itself")
    gs = src[src.find("async def _grid_status"):src.find("def _quake_watch_scan")]
    if re.search(r"for w in self\._quake_watches\.values\(\)", gs):
        p.append("5: _grid_status iterates self._quake_watches itself")

    # 6
    import json
    now = 1_000_000.0
    text = json.dumps({"us1": {"ts": "x"}, "us2": {"ts": now - 60}})
    try:
        got = wg._quake_watches_load(text, now)
    except Exception as e:
        got = {"raised": str(e)}
    print(f"  6 one bad watch, one good -> {sorted(got)}")
    if sorted(got) != ["us2"]:
        p.append(f"6: restored {sorted(got)}, expected us2")

    # 7
    note = getattr(wg.AgentManager, "_note_missing", None)
    if note is None:
        p.append("7: no AgentManager._note_missing - stations silent after "
                 "an episode opened are never added")
    else:
        m = manager(None, {"OLD-1": {"cell": "JN27", "flagged": 5.0}})
        m._silence_active = {"JN27": 1.0}
        alerts = {"JN27": {"silent_calls": ["OLD-1", "LATE-2"]},
                  "KP23": {"silent_calls": ["PENDING-3"]}}
        m._note_missing(alerts, 100.0)
        print(f"  7 open JN27 + pending KP23 -> {sorted(m._missing)}")
        if "LATE-2" not in m._missing:
            p.append("7: a station silent after its cell's episode opened was not added")
        if "PENDING-3" in m._missing:
            p.append("7: a cell still waiting out its confirm delay added a station")
        if m._missing.get("OLD-1", {}).get("flagged") != 5.0:
            p.append("7: an entry already on the list lost its first date")

    for f in p:
        print("  FAIL  " + f)
    if p:
        print("\n%d failure(s)" % len(p))
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
