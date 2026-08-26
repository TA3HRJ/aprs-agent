"""
APRS-Agent Web GUI
==================
Web-based interface for APRS-Agent. Runs on any OS with a browser.

  python web_gui.py                        Start with defaults
  python web_gui.py -c /path/to/config     Use a specific config
  python web_gui.py --host 0.0.0.0 -p 8080 Listen on all interfaces

On Windows: automatically opens browser to http://localhost:PORT
On Linux  : access via http://SERVER_IP:PORT

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import json
import math
import queue
import re
import sys
import threading
import time
import webbrowser
from collections import OrderedDict, deque
from pathlib import Path
from typing import Any, Optional, Set

from aiohttp import WSCloseCode, web

import config as cfg_module
import aprs_connection
import extension_server as ext_server_module
from extensions import ExtensionRegistry
import station_db as station_db_module
from packet_parser import parse_message
from station_db import StationDB


def _resolve_path(name: str) -> Path:
    if hasattr(sys, "_MEIPASS"):
        p = Path(sys._MEIPASS) / name
        if p.exists():
            return p
    p = Path(__file__).parent / name
    if p.exists():
        return p
    return Path(name)


_STATIC_DIR = _resolve_path("static")
_DEFAULT_CFG = Path(__file__).parent / "aprsconfig.toml"

# Cache headers: app shell revalidates via ETag, immutable assets cache for a day
_NO_CACHE = {"Cache-Control": "no-cache"}
_DAY_CACHE = {"Cache-Control": "public, max-age=86400"}
# Brand assets revalidate instead of sitting in the cache for a day.
# Replacing the logo changed the bytes and the ETag, and browsers that
# already held it kept showing the old mark because max-age told them not
# to ask. A conditional GET on a 17 KB file is cheap; being wrong for a
# day is not.
_REVALIDATE = {"Cache-Control": "public, no-cache"}

# In-memory gzip cache for index.html, keyed by file mtime/size so edits
# during development are picked up automatically.
_GZ_CACHE: dict = {}


def _gzipped_index(public: bool = False) -> tuple[bytes, bytes, str]:
    """Return (raw_html, gzipped_html, etag).

    Injects the running version as window.BUILD, which is how an already-open
    page notices it is running an old build: a tab never re-requests the shell
    on its own, so without this it keeps executing whatever JavaScript it
    loaded, however many times the server is redeployed. The public variant
    additionally gets window.PUBLIC so the page renders in read-only mode.
    """
    path = _STATIC_DIR / "index.html"
    st = path.stat()
    # The version belongs in the key and the ETag as well: a release that
    # bumps VERSION without touching index.html would otherwise keep serving
    # a page that reports the previous build, and the page would either never
    # notice the update or never stop noticing it.
    key = (st.st_mtime_ns, st.st_size, cfg_module.VERSION)
    ck = "index-pub" if public else "index"
    cached = _GZ_CACHE.get(ck)
    if not cached or cached[0] != key:
        raw = path.read_bytes()
        inject = b'<script>window.BUILD="' + cfg_module.VERSION.encode() + b'"'
        if public:
            inject += b";window.PUBLIC=true"
        raw = raw.replace(b"</head>", inject + b"</script></head>", 1)
        body = gzip.compress(raw, 9)
        suffix = "-p" if public else ""
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}-{cfg_module.VERSION}{suffix}"'
        cached = (key, raw, body, etag)
        _GZ_CACHE[ck] = cached
    return cached[1], cached[2], cached[3]


class _QueueWriter:
    """Bounded stderr redirect: drops the oldest lines when the browser
    cannot keep up, so memory stays flat on long unattended runs."""

    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if not text:
            return
        try:
            self._q.put_nowait(text)
        except queue.Full:
            try:
                self._q.get_nowait()
            except queue.Empty:
                pass
            try:
                self._q.put_nowait(text)
            except queue.Full:
                pass

    def flush(self) -> None:
        pass


# Source callsign of packets echoed by the logger extension, e.g.
# "[logger] TA3ABC-9>APRS,TCPIP*,qAC,...:payload"
_SRC_CALL_RE = re.compile(r"^\[logger\] ([A-Z0-9]{3,9}(?:-[A-Z0-9]{1,2})?)>", re.M)
# Full raw APRS line extracted from logger output
_SRC_LINE_RE = re.compile(r"^\[logger\] (.+)$", re.M)
# The agent's own Fixed Beacon (outbound — never echoed back by APRS-IS).
# Ingested locally so the station shows on the map; flagged so it is excluded
# from silence detection.
_OWN_BEACON_RE = re.compile(r"^\[fixed_beacon\] beacon sent: (.+)$", re.M)
# Outbound packets, printed by the APRS-IS send loop for every extension.
# APRS-IS never echoes our own traffic, so this is the only way to see the
# messages we send (AI replies, Telegram/WhatsApp/email bridges).
_TX_LINE_RE = re.compile(r"^--> (.+)$", re.M)

# Messages panel: rolling in-memory buffer (~400 × ~500 B ≈ 200 KB)
_MSG_BUFFER = 400
_MSG_DEDUP_S = 30      # same message re-gated by another igate

# Log-line classification for the RX/TX/error stat counters. These mirror the
# browser's cls() classifier so the server-authoritative counts match what the
# live log colouring shows — but, unlike the old client-side tally, they survive
# a page refresh because they live on the server alongside the packet counter.
_AIRESP_MARK = "[ai-gateway] AI response"
_AIERR_RE = re.compile(r"\[ai-gateway\].*error|failed", re.I)
_ERR_RE = re.compile(r"error|fail|fatal", re.I)

_MAX_STATIONS = 200     # last-heard chip table (most recent N callsigns)
_STATS_INTERVAL = 2.0   # seconds between stats pushes to browsers
_AI_NOTE_COOLDOWN_S = 3 * 3600   # reuse a silence/prop AI note this long

# ── Earthquake correlation (USGS, free, no API key, refreshed every minute)
# A regional silence cluster and a nearby earthquake look identical to the
# detector — both are "many stations stopped at once". Pulling the quake in
# turns the AI's verdict from "shared infrastructure or power issue" into
# something an operator can act on, and costs one cached HTTP GET.
_QUAKE_URL = ("https://earthquake.usgs.gov/earthquakes/feed/v1.0/"
              "summary/4.5_day.geojson")
_QUAKE_TTL = 600.0          # scans run every 5 min; don't hammer USGS
_QUAKE_RADIUS_KM = 500.0    # generous: report it, let the AI weigh it
_QUAKE_WINDOW_S = 24 * 3600
_quake_cache: "tuple[float, list]" = (0.0, [])


_slim_lock: "asyncio.Lock | None" = None


def _get_slim_lock() -> "asyncio.Lock":
    """Created lazily so it binds to the running loop, and shared by the
    admin and public apps (same process, same loop)."""
    global _slim_lock
    if _slim_lock is None:
        _slim_lock = asyncio.Lock()
    return _slim_lock


_cells_lock: "asyncio.Lock | None" = None
# (built_at, build_seconds, cells) — built_at 0.0 means "never built", which is
# the only thing that makes a caller wait. An empty result is a result.
_cells_cache: "tuple[float, float, list]" = (0.0, 0.0, [])
# Floor for the adaptive window. It used to be 2.0 s, which quietly undid the
# adaptation it sat in front of: the window is computed from the LAST build, so
# a fast build granted 2.0 s and the next build — measured at up to 2.4 s on
# 145k stations — had already outlived the window it was given. The walk ran
# essentially without pause (F-36: ~1 request in 5 rebuilt, cached answers
# 0.07-0.30 s against rebuilds of 0.6-2.4 s). The map polls every few seconds
# and does not need cells fresher than this.
_CELLS_MIN_TTL_S = 10.0


async def silence_cells_cached(db, history_path: str = "") -> list:
    """silence_cells() off the event loop, shared by every caller.

    The history path is what turns on the narrower definition of `alert`: with
    it the cells carry `chronic` and `persistence` and a cell that has been in
    this state through its whole recorded history stops being called news.
    Without it the raw threshold result comes back, which is what
    record_silence_history() wants to store.

    It walks the whole station registry: measured at 0.3-0.9 s against 165k
    stations. Run inline it stops everything else for that long, and the map
    polls it on a timer — which is how the API came to answer some requests in
    six seconds and hang others past forty. Exactly the shape of the v3.1.2
    livelock, which fixed /api/stations and left this one behind; v3.2.0 then
    copied the synchronous call into the evidence endpoint.

    The window scales with the measured build, as it does for the station
    cache: a rebuild that takes longer than its own TTL can never finish
    before the next caller starts another one.
    """
    global _cells_cache
    global _cells_lock
    if _cells_lock is None:
        _cells_lock = asyncio.Lock()

    # F-35: while the feed is deaf, silence_cells() returns [] as a refusal to
    # judge, not as a finding. Rebuilding here would overwrite the last true
    # reading with that refusal, and every consumer downstream would read it as
    # "nothing is silent anywhere". Hold what we last knew and let the callers
    # label it — they ask db.deaf_since() for themselves.
    if db.deaf_since():
        return _cells_cache[2]

    built_at, build_s, cells = _cells_cache
    now = time.time()
    if built_at and now - built_at < max(_CELLS_MIN_TTL_S, build_s * 4):
        return cells

    async with _cells_lock:
        # Another caller may have rebuilt it while this one waited.
        built_at, build_s, cells = _cells_cache
        now = time.time()
        if built_at and now - built_at < max(_CELLS_MIN_TTL_S, build_s * 4):
            return cells
        t0 = time.time()
        try:
            fresh = await asyncio.get_event_loop().run_in_executor(
                None, lambda: db.silence_cells(history_path=history_path))
        except Exception:
            return cells
        _cells_cache = (time.time(), time.time() - t0, fresh)
        return fresh


def _fetch_quakes() -> list:
    """Recent M4.5+ quakes worldwide. Never raises: correlation is extra
    context, never a precondition for alerting — if USGS is unreachable the
    silence alert must still go out exactly as before.

    BLOCKING — call only via run_in_executor (the silence watch loop warms
    the cache once per scan). Inline on the event loop it would freeze every
    other request for the whole HTTP timeout.
    """
    global _quake_cache
    ts, data = _quake_cache
    now = time.time()
    if now - ts < _QUAKE_TTL:
        return data
    try:
        import urllib.request, json as _json
        req = urllib.request.Request(
            _QUAKE_URL,
            headers={"User-Agent": f"APRS-Agent/{cfg_module.VERSION}"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = _json.loads(resp.read())
        out = []
        for f in raw.get("features", []):
            p = f.get("properties") or {}
            g = (f.get("geometry") or {}).get("coordinates") or []
            if len(g) < 2 or p.get("mag") is None:
                continue
            out.append({
                "mag": round(float(p["mag"]), 1),
                "place": (p.get("place") or "").strip(),
                "ts": float(p.get("time") or 0) / 1000.0,
                "depth_km": (round(float(g[2])) if len(g) > 2
                             and g[2] is not None else None),
                "lat": float(g[1]), "lon": float(g[0]),
            })
        _quake_cache = (now, out)
        return out
    except Exception:
        # Keep whatever we had and back off for a full TTL rather than
        # retrying on every cell of every scan.
        _quake_cache = (now, data)
        return data


def _quakes_near(lat: float, lon: float, since_ts: float) -> list:
    """Quakes close enough, and recent enough, to be a candidate cause for a
    silence that began at since_ts. Ordered strongest-and-nearest first."""
    out = []
    # Cache only — never fetches. Warmed off-loop by the silence watch loop;
    # until it has been warmed this returns nothing, which is the correct
    # degradation (no quake context) rather than a stalled request.
    for q in _quake_cache[1]:
        if not (since_ts - _QUAKE_WINDOW_S <= q["ts"] <= since_ts + 600):
            continue
        try:
            d = StationDB._haversine_km(lat, lon, q["lat"], q["lon"])
        except Exception:
            continue
        if d <= _QUAKE_RADIUS_KM:
            out.append(dict(q, dist_km=int(round(d))))
    out.sort(key=lambda q: (-q["mag"], q["dist_km"]))
    return out[:3]


def _cell_quakes(cell: str, since_ts: "float | None") -> list:
    """Quake candidates for a Maidenhead cell, measured from its centre."""
    b = station_db_module._cell_bounds(cell)
    if not b or not since_ts:
        return []
    lat = (b[0][0] + b[1][0]) / 2.0
    lon = (b[0][1] + b[1][1]) / 2.0
    return _quakes_near(lat, lon, since_ts)


def _gate_evidence(mgr: "AgentManager", c: dict) -> dict:
    """Which gate each silent station came through, and whether we can see it.

    Eight stations up to 100 km apart all falling quiet inside nine seconds is
    not a region losing power; it is one path going away. The registry knew
    which path, and the bundle did not carry it, so readers inferred a "shared
    dependency" from timing when they could have been told.
    """
    gate_of = c.get("gate_of") or {}
    out: dict = {"gate_of": gate_of, "distinct_gates": len(set(gate_of.values())),
                 "shared_gate": c.get("shared_gate") or "", "detail": {}}
    now = time.time()
    for g in sorted(set(gate_of.values())):
        if not g:
            continue
        r = mgr._station_db._stations.get(g)
        if r is None or not r.packet_count:
            out["detail"][g] = {
                "tracked": False,
                "note": "this gate is not in the registry — it never beacons "
                        "its own position, or sits outside the feed. Its "
                        "silence cannot be confirmed either way",
            }
        else:
            out["detail"][g] = {
                "tracked": True,
                "last_seen": int(r.last_seen),
                "silent_for_s": max(0, int(now - r.last_seen)),
                # The same 30-minute rule the cause branch uses.
                "considered_silent": (now - r.last_seen) >= 1800,
            }
    return out


def _cell_context_stats(c: dict, history: dict) -> dict:
    """Where the current state sits in this cell's own history.

    A cell that has been at this ratio in every stored snapshot is telling a
    different story from one that has just reached it, and the difference took
    reading hundreds of rows to see.
    """
    recent = (history or {}).get("recent") or []
    snaps = (history or {}).get("snapshots") or 0
    alerting = (history or {}).get("alerting_snapshots") or 0
    ratio = c.get("ratio") or 0.0
    at_or_above = sum(1 for r in recent if (r.get("ratio") or 0) >= ratio)
    # Both numbers used to come from the cell's own stored rows, and only
    # alerting cells are stored — so "alerting in every snapshot" was true of
    # every cell, always. The prompt asserted it, the model repeated it with a
    # /high confidence tag, and the popup ended up calling a cell a possible
    # outage and chronically normal in the same breath. snapshots is now the
    # number of snapshot RUNS since the cell was first seen.
    pct = int(round(100.0 * alerting / snaps)) if snaps else 0
    # How often a cell alerts turned out not to be the useful question — cells
    # alerting in 2% of runs still had the identical cast of silent stations
    # every time. Whether any station currently silent is one this cell does
    # NOT usually miss is the question, so the prompt gets that too, and gets
    # it named rather than implied.
    recur = c.get("recurrence") or {}
    novel = c.get("novel_stations") or []
    if not recur:
        stations = ""
    elif novel:
        stations = (" These stations are silent and are NOT usually among "
                    "this cell's missing: {n}. That is the part that needs "
                    "explaining; the rest of the silent set is routine for "
                    "this cell.").format(n=", ".join(novel))
    else:
        stations = (" Every station currently silent here is one that is "
                    "usually among this cell's missing, so this is the same "
                    "set as before rather than something new.")
    return {
        "snapshots": snaps,
        "alerting_snapshots": alerting,
        "alerting_share": round(alerting / snaps, 3) if snaps else None,
        "always_alerting": bool(snaps) and pct >= 90,
        "station_recurrence": recur,
        "novel_stations": novel,
        "recent_sampled": len(recent),
        "recent_at_or_above_current_ratio": at_or_above,
        "reading": (
            "this cell has alerted in {a} of the {n} snapshot runs taken "
            "since it was first seen ({p}%). {v}"
        ).format(a=alerting, n=snaps, p=pct, v=(
            "That is essentially all of them: the current state is this "
            "cell's normal rather than a change."
            if pct >= 90 else
            "So it alerts intermittently, and has recovered in between — do "
            "not describe it as permanently or chronically silent."
        )) + stations if snaps else "no stored history for this cell yet",
    }


def _quake_evidence(c: dict) -> list:
    """Quake candidates carrying the two fields the map popup never showed:
    how long before the silence each one happened, and its hypocentral
    (slant) distance, which accounts for depth.

    Both are already computable from what we store; neither reaches the
    operator. The time offset in particular is what separates "10 minutes
    before" from "20 hours before" — the difference between causation and
    coincidence.
    """
    out = []
    since = c.get("since")
    for q in _cell_quakes(c["cell"], since):
        e = dict(q)
        if since:
            # Positive = the quake happened before the silence began.
            e["offset_s"] = int(since - q["ts"])
        depth = q.get("depth_km")
        if depth is not None:
            e["hypocentral_km"] = int(round(math.hypot(q["dist_km"], depth)))
        out.append(e)
    return out


def _fmt_quake(q: dict) -> str:
    """One-line human summary, e.g. 'M7.4 120 km away, 40m before, 103 km deep'."""
    depth = f", {q['depth_km']} km deep" if q.get("depth_km") is not None else ""
    where = f" ({q['place']})" if q.get("place") else ""
    return f"M{q['mag']} {q['dist_km']} km away{depth}{where}"


class AgentManager:

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.running = False
        self._log_queue: queue.Queue = queue.Queue(maxsize=2000)
        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._public_ws: Set[web.WebSocketResponse] = set()  # read-only viewers
        self._thread: Optional[threading.Thread] = None
        self._agent_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._original_stderr = sys.stderr
        # Live stats shown in the browser (packet counter + last-heard stations)
        self._started_at: Optional[float] = None
        self._pkt_count = 0
        self._unique_count = 0          # distinct call+SSID pairs ever heard
        self._unique_calls = 0          # distinct base callsigns (SSID stripped)
        self._ai_rx = 0                 # AI-gateway messages received (RX)
        self._ai_tx = 0                 # AI-gateway messages sent (TX)
        self._err_count = 0             # error/failure log lines
        self._stations: "OrderedDict[str, list]" = OrderedDict()  # call -> [last_ts, count]
        self._seen_calls: "set[str]" = set()       # full call+SSID
        self._seen_base_calls: "set[str]" = set()  # base callsign only
        self._last_stats_sent = 0.0
        self._station_db: StationDB = StationDB()
        # SQLite persistence lives next to the config file
        self._sta_db_path = str(
            Path(config_path).resolve().with_name("aprs_stations.db"))
        try:
            n = self._station_db.load_sqlite(self._sta_db_path)
            if n:
                print(f"[station-db] Restored {n} stations from "
                      f"{self._sta_db_path}", file=sys.__stderr__)
            bad = getattr(self._station_db, "load_dropped_positions", 0)
            if bad:
                # Written before positions were validated anywhere. Saying it
                # out loud is how anyone learns the stored data had them.
                print(f"[station-db] dropped {bad} stored position(s) that "
                      f"were not on Earth", file=sys.__stderr__)
        except Exception as e:
            print(f"[station-db] SQLite load failed: {e}", file=sys.__stderr__)
        # Lifelong uptime: seconds accumulated by every previous run. The
        # current session is added on top when reported, and folded in here
        # when the agent stops — so a restart (a release, a reboot) no longer
        # loses the station's total service time.
        try:
            self._uptime_base = float(
                station_db_module.load_meta(self._sta_db_path, "uptime_total", "0"))
        except (ValueError, TypeError):
            self._uptime_base = 0.0
        # Lifetime AI analysis call counter (silence + propagation + station
        # AI — the auto-triggered calls that eat the provider quota; the AI
        # Gateway's user-triggered RF replies are its own concern). Persisted
        # so the operator can watch the Puter/Groq quota across restarts.
        try:
            self._ai_calls = int(
                station_db_module.load_meta(self._sta_db_path,
                                            "ai_calls_total", "0"))
        except (ValueError, TypeError):
            self._ai_calls = 0
        # Silence watch (Phase 4): active alert episodes + AI assessments
        self._silence_active: dict[str, float] = {}
        self._silence_ai_notes: dict[str, str] = {}
        # Stations that crossed their silence threshold while their cell was
        # alerting and have not been heard since. Deliberately NOT cleared
        # when the cell's alert clears: in the Colombia M7.4 case the cell
        # fell below the alert ratio as soon as 5 of 7 stations recovered,
        # which dropped the whole cell from the alert list — including the
        # two stations that never came back, i.e. the only two worth looking
        # at. Entries leave this dict when the station is heard again.
        # callsign -> {"cell": str, "flagged": float}
        self._missing: dict[str, dict] = {}
        # Digest mode: alerts queued here between flushes (list of (ts, cell
        # dict, ai note)); lost on restart, same as the episode state above.
        self._silence_pending: list = []
        self._silence_last_flush = time.time()
        # Set while the feed is deaf, so entering and leaving that state each
        # log once instead of every 5-minute scan (F-35).
        self._silence_deaf_at: float = 0.0
        # Gate baselines are checkpointed on a slower cadence than the rest.
        self._gate_stats_saved_at: float = 0.0
        # Propagation openings: active episodes per Maidenhead field
        # (region → first-detected ts). Alert once per episode, like silence.
        self._prop_active: dict[str, float] = {}
        # Restore alert episodes (silence + propagation) so a restart doesn't
        # blind the "Since" duration or re-fire notifications for an outage
        # already in progress. Only trusted if the checkpoint is recent — if
        # the agent was down for a while, cells may have flapped through
        # several real episodes in the meantime, and none of that history is
        # recoverable; starting fresh is more honest than resurrecting a
        # stale start time or duplicating a still-open episode's alert.
        try:
            ckpt = float(station_db_module.load_meta(
                self._sta_db_path, "episodes_checkpoint_ts", "0"))
        except (ValueError, TypeError):
            ckpt = 0.0
        if ckpt and (time.time() - ckpt) <= 1800:
            try:
                self._silence_active.update(json.loads(
                    station_db_module.load_meta(
                        self._sta_db_path, "silence_episodes", "{}")))
            except Exception:
                pass
            try:
                self._prop_active.update(json.loads(
                    station_db_module.load_meta(
                        self._sta_db_path, "prop_episodes", "{}")))
            except Exception:
                pass
        # Gate baselines are restored unconditionally, with no grace window.
        # An episode is a claim about right now and goes stale; "what this gate
        # normally hears" is a property of an aerial on a hill. Without this,
        # no gate ever reached the 20 samples its own threshold requires, and
        # the propagation detector ran permanently on the absolute floor (F-43).
        try:
            n = self._station_db.import_gate_stats(json.loads(
                station_db_module.load_meta(
                    self._sta_db_path, "prop_gate_stats", "{}")))
            if n:
                print(f"[prop] {n} gate baselines restored", file=sys.stderr)
        except Exception:
            pass
        # Missing stations are restored WITHOUT the checkpoint grace window
        # the episodes above use. A station that never came back is a
        # multi-day concern, and the whole point of tracking it is that it
        # survives — including a restart, which is exactly when its cell may
        # no longer be alerting and so would never re-flag it. Stale entries
        # are self-correcting: the first scan drops anyone heard since.
        try:
            self._missing.update(json.loads(
                station_db_module.load_meta(
                    self._sta_db_path, "missing_stations", "{}")))
        except Exception:
            pass
        # AI-note cooldown cache: cell/region -> (note, generated_ts). A cell
        # that recovers and re-alerts minutes later doesn't need a fresh AI
        # read — the previous verdict is reused within _AI_NOTE_COOLDOWN_S,
        # which is where a meaningful share of world-mode AI call volume was
        # going (flapping cells re-alerting repeatedly). RAM-only, same as
        # the propagation link stats — re-learns within hours of a restart.
        self._silence_note_cache: dict[str, tuple[str, float]] = {}
        self._prop_note_cache: dict[str, tuple[str, float]] = {}
        # Messages panel: rolling buffer of APRS messages (in + out)
        self._messages: deque = deque(maxlen=_MSG_BUFFER)
        self._msg_seen: dict[tuple, int] = {}   # dedup key → last seen ts
        self._channel_map: dict[str, str] = {}  # callsign → AI/Telegram/…

    def get_config(self) -> dict:
        return cfg_module.load_config(self.config_path)

    def save_config(self, data: dict) -> None:
        cfg_module.sync_config_to_file(data, self.config_path)

    def start(self) -> bool:
        if self.running:
            return False
        self._thread = threading.Thread(target=self._run_agent, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> bool:
        if not self.running:
            return False
        if self._agent_loop and self._stop_event:
            self._agent_loop.call_soon_threadsafe(self._stop_event.set)
        return True

    def _run_agent(self) -> None:
        self._agent_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._agent_loop)
        self._stop_event = asyncio.Event()
        sys.stderr = _QueueWriter(self._log_queue)
        self._started_at = time.time()
        self._pkt_count = 0
        self._unique_count = 0
        self._unique_calls = 0
        self._ai_rx = 0
        self._ai_tx = 0
        self._err_count = 0
        self._stations.clear()
        self._seen_calls.clear()
        self._seen_base_calls.clear()
        # Station records are NOT reset on agent start any more: they are
        # persisted in SQLite so the beacon-cadence baseline (silence
        # detection) survives restarts.
        try:
            cfg = cfg_module.load_config(self.config_path)
            self._channel_map = self._build_channel_map(cfg)
            grids = cfg.get("monitor", {}).get("silence_grids", []) or []
            self._station_db.silence_grids = [
                str(g).strip().upper() for g in grids if str(g).strip()]
            if self._station_db.silence_grids:
                self._log_queue.put(
                    "[silence] Scoped to grids: "
                    + ", ".join(self._station_db.silence_grids) + "\n")
            # Tell silence detection what the feed can actually hear. After
            # narrowing from full feed to a prefix filter, the registry still
            # holds tens of thousands of foreign stations — all "silent" only
            # because we stopped listening, which painted the whole world red
            # for the 24 h baseline window. Out-of-scope stations must not be
            # silence sensors.
            if cfg.get("full_feed", False):
                self._station_db.feed_filter = []
            else:
                self._station_db.feed_filter = [
                    str(c).strip().upper()
                    for c in cfg.get("allowed_callsigns", []) if str(c).strip()]
            db_path = cfg.get("repeater_db_path", "").strip()
            if db_path:
                n = self._station_db.load_repeater_db(db_path)
                if n:
                    self._log_queue.put(f"[station-db] Loaded {n} repeater records from DB\n")
                else:
                    self._log_queue.put(f"[station-db] WARNING: repeater_db_path set but no records loaded from '{db_path}'\n")
        except Exception as e:
            self._log_queue.put(f"[station-db] Could not load repeater DB: {e}\n")
        self.running = True
        try:
            self._agent_loop.run_until_complete(self._agent_main())
        except Exception as e:
            self._log_queue.put(f"[agent] fatal: {e}\n")
        finally:
            sys.stderr = self._original_stderr
            self.running = False
            # Fold this session into the lifelong total before the clock resets
            if self._started_at:
                self._uptime_base += time.time() - self._started_at
                self._started_at = None
                self._save_uptime()
            self._agent_loop.close()
            self._agent_loop = None

    def lifelong_uptime(self) -> float:
        """Total seconds this station has been running, across all restarts."""
        total = self._uptime_base
        if self.running and self._started_at:
            total += time.time() - self._started_at
        return total

    def _save_uptime(self) -> None:
        try:
            station_db_module.save_meta(
                self._sta_db_path, "uptime_total", str(int(self.lifelong_uptime())))
            station_db_module.save_meta(
                self._sta_db_path, "ai_calls_total", str(self._ai_calls))
            # Episode checkpoint rides the same cadence (60 s + shutdown).
            station_db_module.save_meta(
                self._sta_db_path, "silence_episodes",
                json.dumps(self._silence_active))
            station_db_module.save_meta(
                self._sta_db_path, "prop_episodes",
                json.dumps(self._prop_active))
            station_db_module.save_meta(
                self._sta_db_path, "episodes_checkpoint_ts", str(time.time()))
            station_db_module.save_meta(
                self._sta_db_path, "missing_stations",
                json.dumps(self._missing))
            # Not on every 60 s checkpoint: this one grows with the gate
            # count (2,000+ on the worldwide feed) while the others are a
            # handful of keys. Five minutes of lost baseline movement is
            # nothing against a rewrite a minute.
            now_ck = time.time()
            if now_ck - self._gate_stats_saved_at >= 300:
                self._gate_stats_saved_at = now_ck
                station_db_module.save_meta(
                    self._sta_db_path, "prop_gate_stats",
                    json.dumps(self._station_db.export_gate_stats()))
        except Exception as e:
            print(f"[station-db] uptime save failed: {e}", file=sys.__stderr__)

    @staticmethod
    def _log_both(msg: str) -> None:
        """Write to both the web Live Log (sys.stderr, redirected to the
        browser's log queue while the agent is running) and the real
        process stderr (sys.__stderr__, always captured by journald).
        Without this, ops-relevant lines — new silence/propagation alerts,
        episodes clearing — were invisible to `journalctl` for the entire
        time the agent was running, which made auditing "why did the AI
        get called" impossible from the server side, only from the web UI.
        """
        print(msg, file=sys.stderr)
        if sys.stderr is not sys.__stderr__:
            print(msg, file=sys.__stderr__)

    @staticmethod
    def _deepseek_peak_hour() -> bool:
        """True during DeepSeek's announced peak-pricing windows (UTC
        01:00-04:00 and 06:00-10:00), where every billing item costs 2x.
        DeepSeek-specific -- callers must also check the active provider is
        "deepseek", since no other provider has this pricing shape. The
        effective date is "subject to official notice" per DeepSeek, so
        this is dormant (never true in practice) until it actually starts,
        at zero cost to check.
        """
        h = time.gmtime().tm_hour
        return 1 <= h < 4 or 6 <= h < 10

    async def _agent_main(self) -> None:
        try:
            config = cfg_module.load_config(self.config_path)
        except cfg_module.ConfigError as e:
            # Runs on the agent thread: raising here would kill it silently,
            # leaving the UI showing "Running" with nothing behind it.
            self._log_both(f"[config] {e}")
            self._log_both("[config] Agent not started — fix the config file "
                           "and press Start again.")
            return

        ExtensionRegistry.clear()

        if config["extension_server"]["enabled"]:
            ext_store = ext_server_module.start(config)
        else:
            ext_store = ext_server_module.ConStore()

        from extensions.logger_ext import Logger
        from extensions.twitter_ext import Twitter
        from extensions.bluesky_ext import Bluesky
        from extensions.whatsapp_ext import WhatsApp
        from extensions.telegram_ext import Telegram
        from extensions.ai_gateway_ext import AIGateway
        from extensions.imap_ext import ImapReceiver
        from extensions.smtp_ext import SmtpEmailer
        from extensions.fixed_beacon import FixedBeacon

        ext_cfg = config.get("extensions", {})
        pairs = [
            ("twitter",      Twitter,      ext_cfg.get("twitter", {})),
            ("bluesky",      Bluesky,      ext_cfg.get("bluesky", {})),
            ("whatsapp",     WhatsApp,     ext_cfg.get("whatsapp", {})),
            ("telegram",     Telegram,     ext_cfg.get("telegram", {})),
            ("ai_gateway",   AIGateway,    ext_cfg.get("ai_gateway", {})),  # takes config_path too, see below
            ("imap",         ImapReceiver, ext_cfg.get("imap", {})),
            ("logger",       Logger,       ext_cfg.get("logger", {})),
            ("smtp",         SmtpEmailer,  ext_cfg.get("smtp", {})),
            ("fixed_beacon", FixedBeacon,  ext_cfg.get("fixed_beacon", {})),
        ]
        for name, cls, cfg in pairs:
            if cfg.get("enabled"):
                try:
                    # The AI gateway alone gets the config path: it is the one
                    # extension addressable by the whole world, so its
                    # whitelist has to be closeable without a restart.
                    if cls is AIGateway:
                        ext = cls(cfg, self.config_path)
                        # Its own registry, for answering a sender about their
                        # own callsign. Nothing else reads it.
                        ext.set_station_db(self._station_db)
                        ExtensionRegistry.register(ext)
                    else:
                        ExtensionRegistry.register(cls(cfg))
                except Exception as e:
                    print(f"[{name}] Init failed: {e}", file=sys.stderr)

        server_task = asyncio.create_task(
            aprs_connection.start_server(config, ext_store)
        )

        # Silence watch is always on: detection is cheap, and AI/notification
        # steps degrade gracefully when their configs are missing.
        asyncio.create_task(self._silence_watch_loop(config))
        self._log_both("[silence] Silence watch started (first scan in 15m)")

        mon_cfg = config.get("monitor", {})
        if mon_cfg.get("enabled") and config.get("repeater_db_path", "").strip():
            asyncio.create_task(self._monitor_loop(config))
            print("[monitor] Repeater monitor started", file=sys.stderr)
        elif mon_cfg.get("enabled"):
            print("[monitor] WARNING: monitor enabled but repeater_db_path not set", file=sys.stderr)

        sai_cfg = config.get("station_ai", {})
        if sai_cfg.get("enabled"):
            ai_ext = config.get("extensions", {}).get("ai_gateway", {})
            # Station AI reuses the AI Gateway's credentials, so it must be
            # enabled too — matches the silence/propagation ai_ok fix
            # (same reasoning: a provider string alone is not "configured").
            if ai_ext.get("enabled") and (ai_ext.get("provider") or ai_ext.get("base_url")):
                asyncio.create_task(self._ai_analysis_loop(config))
                hours = sai_cfg.get("interval_hours", 24)
                print(f"[station-ai] AI analysis started (every {hours}h, first run in 10m)", file=sys.stderr)
            else:
                print("[station-ai] WARNING: station_ai enabled but ai_gateway not configured/enabled", file=sys.stderr)

        await self._stop_event.wait()
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

        current = asyncio.current_task()
        for task in asyncio.all_tasks():
            if task is not current and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

        print("[agent] stopped.", file=sys.stderr)

    # ── Silence watch: AI assessment + alerting (silence-map phase 4) ────────

    async def _silence_watch_loop(self, config: dict) -> None:
        """Scan for new silence-cell alerts every 5 minutes.

        Each cell alerts once per episode (until it recovers). If the AI
        Gateway is configured, an AI assessment is attached to the cell (shown
        in map popups and stored with history snapshots); if the monitor
        notify channel is configured, an alert message is sent there —
        immediately, or batched into one message every silence_digest_mins.
        """
        mon = config.get("monitor", {})
        channel = mon.get("notify_channel", "")
        digest_mins = max(0, int(mon.get("silence_digest_mins", 0) or 0))
        ai_cfg = config.get("extensions", {}).get("ai_gateway", {})
        # Silence/propagation assessment reuses the AI Gateway's provider
        # config (documented as such), so its "enabled" toggle must be the
        # one master switch that actually stops all auto-triggered AI calls.
        # Previously this only checked whether a provider string was set —
        # "puter" is always present in DEFAULTS, so disabling AI Gateway in
        # the UI silently did NOT stop these calls (confirmed live: 258
        # calls with enabled=false since last restart, burning a fresh
        # Puter key). ai_gateway.enabled is now required.
        ai_ok = bool(ai_cfg.get("enabled")
                    and (ai_cfg.get("provider") or ai_cfg.get("base_url")))

        deepseek = ai_cfg.get("provider") == "deepseek"

        await asyncio.sleep(900)   # let cadence baselines settle first
        while True:
            # DeepSeek-only, and dormant until their peak-pricing actually
            # starts (see _deepseek_peak_hour) -- re-checked every scan since
            # the clock keeps moving, unlike ai_ok above which only changes
            # on a restart.
            peak = deepseek and self._deepseek_peak_hour()
            effective_ai_ok = ai_ok and not peak
            # Warm the quake cache off the event loop; _quakes_near() only
            # ever reads it, so no request handler can block on USGS.
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, _fetch_quakes)
            except Exception:
                pass
            # Off the loop like everything else: this loop runs beside the
            # HTTP handlers, so a synchronous scan here stalls them too.
            cells = await silence_cells_cached(self._station_db, self._sta_db_path)

            # F-35: no feed, no judgement — and no announcements either.
            # Everything below this point either raises an alert or retracts
            # one, and while we cannot hear, a retraction is a false statement.
            # On 2026-08-14 twelve minutes of dead feed produced 28 "cleared",
            # two "[prop] cleared" and five "back on the air" in one second,
            # none of which had happened. Hold every episode exactly as it was.
            deaf_since = self._station_db.deaf_since()
            if deaf_since:
                if not self._silence_deaf_at:
                    self._silence_deaf_at = deaf_since
                    self._log_both(
                        f"[silence] feed deaf since "
                        f"{time.strftime('%H:%M:%S', time.localtime(deaf_since))}"
                        f" — holding {len(self._silence_active)} episode(s), "
                        f"judging nothing")
                await asyncio.sleep(300)
                continue
            if self._silence_deaf_at:
                self._log_both(
                    f"[silence] feed back after "
                    f"{int(time.time() - self._silence_deaf_at)}s — resuming")
                self._silence_deaf_at = 0.0

            alerts = {c["cell"]: c for c in cells if c["alert"]}

            for cell, c in alerts.items():
                if cell in self._silence_active:
                    continue                     # already alerted this episode
                self._silence_active[cell] = time.time()
                for _call in c.get("silent_calls", []):
                    self._missing.setdefault(
                        _call, {"cell": cell, "flagged": time.time()})
                note = ""
                now_ts = time.time()
                cached = self._silence_note_cache.get(cell)
                if cached and now_ts - cached[1] < _AI_NOTE_COOLDOWN_S:
                    # Same cell recently assessed and recovered since — the
                    # verdict (power outage / igate failure) is unlikely to
                    # have changed in the meantime, so reuse it instead of
                    # spending another AI call on a cell that's just flapping.
                    note = cached[0]
                    self._log_both(f"[silence] {cell}: reusing cached AI "
                                   f"note (cooldown, "
                                   f"{int((_AI_NOTE_COOLDOWN_S - (now_ts - cached[1])) / 60)}m left)")
                elif effective_ai_ok:
                    try:
                        note = await self._assess_silence(c, ai_cfg)
                    except Exception as e:
                        self._log_both(f"[silence] AI assessment failed: {e}")
                elif peak and ai_ok:
                    self._log_both(f"[silence] {cell}: skipping AI assessment "
                                   f"(DeepSeek peak-pricing window)")
                if note:
                    self._silence_ai_notes[cell] = note
                    self._silence_note_cache[cell] = (note, now_ts)
                self._log_both(
                    f"[silence] ALERT {cell}: {c['silent']}/{c['baseline']}"
                    f" silent ({c['cause']})")
                if channel:
                    if digest_mins > 0:
                        self._silence_pending.append((time.time(), c, note))
                    else:
                        try:
                            await self._send_notification(
                                self._format_silence_msg(c, note),
                                channel, config)
                        except Exception as e:
                            self._log_both(f"[silence] notification error: {e}")

            # Episode over: cell recovered — allow future re-alerts
            for cell in list(self._silence_active):
                if cell not in alerts:
                    del self._silence_active[cell]
                    self._silence_ai_notes.pop(cell, None)
                    self._log_both(f"[silence] cleared: {cell}")

            # A station leaves the missing list only by being heard again —
            # independent of whether its cell is still alerting.
            if self._missing:
                try:
                    state = self._station_db.silence_state(list(self._missing))
                except Exception:
                    state = {}
                for call in list(self._missing):
                    st = state.get(call)
                    if st is None or not st["silent"]:
                        del self._missing[call]
                        self._log_both(f"[silence] back on the air: {call}")

            # Prune cooled-down cache entries regardless of alert state, so
            # the dict doesn't grow forever with cells that never re-alert.
            now_ts = time.time()
            for cell in list(self._silence_note_cache):
                if now_ts - self._silence_note_cache[cell][1] >= _AI_NOTE_COOLDOWN_S:
                    del self._silence_note_cache[cell]

            # Digest mode: flush the queued alerts as one combined message
            if (digest_mins > 0 and self._silence_pending
                    and time.time() - self._silence_last_flush
                    >= digest_mins * 60):
                msg = self._format_silence_digest(
                    self._silence_pending, digest_mins)
                self._silence_pending = []
                self._silence_last_flush = time.time()
                try:
                    await self._send_notification(msg, channel, config)
                except Exception as e:
                    self._log_both(f"[silence] digest notification error: {e}")

            # ── Propagation openings (same 5-min cadence) ──
            try:
                await self._prop_watch(channel, effective_ai_ok, ai_cfg, config,
                                       peak_skipped=peak and ai_ok)
            except Exception as e:
                self._log_both(f"[prop] watch error: {e}")

            await asyncio.sleep(300)

    async def _prop_watch(self, channel: str, ai_ok: bool,
                          ai_cfg: dict, config: dict,
                          peak_skipped: bool = False) -> None:
        """Group recent anomalous RF links into opening events.

        One long link is never an event — a single misconfigured GPS can
        fake any distance. An opening needs at least two DIFFERENT senders
        in the same Maidenhead field (of the link midpoints) within the
        last 30 minutes. Alerts once per episode; the episode ends when the
        region has produced no anomalous links for a scan.
        """
        from packet_parser import _latlon_to_locator
        now = time.time()
        recent = [l for l in list(self._station_db._prop_links)
                  if now - l["ts"] < 1800]
        # A link whose own position contradicts its own callsign is dropped
        # before the grouping, not after — the group IS the midpoint of the two
        # positions, so a wrong position does not merely weaken the evidence,
        # it files the link under the wrong field. Two such links could invent
        # an opening in a place neither station has ever been.
        #
        # Only a positive contradiction removes a link. `unknown` stays: it
        # means the prefix is not in the table or the identifier is an APRS
        # object name, and dropping those would silence real openings wherever
        # the table happens to be thin. Consistency is weak evidence, and
        # contradiction is the only direction worth acting on.
        #
        # Measured 2026-08-15: 17% of gate-judged anomalies carry a
        # contradicted position, against 2% of floor-only ones — wrong
        # positions concentrate in exactly the extreme tail that looks most
        # like a discovery.
        kept = []
        for l in recent:
            sp = station_db_module.position_corroboration(
                l.get("call"), l.get("s_lat"), l.get("s_lon"))
            gp = station_db_module.position_corroboration(
                l.get("gate"), l.get("g_lat"), l.get("g_lon"))
            if sp.get("consistent") is False or gp.get("consistent") is False:
                bad = l["call"] if sp.get("consistent") is False else l["gate"]
                self._log_both(
                    f"[prop] {l['call']}->{l['gate']} {l['km']:.0f}km excluded "
                    f"from opening grouping: {bad} reports a position outside "
                    f"its own callsign allocation")
                continue
            # A gate that measures the same large distance every time is not
            # reporting propagation, it is reporting one fixed coordinate
            # error. Repeated, it supplies its own "second sender" and
            # manufactures an opening: 3 of 245 stored events over 14 days
            # existed only because of one, and one of those carried the same
            # pair three times (F-2026-08-26-03). The test is on the link
            # rather than the gate — a signature gate measuring a DIFFERENT
            # distance has made a real observation.
            if self._station_db.fixed_geometry_link(l.get("gate", ""),
                                                    l.get("km", 0)):
                self._log_both(
                    f"[prop] {l['call']}->{l['gate']} {l['km']:.0f}km excluded "
                    f"from opening grouping: this gate measures the same "
                    f"distance every time, so the link is its own geometry "
                    f"rather than evidence")
                continue
            kept.append(l)
        recent = kept
        groups: dict[str, list] = {}
        for l in recent:
            mid_lat = (l["s_lat"] + l["g_lat"]) / 2
            mid_lon = (l["s_lon"] + l["g_lon"]) / 2
            region = _latlon_to_locator(mid_lat, mid_lon)[:2]
            groups.setdefault(region, []).append(l)

        for region, ls in groups.items():
            # A link flagged only by the 300 km floor, because its gate had no
            # baseline yet, is a measurement — not evidence of a band opening.
            # It stays on the map under its own class; it does not put a
            # notification on somebody's phone. The operator's call, taken with
            # the numbers in F-43 attached: on a freshly restarted process
            # EVERY gate is young, so an opening built out of these would be
            # announcing the restart, not the ionosphere.
            ls = [l for l in ls
                  if (l.get("at_flag") or {}).get("established", True)]
            if not ls:
                continue
            senders = {l["call"].split("-")[0] for l in ls}
            if len(senders) < 2:
                continue                    # single sender = no event
            if region in self._prop_active:
                continue                    # already alerted this episode
            self._prop_active[region] = now
            note = ""
            cached = self._prop_note_cache.get(region)
            if cached and now - cached[1] < _AI_NOTE_COOLDOWN_S:
                # Same region opened, closed and reopened shortly after — the
                # propagation mode (tropo/sporadic-E) hasn't likely changed,
                # so reuse the verdict instead of spending another AI call.
                note = cached[0]
                self._log_both(f"[prop] {region}: reusing cached AI note "
                               f"(cooldown, "
                               f"{int((_AI_NOTE_COOLDOWN_S - (now - cached[1])) / 60)}m left)")
            elif ai_ok:
                try:
                    note = await self._assess_prop(region, ls, ai_cfg)
                except Exception as e:
                    self._log_both(f"[prop] AI assessment failed: {e}")
            elif peak_skipped:
                self._log_both(f"[prop] {region}: skipping AI assessment "
                               f"(DeepSeek peak-pricing window)")
            if note:
                self._prop_note_cache[region] = (note, now)
                # Attach the note back onto the same dict objects living in
                # station_db's _prop_links deque, so /api/prop (live) shows
                # it too -- otherwise the AI call that generated it (real
                # tokens spent) only ever reached the Telegram/email
                # notification, never the map that prompted the question.
                for l in ls:
                    l["note"] = note
            max_km = max(l["km"] for l in ls)
            self._log_both(f"[prop] OPENING {region}: {len(ls)} links from "
                          f"{len(senders)} senders, max {max_km} km")
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, station_db_module.record_prop_event,
                    self._sta_db_path,
                    {"ts": int(now), "region": region, "note": note,
                     "links": ls})
            except Exception as e:
                self._log_both(f"[prop] history write failed: {e}")
            # Notification is scoped to a region of interest, independent of
            # detection: the map/timeline always show every worldwide
            # opening (already recorded above), but a US↔Western-Europe
            # event is not actionable for an operator who only watches
            # Turkey — pinging them for it just trains them to ignore the
            # channel. Relevant means EITHER end of ANY link in the group
            # falls in the configured grids, so e.g. a South-Africa-to-
            # Turkey opening still notifies (the Turkish gate matches) even
            # though the sender is on another continent.
            notify_grids = config.get("monitor", {}).get(
                "prop_notify_grids", []) or []
            relevant = not notify_grids or any(
                _latlon_to_locator(l["s_lat"], l["s_lon"])[:2] in notify_grids
                or _latlon_to_locator(l["g_lat"], l["g_lon"])[:2] in notify_grids
                for l in ls)
            if channel and relevant:
                try:
                    await self._send_notification(
                        self._format_prop_msg(region, ls, note),
                        channel, config)
                except Exception as e:
                    self._log_both(f"[prop] notification error: {e}")
            elif channel:
                self._log_both(f"[prop] {region} outside prop_notify_grids — "
                               "recorded, not notified")

        # Episode over: region quiet again — allow future re-alerts
        for region in list(self._prop_active):
            if region not in groups:
                del self._prop_active[region]
                self._log_both(f"[prop] cleared: {region}")

        # Prune cooled-down cache entries regardless of alert state
        for region in list(self._prop_note_cache):
            if now - self._prop_note_cache[region][1] >= _AI_NOTE_COOLDOWN_S:
                del self._prop_note_cache[region]

    async def _assess_prop(self, region: str, ls: list,
                           ai_cfg: dict) -> str:
        """Short AI read on an opening: tropo vs sporadic-E vs other."""
        provider = ai_cfg.get("provider", "puter")
        api_key = cfg_module.resolve_ai_api_key(ai_cfg, provider)
        base_url = self._ai_base_url(provider, ai_cfg.get("base_url", ""))
        model = ai_cfg.get("model", "")
        pairs = "\n".join(
            f"- {l['call']} to {l['gate']}: {l['km']} km" for l in ls[:8])
        prompt = (
            "VHF/UHF radio propagation event on the APRS network.\n"
            f"Maidenhead field: {region}\n"
            f"{len(ls)} unusually long station-to-igate RF links in the last "
            f"30 minutes (normal is under ~150 km):\n{pairs}\n"
            f"UTC time: {time.strftime('%H:%M', time.gmtime())}, "
            f"month: {time.strftime('%B', time.gmtime())}.\n"
            "Assess the most likely mode. Return ONLY valid JSON, no prose:\n"
            '{"cause": "<tropo|sporadic_e|aurora|unknown>", '
            '"confidence": "<low|medium|high>", '
            '"summary": "<one short plain-language sentence>"}'
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._call_ai_api(provider, base_url, api_key, model,
                                      prompt))
        if not result:
            return ""
        cause = result.get("cause") or "unknown"
        conf = result.get("confidence") or "low"
        summary = (result.get("summary") or "").strip()
        return f"[{cause}/{conf}] {summary}" if summary else f"[{cause}/{conf}]"

    @staticmethod
    def _format_prop_msg(region: str, ls: list, note: str) -> str:
        max_km = max(l["km"] for l in ls)
        senders = len({l["call"].split("-")[0] for l in ls})
        msg = (f"📡 BAND OPENING — {region}\n"
               f"{len(ls)} long RF links from {senders} stations, "
               f"up to {int(max_km)} km\n")
        msg += "\n".join(
            f"{l['call']} ⇄ {l['gate']} · {int(l['km'])} km"
            for l in ls[:6])
        if note:
            msg += f"\nAI: {note}"
        return msg

    def _cell_context(self, c: dict) -> str:
        """Ground truth for the AI: what the silent stations were saying, and
        who in the same cell is still alive. Lets the model tell an expired
        event advisory or a service feed apart from a real infrastructure
        outage — without this it confidently guessed 'power outage' for a
        cluster of closed fire advisories."""
        cell = c["cell"]
        silent = set(c["silent_calls"])
        sil_lines: list[str] = []
        act_lines: list[str] = []
        act_n = 0
        now = time.time()
        for r in list(self._station_db._stations.values()):
            if not r.locator or r.locator[:4].upper() != cell:
                continue
            if r.callsign in silent:
                if len(sil_lines) < 6:
                    cm = (r.comment or "").strip()[:90]
                    sil_lines.append(
                        f"- {r.callsign} ({r.station_type})"
                        + (f": {cm}" if cm else ""))
            elif (now - r.last_seen) < 3600:
                act_n += 1
                if len(act_lines) < 3:
                    act_lines.append(f"- {r.callsign} ({r.station_type})")
        out = ""
        if sil_lines:
            out += ("Silent station details (type, last comment):\n"
                    + "\n".join(sil_lines) + "\n")
        if act_n:
            out += (f"Stations in the same cell still active: {act_n}, e.g.\n"
                    + "\n".join(act_lines) + "\n")
        return out

    @staticmethod
    def _quake_context(c: dict) -> str:
        """Earthquake candidates as a prompt fragment. Deliberately phrased
        as evidence, not a conclusion: a quake nearby does not prove it
        caused the silence, and the model should still be able to answer
        'event_expired' or 'igate_failure' when the rest of the picture
        says so."""
        qs = _cell_quakes(c["cell"], c.get("since"))
        if not qs:
            return ""
        lines = []
        for q in qs:
            before = int((c["since"] - q["ts"]) / 60) if c.get("since") else 0
            when = (f"{before} minutes before the silence began"
                    if before >= 0 else f"{-before} minutes after")
            lines.append(f"  - {_fmt_quake(q)}, {when}")
        return ("Recent seismic activity near this cell (USGS):\n"
                + "\n".join(lines) + "\n")

    def _onset_context(self, c: dict) -> str:
        """How far apart the stations actually fell silent.

        The note used to assert that stations "went silent simultaneously"
        without ever checking. Sometimes that was true to nine seconds, and
        sometimes the onsets were spread over eleven hours — the opposite
        signature — and the sentence read the same either way. A downstream
        reader then repeated the word while printing the numbers that
        contradicted it. So the spread is measured and stated, and the model is
        told what it means.
        """
        try:
            state = self._station_db.silence_state(c.get("silent_calls") or [])
        except Exception:
            return ""
        onsets = sorted(s["since"] for s in state.values() if s.get("since"))
        if len(onsets) < 2:
            return ""
        spread = int(onsets[-1] - onsets[0])
        if spread < 120:
            human, reading = f"{spread} seconds", (
                "essentially simultaneous — consistent with one shared path "
                "or supply failing at once")
        elif spread < 1800:
            human, reading = f"{spread // 60} minutes", (
                "close together — a shared cause is plausible, though not "
                "the instant drop a single feed failure produces")
        else:
            human = (f"{spread // 3600} hours {(spread % 3600) // 60} minutes"
                     if spread >= 3600 else f"{spread // 60} minutes")
            reading = ("far apart — these stations did NOT go down together, "
                       "which argues against one power or infrastructure "
                       "event and towards independent or gradual causes")
        return (f"Onsets span {human} between the first and last station: "
                f"{reading}.\n")

    def _history_context(self, c: dict) -> str:
        """What this cell has looked like before now.

        Without it the note diagnosed a fortnight-old condition as a fresh
        event, at high confidence, and sent that to the operator's phone.
        """
        try:
            h = station_db_module.cell_silence_history(
                self._sta_db_path, c["cell"], limit=1)
        except Exception:
            return ""
        snaps = h.get("snapshots") or 0
        if not snaps:
            return ("No earlier snapshots stored for this cell: as far as the "
                    "record goes, this is new.\n")
        alerting = h.get("alerting_snapshots") or 0
        seen = (h.get("per_station") or {})
        repeat = [k for k in (c.get("silent_calls") or [])
                  if seen.get(k, 0) >= max(3, snaps // 2)]
        line = (f"This cell has {snaps} stored snapshots, {alerting} of them "
                f"alerting.\n")
        if snaps and alerting == snaps:
            line += ("It has been alerting in EVERY stored snapshot, so this "
                     "state is its normal rather than a change.\n")
        if repeat:
            line += (f"These stations are silent in at least half of those "
                     f"snapshots and are chronically absent rather than newly "
                     f"lost: {', '.join(repeat[:8])}.\n")
        return line

    async def _assess_silence(self, c: dict, ai_cfg: dict) -> str:
        """Ask the AI Gateway to interpret a silence cluster. Returns a short
        note like "[power_outage/high] …summary…" or "" on failure."""
        provider = ai_cfg.get("provider", "puter")
        api_key  = cfg_module.resolve_ai_api_key(ai_cfg, provider)
        base_url = self._ai_base_url(provider, ai_cfg.get("base_url", ""))
        model    = ai_cfg.get("model", "")

        mins = ""
        if c.get("since"):
            mins = f"Silence began ~{max(0, int(time.time() - c['since']) // 60)} minutes ago.\n"
        if c["cause"] == "igate":
            pre = "all silent stations shared one igate which is itself silent"
        elif c["cause"] == "shared_gate":
            pre = (f"all silent stations arrived through one gate "
                   f"({c.get('shared_gate') or 'unknown'}) that this agent "
                   f"cannot see — it never beacons, so its own silence cannot "
                   f"be confirmed. One shared path failing explains this "
                   f"better than a regional outage")
        else:
            pre = "multiple igates involved — infrastructure/power outage possible"
        prompt = (
            "APRS network silence event.\n"
            f"Maidenhead grid cell: {c['cell']}\n"
            f"{c['silent']} of {c['baseline']} recently-active stations are "
            f"silent (ratio {c['ratio']}).\n"
            f"Preliminary signal: {pre}.\n"
            f"Silent stations: {', '.join(c['silent_calls'][:10])}\n"
            f"{mins}"
            f"{self._onset_context(c)}"
            f"{self._history_context(c)}"
            f"{self._cell_context(c)}\n"
            f"{self._quake_context(c)}"
            "Consider that some APRS 'stations' are event advisory objects "
            "(incidents, fire warnings, markers) published by services — "
            "those expire by design when the event closes, which is not an "
            "outage.\n"
            "Assess the most likely cause. Return ONLY valid JSON, no prose:\n"
            '{"cause": "<power_outage|igate_failure|maintenance|propagation'
            '|event_expired|unknown>", '
            '"confidence": "<low|medium|high>", '
            '"summary": "<one short plain-language sentence>"}'
        )
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._call_ai_api(provider, base_url, api_key, model, prompt)
        )
        if not result:
            return ""
        cause = result.get("cause") or "unknown"
        conf = result.get("confidence") or "low"
        summary = (result.get("summary") or "").strip()
        return f"[{cause}/{conf}] {summary}" if summary else f"[{cause}/{conf}]"

    @staticmethod
    def _ai_base_url(provider: str, base_url: str) -> str:
        base_url = (base_url or "").rstrip("/")
        if provider == "puter":
            return base_url or "https://api.puter.com/puterai/openai/v1"
        if provider == "groq":
            return base_url or "https://api.groq.com/openai/v1"
        if provider == "openrouter":
            return base_url or "https://openrouter.ai/api/v1"
        if provider == "openai":
            return base_url or "https://api.openai.com/v1"
        if provider == "deepseek":
            return base_url or "https://api.deepseek.com/v1"
        if provider == "anthropic":
            # Different API shape (see _call_ai_api) — this is the host
            # only, "/v1/messages" is appended there, not "/chat/completions".
            return base_url or "https://api.anthropic.com"
        return base_url

    @staticmethod
    def _format_silence_msg(c: dict, note: str) -> str:
        # A shared gate is a yellow event, not a red one: it says one path
        # went away, which is a smaller claim than a region losing power and
        # is what the evidence usually supports.
        if c["cause"] == "igate":
            icon, cause = "🟡", "IGate failure"
        elif c["cause"] == "shared_gate":
            icon = "🟡"
            cause = (f"One shared gate ({c.get('shared_gate') or '?'}) — "
                     f"not visible to this agent, so its own state is unknown")
        else:
            icon, cause = "🔴", "Regional silence — possible outage"
        msg = (f"{icon} SILENCE ALERT — {c['cell']}\n"
               f"{c['silent']} of {c['baseline']} stations silent "
               f"({int(c['ratio'] * 100)}%)\n{cause}\n"
               f"Stations: {', '.join(c['silent_calls'][:8])}")
        for q in _cell_quakes(c["cell"], c.get("since")):
            msg += f"\n🌍 {_fmt_quake(q)}"
        if note:
            msg += f"\nAI: {note}"
        return msg

    @staticmethod
    def _format_silence_digest(pending: list, digest_mins: int) -> str:
        """One combined notification for all alerts queued since the last
        flush. Telegram caps messages at 4096 chars — stop adding lines
        before that and summarise the rest."""
        head = (f"🔕 SILENCE DIGEST — {len(pending)} new alert"
                f"{'s' if len(pending) != 1 else ''} in the last "
                f"{digest_mins} min")
        lines = []
        for ts, c, note in pending:
            shared = c["cause"] in ("igate", "shared_gate")
            icon = "🟡" if shared else "🔴"
            hhmm = time.strftime("%H:%M", time.localtime(ts))
            tag = (" (igate)" if c["cause"] == "igate"
                   else " (one shared gate)" if c["cause"] == "shared_gate"
                   else "")
            line = (f"{icon} {hhmm} {c['cell']} — {c['silent']}/"
                    f"{c['baseline']} silent{tag}")
            if note:
                line += f"\n   AI: {note}"
            lines.append(line)
        msg = head
        shown = 0
        for line in lines:
            if len(msg) + len(line) + 1 > 3900:
                break
            msg += "\n" + line
            shown += 1
        if shown < len(lines):
            msg += f"\n… and {len(lines) - shown} more"
        return msg

    # ── Repeater monitor ──────────────────────────────────────────────────────

    async def _monitor_loop(self, config: dict) -> None:
        mon = config.get("monitor", {})
        interval = max(1, int(mon.get("check_interval_mins", 10))) * 60
        watch_raw = mon.get("watch_callsigns", [])
        watch = set(w.strip().upper().split("-")[0] for w in watch_raw if w.strip())
        channel = mon.get("notify_channel", "telegram")

        # First sleep lets the agent fill in some stations before first check
        await asyncio.sleep(min(interval, 120))

        while True:
            transitions = self._station_db.check_transitions(watch_filter=watch or None)
            for rec, event in transitions:
                msg = self._format_monitor_msg(rec, event)
                print(f"[monitor] {event.upper()} → {rec.callsign}", file=sys.stderr)
                try:
                    await self._send_notification(msg, channel, config)
                except Exception as e:
                    print(f"[monitor] notification error: {e}", file=sys.stderr)
            await asyncio.sleep(interval)

    @staticmethod
    def _format_monitor_msg(rec: "object", event: str) -> str:
        icon = "🟢" if event == "online" else "🔴"
        loc = ", ".join(p for p in [rec.city, rec.district, rec.ta_region] if p)
        freq = f"{rec.freq_mhz:.4f} MHz" if rec.freq_mhz else ""
        tone = f" T{rec.tone_hz}" if rec.tone_hz else ""
        parts = [p for p in [loc, freq + tone, rec.mode] if p]
        detail = " · ".join(parts) if parts else ""
        ago = ""
        if event == "offline" and rec.last_seen_ago_s is not None:
            h = rec.last_seen_ago_s // 3600
            m = (rec.last_seen_ago_s % 3600) // 60
            ago = f" (last heard {h}h {m:02d}m ago)" if h else f" (last heard {m}m ago)"
        return f"{icon} {rec.callsign} is now {event.upper()}{ago}\n{detail}"

    # ── AI station analysis ───────────────────────────────────────────────────

    async def _ai_analysis_loop(self, config: dict) -> None:
        sai = config.get("station_ai", {})
        interval = max(1, int(sai.get("interval_hours", 24))) * 3600
        max_batch = max(1, int(sai.get("max_batch", 20)))
        ai_cfg = config.get("extensions", {}).get("ai_gateway", {})

        # Initial delay: let the agent accumulate stations first
        await asyncio.sleep(600)
        deepseek = ai_cfg.get("provider") == "deepseek"

        while True:
            if deepseek and self._deepseek_peak_hour():
                # A day-long interval is too coarse to just skip this cycle
                # (would push the next run a full day out) -- wait out the
                # peak window instead, then run as normal.
                self._log_both("[station-ai] DeepSeek peak-pricing window — "
                               "deferring batch until it ends")
                while deepseek and self._deepseek_peak_hour():
                    await asyncio.sleep(1200)
            batch = self._station_db.get_unanalyzed(max_batch)
            if batch:
                print(f"[station-ai] Analysing {len(batch)} station(s)…", file=sys.stderr)
                for rec in batch:
                    try:
                        await self._analyze_one(rec, ai_cfg)
                    except Exception as e:
                        print(f"[station-ai] {rec.callsign}: {e}", file=sys.stderr)
                        rec.ai_analyzed = True  # don't retry on error this session
                    await asyncio.sleep(2)      # polite gap between requests
            await asyncio.sleep(interval)

    # Keywords that suggest the comment carries real station/operational info.
    _OPERATIONAL_RE = re.compile(
        r'(?i)(MHz|Hz|CTCSS|EchoLink|TRAC|dernek|club|kulüb|AKRAD|igate|digi'
        r'|echolink|gateway|beacon|aprs|relay|http|\.net|\.org|\.com)',
    )
    # Patterns that indicate a transient/greeting message — skip AI for these.
    _GREETING_RE = re.compile(
        r'(?i)(kutlu|kutlar|bayram|happy|merry|year|yılbaşı|yeni yıl'
        r'|sevgililer|anneler|babalar|eid|ramazan|merry|good luck)',
    )

    async def _analyze_one(self, rec: "object", ai_cfg: dict) -> None:
        comment = rec.comment.strip()
        # Skip transient greetings or comments with no operational content.
        if self._GREETING_RE.search(comment) and not self._OPERATIONAL_RE.search(comment):
            print(f"[station-ai] {rec.callsign}: skipped (greeting/seasonal)", file=sys.stderr)
            rec.ai_analyzed = True
            return

        provider  = ai_cfg.get("provider", "puter")
        api_key   = cfg_module.resolve_ai_api_key(ai_cfg, provider)
        base_url  = self._ai_base_url(provider, ai_cfg.get("base_url", ""))
        model     = ai_cfg.get("model", "")

        prompt = (
            f"Station callsign: {rec.callsign}\n"
            f"APRS comment: {comment[:300]}\n\n"
            "Extract the following from the APRS comment above and return ONLY valid JSON "
            "with no prose or markdown:\n"
            '{"org": "<organization or club name, null if not found>", '
            '"description": "<one-sentence description of this station, null if not found>"}'
        )

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: self._call_ai_api(provider, base_url, api_key, model, prompt)
        )
        rec.ai_analyzed = True
        if result:
            rec.ai_org = result.get("org") or ""
            rec.ai_description = result.get("description") or ""
            if rec.ai_org or rec.ai_description:
                print(
                    f"[station-ai] {rec.callsign}: org={rec.ai_org!r} desc={rec.ai_description!r}",
                    file=sys.stderr
                )

    def _call_ai_api(self, provider: str, base_url: str, api_key: str,
                     model: str, prompt: str) -> "dict | None":
        # Counts attempts, not successes: quota-wise a request that reaches
        # the provider is spent whether or not the JSON parses.
        self._ai_calls += 1
        import urllib.request, json as _json

        system_msg = ("You extract structured data from APRS beacon text. "
                      "Return ONLY valid JSON, no prose.")

        if provider == "anthropic":
            # Anthropic's Messages API is not OpenAI-compatible: different
            # endpoint, auth header, and request/response shape.
            url = base_url.rstrip("/") + "/v1/messages"
            payload = {
                "model": model or "claude-3-5-haiku-20241022",
                "max_tokens": 120,
                "system": system_msg,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"Content-Type": "application/json",
                       "anthropic-version": "2023-06-01"}
            if api_key:
                headers["x-api-key"] = api_key
            req = urllib.request.Request(
                url, data=_json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())
            text = "".join(
                block.get("text", "") for block in data.get("content", [])
                if block.get("type") == "text")
        else:
            default_models = {
                "puter": "gpt-4o-mini",
                "groq":  "llama-3.1-8b-instant",
                "openai": "gpt-4o-mini",
                # "deepseek-chat" is a legacy alias for this model,
                # deprecating 2026-07-24 -- use the real name directly.
                "deepseek": "deepseek-v4-flash",
            }
            payload = {
                "model": model or default_models.get(provider, ""),
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 120,
                "temperature": 0,
            }
            if provider == "deepseek":
                # deepseek-v4-flash defaults to Thinking Mode on -- the
                # legacy "deepseek-chat"/"deepseek-reasoner" aliases were
                # actually this same model with thinking off/on respectively.
                # Without this, the model spends the whole max_tokens budget
                # on reasoning_content and never reaches the actual JSON
                # answer in content, which then fails to parse -- silently,
                # since an empty/invalid response isn't an exception.
                payload["thinking"] = {"type": "disabled"}
            url = base_url.rstrip("/") + "/chat/completions"

            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            req = urllib.request.Request(
                url, data=_json.dumps(payload).encode(), headers=headers
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = _json.loads(resp.read())

            text = (data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", ""))

        text = text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        try:
            return _json.loads(text)
        except Exception:
            return None

    @staticmethod
    async def _send_notification(msg: str, channel: str, config: dict) -> None:
        loop = asyncio.get_event_loop()
        if channel == "telegram":
            tg = config.get("extensions", {}).get("telegram", {})
            token = tg.get("bot_token", "")
            chat_id = str(tg.get("chat_id", ""))
            if not token or not chat_id:
                print("[monitor] Telegram not configured — cannot send notification", file=sys.stderr)
                return
            import urllib.request, urllib.parse, json as _json
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = _json.dumps({"chat_id": chat_id, "text": msg}).encode()
            req = urllib.request.Request(url, data=payload,
                                         headers={"Content-Type": "application/json"})
            await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))
        elif channel == "smtp":
            smtp_cfg = config.get("extensions", {}).get("smtp", {})
            server_port = smtp_cfg.get("smtp_server", "")
            username = smtp_cfg.get("smtp_username", "")
            password = smtp_cfg.get("smtp_password", "")
            from_email = smtp_cfg.get("from_email", username)
            recipients = smtp_cfg.get("allowed_receiver_emails", [])
            if not server_port or not recipients:
                print("[monitor] SMTP not configured — cannot send notification", file=sys.stderr)
                return
            host, _, port_str = server_port.rpartition(":")
            port = int(port_str) if port_str.isdigit() else 587
            import smtplib, email.mime.text as _mt
            mime = _mt.MIMEText(msg, "plain", "utf-8")
            mime["Subject"] = f"APRS Monitor: {msg.splitlines()[0]}"
            mime["From"] = from_email
            mime["To"] = ", ".join(recipients)
            def _send():
                with smtplib.SMTP(host, port, timeout=10) as s:
                    s.starttls()
                    if username:
                        s.login(username, password)
                    s.sendmail(from_email, recipients, mime.as_string())
            await loop.run_in_executor(None, _send)

    def _build_channel_map(self, config: dict) -> dict[str, str]:
        """Map callsigns to the bridge they belong to, so each message can be
        labelled AI / Telegram / WhatsApp / Email / …

        Both sides are covered: the addressee that triggers an extension
        (incoming) and the callsign an extension sends from (outgoing).
        """
        ext = config.get("extensions", {})
        m: dict[str, str] = {}

        def add(names, label: str) -> None:
            for n in names or []:
                n = str(n).strip().upper()
                if n and n != "N0CALL":
                    m.setdefault(n, label)

        ai = ext.get("ai_gateway", {})
        add([ai.get("callsign", "")] + list(ai.get("trigger_aliases", [])), "AI")
        tg = ext.get("telegram", {})
        add([tg.get("from_callsign", "")] + list(tg.get("allowed_recepients", [])),
            "Telegram")
        wa = ext.get("whatsapp", {})
        add([wa.get("from_callsign", "")] + list(wa.get("allowed_recepients", [])),
            "WhatsApp")
        im = ext.get("imap", {})
        add([im.get("from_callsign", "")], "Email")
        sm = ext.get("smtp", {})
        # smtp spells it "recipients"; the other extensions use "recepients"
        add(list(sm.get("allowed_recipients", []))
            + list(sm.get("allowed_recepients", [])), "Email")
        add(list(ext.get("twitter", {}).get("allowed_recepients", [])), "Twitter")
        add(list(ext.get("bluesky", {}).get("allowed_recepients", [])), "Bluesky")
        return m

    def _track_messages(self, text: str) -> list:
        """Pull APRS messages out of the log stream and store them.

        Incoming messages come from the logger lines; outgoing ones from the
        send loop's '-->' lines, because APRS-IS never echoes our own traffic
        back to us. Returns the newly stored messages (for the WebSocket push).
        """
        new = []
        for direction, raws in (("rx", _SRC_LINE_RE.findall(text)),
                                ("tx", _TX_LINE_RE.findall(text))):
            for raw in raws:
                msg = parse_message(raw)
                # ack/rej and telemetry definitions are machine chatter
                if not msg or msg["kind"] not in ("msg", "bulletin"):
                    continue
                key = (msg["from"], msg["to"], msg["text"], msg["msg_id"])
                last = self._msg_seen.get(key)
                if last is not None and msg["ts"] - last < _MSG_DEDUP_S:
                    continue          # same message gated via another igate
                self._msg_seen[key] = msg["ts"]
                if len(self._msg_seen) > 4 * _MSG_BUFFER:
                    cutoff = msg["ts"] - _MSG_DEDUP_S
                    self._msg_seen = {k: v for k, v in self._msg_seen.items()
                                      if v >= cutoff}
                msg["dir"] = direction
                who = msg["to"] if direction == "rx" else msg["from"]
                msg["channel"] = self._channel_map.get(who.upper(), "APRS")
                self._messages.append(msg)
                new.append(msg)
        return new

    def _track_stations(self, text: str) -> None:
        now = time.time()
        for raw_line in _SRC_LINE_RE.findall(text):
            self._station_db.ingest(raw_line)
        # The agent's own beacon never comes back through APRS-IS, so feed it
        # into the registry from the outbound log line (map-only, no counters).
        for raw_line in _OWN_BEACON_RE.findall(text):
            self._station_db.ingest(raw_line, own=True)
        for call in _SRC_CALL_RE.findall(text):
            self._pkt_count += 1
            if call not in self._seen_calls:
                self._seen_calls.add(call)
                self._unique_count += 1
            base = call.split("-")[0]
            if base not in self._seen_base_calls:
                self._seen_base_calls.add(base)
                self._unique_calls += 1
            entry = self._stations.get(call)
            if entry:
                entry[0] = now
                entry[1] += 1
                self._stations.move_to_end(call)
            else:
                if len(self._stations) >= _MAX_STATIONS:
                    self._stations.popitem(last=False)  # drop least recently heard chip
                self._stations[call] = [now, 1]

    def _count_log_lines(self, text: str) -> None:
        """Tally AI RX/TX and error log lines for the persistent stat counters."""
        for line in text.split("\n"):
            if not line:
                continue
            if "[ai-gateway] RX" in line:
                self._ai_rx += 1
            elif "[ai-gateway] TX" in line:
                self._ai_tx += 1
            elif _AIRESP_MARK in line:
                continue
            elif _AIERR_RE.search(line) or _ERR_RE.search(line):
                self._err_count += 1

    def _stats_payload(self) -> dict:
        now = time.time()
        recent = list(self._stations.items())[-12:]  # 12 most recently heard
        recent.reverse()
        return {
            "type": "stats",
            "running": self.running,
            "uptime": int(now - self._started_at) if self.running and self._started_at else 0,
            "uptime_total": int(self.lifelong_uptime()),
            "packets": self._pkt_count,
            # Named for what it is. "unique" is this run; the registry is
            # what is on record, and the bar used to show only the first
            # under a label that read as the second.
            "unique": self._unique_count,
            "unique_calls": self._unique_calls,
            "registry": self._station_db.count(),
            "received": self._ai_rx,
            "sent": self._ai_tx,
            "errors": self._err_count,
            "stations": [
                {"c": call, "t": int(now - ts), "n": count}
                for call, (ts, count) in recent
            ],
        }

    async def broadcast_logs(self) -> None:
        while True:
            messages = []
            try:
                while True:
                    messages.append(self._log_queue.get_nowait())
            except queue.Empty:
                pass

            payloads = []
            if messages:
                text = "".join(messages)
                text = re.sub(r"\x1b\[[0-9;]*m", "", text)
                self._track_stations(text)
                self._count_log_lines(text)
                payloads.append({"type": "log", "text": text})
                new_msgs = self._track_messages(text)
                if new_msgs:
                    payloads.append({"type": "msgs", "msgs": new_msgs})

            now = time.time()
            if now - self._last_stats_sent >= _STATS_INTERVAL:
                self._last_stats_sent = now
                payloads.append(self._stats_payload())

            # Public viewers get only raw packet lines from the log — the
            # operational lines ([smtp], [telegram], …) may carry private
            # details (addresses, chat ids) and stay admin-only.
            pub_payloads = []
            for p in payloads:
                if p.get("type") == "msgs":
                    # Message bodies can carry private details (mail addresses,
                    # bridge traffic) — admin only.
                    continue
                if p.get("type") != "log":
                    pub_payloads.append(p)
                    continue
                kept = "\n".join(l for l in p["text"].split("\n")
                                 if l.startswith("[logger] "))
                if kept:
                    pub_payloads.append({"type": "log", "text": kept + "\n"})

            for plist, clients in ((payloads, self._ws_clients),
                                   (pub_payloads, self._public_ws)):
                if not plist or not clients:
                    continue
                # Serialize each payload ONCE and send the same text frame to
                # every client, instead of ws.send_json() re-encoding it per
                # client — with many concurrent visitors that redundant
                # json.dumps() was the actual cost, not the network write.
                texts = [json.dumps(p) for p in plist]
                dead: Set[web.WebSocketResponse] = set()
                for ws in list(clients):
                    try:
                        for text in texts:
                            await ws.send_str(text)
                    except Exception:
                        dead.add(ws)
                clients -= dead

            # 500ms batches more log lines per WS frame under heavy traffic
            # (many concurrent visitors, or the full worldwide feed) — the
            # log panel already renders in bulk, so visitors do not
            # perceive the wider tick.
            await asyncio.sleep(0.5)

    def add_ws(self, ws: web.WebSocketResponse, public: bool = False) -> None:
        (self._public_ws if public else self._ws_clients).add(ws)

    def remove_ws(self, ws: web.WebSocketResponse) -> None:
        self._ws_clients.discard(ws)
        self._public_ws.discard(ws)


# ── Routes ──────────────────────────────────────────────────────────────────

routes = web.RouteTableDef()


def _index_response(request: web.Request, public: bool) -> web.Response:
    raw, gz_body, etag = _gzipped_index(public)
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={**_NO_CACHE, "ETag": etag})
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        return web.Response(
            body=gz_body,
            content_type="text/html",
            charset="utf-8",
            headers={**_NO_CACHE, "ETag": etag, "Content-Encoding": "gzip"},
        )
    return web.Response(body=raw, content_type="text/html", charset="utf-8",
                        headers={**_NO_CACHE, "ETag": etag})


@routes.get("/")
async def index(request: web.Request) -> web.Response:
    return _index_response(request, public=False)


async def public_index(request: web.Request) -> web.Response:
    return _index_response(request, public=True)


# ── PWA (installable web app) ───────────────────────────────────────────────

@routes.get("/manifest.json")
async def manifest(request: web.Request) -> web.Response:
    return web.FileResponse(_STATIC_DIR / "manifest.json", headers=_DAY_CACHE)


@routes.get("/sw.js")
async def service_worker(request: web.Request) -> web.Response:
    # Service workers must revalidate so browsers pick up new versions
    return web.FileResponse(_STATIC_DIR / "sw.js", headers=_NO_CACHE)


@routes.get("/icon-{size}.png")
async def pwa_icon(request: web.Request) -> web.Response:
    size = request.match_info["size"]
    if size not in ("192", "512"):
        raise web.HTTPNotFound()
    return web.FileResponse(_STATIC_DIR / f"icon-{size}.png", headers=_REVALIDATE)


@routes.get("/api/info")
async def info(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    try:
        cfg = mgr.get_config()
    except (Exception, SystemExit):
        cfg = {}
    ext_cfg = cfg.get("extensions", {})
    ai_cfg = ext_cfg.get("ai_gateway", {})
    mon_cfg = cfg.get("monitor", {})
    sai_cfg = cfg.get("station_ai", {})
    # Same "enabled AND configured" gate used by the silence/propagation/
    # station-AI loops — this is the one number that answers "is AI actually
    # able to be called right now", independent of any single feature toggle.
    ai_ok = bool(ai_cfg.get("enabled")
                and (ai_cfg.get("provider") or ai_cfg.get("base_url")))
    # "Switched on" and "working" are different claims, and reporting the
    # first as the second cost a day of silent failure (§F). ai_ok answers
    # the first; this answers the second, and answers "nothing has asked it
    # yet" rather than guessing.
    ai_health = {"state": "off", "note": "", "at": 0.0}
    if ai_ok:
        ai_health["state"] = "idle"
        try:
            from extensions import ExtensionRegistry
            for ext in ExtensionRegistry._extensions:
                if ext.name == "ai-gateway":
                    ai_health = dict(ext.health)
                    break
        except Exception:
            pass        # never let a status read break the status endpoint

    data = {
        "version": cfg_module.VERSION,
        "running": mgr.running,
        # Public page header identity (callsign is public by definition — it
        # is beaconed to APRS-IS)
        "callsign": cfg.get("callsign", ""),
        "public_title": cfg.get("public_title", ""),
        "public_subtitle": cfg.get("public_subtitle", ""),
        "public_home_url": cfg.get("public_home_url", ""),
        # Which modules are actually doing something right now — none of
        # this is sensitive (no keys/paths), so it's exposed on the public
        # app too. Kept separate from the "Running" action bar, which the
        # public page hides entirely (it carries Start/Stop/Save commands).
        # Left a plain bool: it means "configured", the loops below depend
        # on exactly that, and widening it here would change what four other
        # readers think they are being told.
        "health": {"ai": ai_health["state"]},
        "active": {
            "ai": ai_ok,
            "station_ai": bool(sai_cfg.get("enabled")) and ai_ok,
            "silence_ai": ai_ok,
            "prop_ai": ai_ok,
            "repeater_monitor": bool(mon_cfg.get("enabled")
                                      and cfg.get("repeater_db_path", "").strip()),
            "full_feed": bool(cfg.get("full_feed")),
            "extension_server": bool(cfg.get("extension_server", {}).get("enabled")),
            "telegram": bool(ext_cfg.get("telegram", {}).get("enabled")),
            "whatsapp": bool(ext_cfg.get("whatsapp", {}).get("enabled")),
            "twitter": bool(ext_cfg.get("twitter", {}).get("enabled")),
            "bluesky": bool(ext_cfg.get("bluesky", {}).get("enabled")),
            "smtp": bool(ext_cfg.get("smtp", {}).get("enabled")),
            "imap": bool(ext_cfg.get("imap", {}).get("enabled")),
        },
    }
    if not request.app.get("public"):
        # The config file path is operator information — admin app only
        data["config_path"] = mgr.config_path
        # Lifetime AI analysis calls (quota watch) — operator info too
        data["ai_calls"] = mgr._ai_calls
        # The reason is written by whatever threw and can carry a request
        # URL, so it stops at the admin app. The state itself is public:
        # somebody messaging this gateway is entitled to know it is broken.
        data["health_note"] = {"ai": ai_health["note"],
                               "at": ai_health["at"]}
    return web.json_response(data)


def _evidence(request: web.Request, payload: dict) -> web.Response:
    """Send an evidence bundle, dropping our own reading when ?blind=1.

    The method these bundles exist for asks for a blind first pass: let an
    outside model reach its own conclusion before it sees ours. Doing that by
    hand meant editing JSON, so it got skipped — and a note read first anchors
    the reader rather than informing them. The whole block goes, not just the
    note: `provider` alone is enough of a fingerprint to tell a reader which
    family wrote the thing they are about to agree with.
    """
    if request.query.get("blind") in ("1", "true", "yes"):
        payload = dict(payload)
        payload.pop("assessment", None)
        payload["assessment_omitted"] = (
            "blind=1 — this station's own reading was removed before export")
    return web.json_response(payload)


@routes.get("/api/counters")
async def counters(request: web.Request) -> web.Response:
    """The headline numbers, for a page that only wants them once.

    The stat bar receives these over the WebSocket, which is right for a page
    already open and watching. An outside page — a landing page, a status
    board — wants three numbers and then nothing, and holding a WebSocket
    open per visitor to deliver that would cost a connection each. Read-only
    counts, nothing here identifies anyone.
    """
    mgr: AgentManager = request.app["manager"]
    s = mgr._stats_payload()
    # "stations" is deliberately the registry, not this run's unique count.
    # The run counters start at zero on every restart, so a page showing one
    # of them says 1,600 a minute after a deploy and 40,000 an hour later
    # while looking like a description of the network. That is the same fault
    # the map's cluster badges had. The run counters are still here, named
    # for what they are, for anyone who wants them.
    db = getattr(mgr, "_station_db", None)
    registry = db.count() if db is not None else None
    return web.json_response({
        "running":       s["running"],
        "stations":      registry,
        "packets":       s["packets"],
        "heard_this_run": s["unique"],
        "calls_this_run": s["unique_calls"],
        "uptime":        s["uptime"],
        "uptime_total":  s["uptime_total"],
    }, headers={"Cache-Control": "public, max-age=30"})


@routes.get("/api/config")
async def get_config(request: web.Request) -> web.Response:
    """The config with every credential masked.

    This endpoint used to hand out bot tokens, mail passwords and every AI key
    in clear text to anything that could reach the admin port — which made any
    foothold in the admin origin, however small, an immediate credential
    harvest. The masked fields round-trip: see save_config below.
    """
    mgr: AgentManager = request.app["manager"]
    return web.json_response(cfg_module.mask_secrets(mgr.get_config()))


@routes.post("/api/config")
async def save_config(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    try:
        data = await request.json()
        # Fields the operator did not retype come back as the mask; restore
        # them from the file instead of writing asterisks over real keys.
        current = mgr.get_config()
        data = cfg_module.unmask_secrets(data, current)
        # The form posts what it renders, not the whole file — see
        # config.apply_partial for what writing it straight out cost.
        data = cfg_module.apply_partial(current, data)
        mgr.save_config(data)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


@routes.post("/api/config-path")
async def set_config_path(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    try:
        data = await request.json()
        new_path = data.get("path", "").strip()
        if new_path:
            mgr.config_path = new_path
        return web.json_response({"ok": True, "config_path": mgr.config_path})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)


@routes.post("/api/clientlog")
async def post_clientlog(request: web.Request) -> web.Response:
    """The page reporting its own failure, so nobody has to be asked to.

    Two days went into an export button that failed on the operator's machine
    and nowhere else. Every server-side measurement said the endpoint answered
    in milliseconds; the page could see which step it had stopped at and had no
    way to say so. Screenshots and DevTools instructions were the substitute,
    and they cost the operator far more than they cost me.

    Admin only (this app is behind the panel's auth, the public app never
    registers this route), same-origin enforced by the middleware, capped, and
    it writes to the journal — no storage, no identifiers, nothing but the
    trace the page already keeps in memory.
    """
    mgr: AgentManager = request.app["manager"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad json"}, status=400)
    what = str(body.get("what", ""))[:40]
    trace = body.get("trace") or []
    if not isinstance(trace, list):
        trace = []
    lines = []
    for e in trace[-25:]:
        if not isinstance(e, dict):
            continue
        lines.append("%s%s" % (str(e.get("step", ""))[:24],
                               ("=" + str(e.get("detail", ""))[:60])
                               if e.get("detail") else ""))
    mgr._log_both("[clientlog] %s | %s" % (what, " -> ".join(lines) or "(empty)"))
    return web.json_response({"ok": True})


@routes.post("/api/start")
async def start_agent(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    ok = mgr.start()
    return web.json_response({"ok": ok, "running": mgr.running})


@routes.post("/api/stop")
async def stop_agent(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    ok = mgr.stop()
    return web.json_response({"ok": ok})


@routes.get("/api/status")
async def get_status(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    return web.json_response({"running": mgr.running})


async def _ws_common(request: web.Request, public: bool) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    mgr: AgentManager = request.app["manager"]
    mgr.add_ws(ws, public=public)
    await ws.send_json({"type": "status", "running": mgr.running})
    await ws.send_json(mgr._stats_payload())
    try:
        async for _ in ws:
            pass
    finally:
        mgr.remove_ws(ws)
    return ws


@routes.get("/ws")
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    return await _ws_common(request, public=False)


async def public_websocket_handler(request: web.Request) -> web.WebSocketResponse:
    return await _ws_common(request, public=True)


# ── WhatsApp webhook ────────────────────────────────────────────────────────

@routes.get("/webhook/whatsapp")
async def wa_webhook_verify(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    cfg = mgr.get_config()
    import hmac as _hmac
    verify_token = cfg.get("extensions", {}).get("whatsapp", {}).get("verify_token", "")
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")
    if (mode == "subscribe" and verify_token
            and _hmac.compare_digest(token, verify_token)):
        return web.Response(text=challenge)
    raise web.HTTPForbidden()


@routes.post("/webhook/whatsapp")
async def wa_webhook_incoming(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    cfg = mgr.get_config()
    import hashlib, hmac as _hmac
    app_secret = cfg.get("extensions", {}).get("whatsapp", {}).get("app_secret", "")
    # An unset app_secret used to mean "accept anything", so whoever could
    # reach this URL could have a message transmitted under the operator's
    # callsign — on their licence. An unverifiable webhook is refused instead.
    if not app_secret:
        print("[whatsapp-webhook] refused: app_secret is not configured",
              file=sys.stderr)
        raise web.HTTPForbidden()
    raw_body = await request.read()
    sig_header = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + _hmac.new(
        app_secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    if not _hmac.compare_digest(expected, sig_header):
        print("[whatsapp-webhook] invalid signature", file=sys.stderr)
        raise web.HTTPForbidden()
    data = json.loads(raw_body)
    try:
        from extensions import ExtensionRegistry
        for ext in ExtensionRegistry._extensions:
            if ext.name == "whatsapp" and hasattr(ext, "process_webhook"):
                await ext.process_webhook(data)
                break
    except Exception as e:
        print(f"[whatsapp-webhook] error: {e}", file=sys.stderr)
    return web.json_response({"ok": True})


@routes.get("/api/stations")
async def get_stations(request: web.Request) -> web.Response:
    """Slim station list for the table and the map. Full records are served
    per-station by /api/stations/{callsign}. Capped so a worldwide feed
    (40k+ stations) cannot produce a 40 MB response every poll."""
    mgr: AgentManager = request.app["manager"]
    try:
        limit = max(0, min(int(request.query.get("limit", 4000)), 20000))
    except ValueError:
        limit = 4000
    bbox = None
    raw_bbox = request.query.get("bbox", "")
    if raw_bbox:
        try:
            s, w, n, e = (float(x) for x in raw_bbox.split(","))
            bbox = (s, w, n, e)
        except (ValueError, TypeError):
            bbox = None
    db = mgr._station_db
    # Rebuilding the slim list walks the whole registry, which on a
    # worldwide feed is seconds of pure CPU — never on the event loop, or
    # every other request (and the WebSocket log) stalls behind it. The lock
    # keeps concurrent pollers from each starting their own rebuild: the
    # first does the work, the rest wait and then find the fresh cache.
    async with _get_slim_lock():
        await asyncio.get_event_loop().run_in_executor(None, db._slim_all)
    # Identical bbox/limit within the same ~2s cache window produce
    # byte-identical JSON — repeat pollers (several browser tabs open on
    # the same view, a visitor's map re-render) can skip the re-send.
    etag = f'"{db.slim_cache_token()}-{limit}-{raw_bbox}"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})
    stations, total = db.get_slim(limit, bbox)
    return web.json_response(
        {"stations": stations, "count": total,
         "capped": total > len(stations)},
        headers={"ETag": etag})


@routes.get("/api/silence")
async def get_silence(request: web.Request) -> web.Response:
    """Maidenhead cells with recently-silent station clusters (map overlay)."""
    mgr: AgentManager = request.app["manager"]
    all_cells = await silence_cells_cached(mgr._station_db, mgr._sta_db_path)
    # Only what the map can draw. The client has always discarded the rest the
    # instant it arrived — it draws on `threshold_met && bounds` and lists on
    # `alert`, and nothing else in the page ever looks at a cell.
    #
    # Measured on the live feed 2026-08-14: 2,135 cells, 1,128,636 bytes, of
    # which 32 were drawn. 98.5% of a megabyte, thrown away on arrival, on a
    # poll that repeats every few seconds — beside /api/stations at 1.3 MB on
    # the same HTTP/2 connection. /api/config is 3 KB and was queueing behind
    # them, which is why the settings panel stayed empty; and `/` lost the
    # service worker's six-second race, so the browser fell back to its cached
    # shell and went on running the previous release's JavaScript. The copy
    # button that "still failed on 3.2.27" was 3.2.26 code, served from a cache
    # that could not be escaped with a hard reload.
    #
    # One filter, 38x smaller.
    cells = [c for c in all_cells if c.get("threshold_met") and c.get("bounds")]
    for c in cells:
        c["ai_note"] = mgr._silence_ai_notes.get(c["cell"], "")
        # "since" is the start of the current alert *episode*, not the
        # longest-silent individual station in the cluster — a cell that
        # recovered and re-alerted should show the new episode's start, not
        # get anchored to one station that never came back.
        episode_start = mgr._silence_active.get(c["cell"])
        if c["alert"] and episode_start:
            c["since"] = int(episode_start)
        # Only alerting cells: _cell_quakes is cheap (one shared cached feed)
        # but the payload is not, on a worldwide feed.
        c["quakes"] = _cell_quakes(c["cell"], c.get("since")) if c["alert"] else []
    # F-35. An empty `cells` used to be the only thing the map was told, and it
    # drew the only conclusion available: nothing is silent anywhere. These two
    # fields let it say the true thing instead — that we cannot hear, since
    # when, and that whatever cells it is showing are the last ones we could
    # actually vouch for.
    deaf_since = mgr._station_db.deaf_since()
    return web.json_response({"cells": cells,
                              # How many were measured, so the filter above is
                              # visible rather than something a reader has to
                              # infer from a number that quietly got smaller.
                              "cells_measured": len(all_cells),
                              "deaf": bool(deaf_since),
                              "deaf_since": int(deaf_since)})


@routes.get("/api/silence/evidence")
async def get_silence_evidence(request: web.Request) -> web.Response:
    """Everything behind one silence cell's map popup, as a portable bundle.

    The popup carries a one-line note from whatever cheap model can afford to
    run automatically over every alerting cell, while the detail that produced
    it exists nowhere but this server. That caps the quality of any reading of
    this data at what the server can pay for, at scale, unattended.

    Exporting the evidence lifts that cap: whoever cares about a given cell can
    re-run the analysis on their own model, on demand, at their cost — which is
    exactly what was done by hand for the Colombia M7.4 case. The bundle is
    self-describing (schema, provenance, detection parameters, generation time)
    so it stays judgeable once it has travelled away from here.
    """
    mgr: AgentManager = request.app["manager"]
    cell = (request.query.get("cell") or "").strip().upper()
    if not cell:
        return web.json_response({"error": "cell parameter required"},
                                 status=400)
    try:
        want_ts = int(request.query.get("ts", "0"))
    except ValueError:
        want_ts = 0

    loop = asyncio.get_event_loop()
    snapshot_ts = None
    if want_ts:
        # Scrubbed to a past moment on the timeline: the cell being looked at
        # is the one in that snapshot, not the one alerting now. Exporting the
        # live cell here would hand over a different event than the one on
        # screen — and refusing outright (the old behaviour) left the reader
        # with no evidence for exactly the moment they were investigating.
        snap = await loop.run_in_executor(
            None, station_db_module.load_silence_history,
            mgr._sta_db_path, want_ts)
        snapshot_ts = snap.get("ts")
        c = next((x for x in (snap.get("cells") or [])
                  if x["cell"] == cell), None)
        if c is None:
            return web.json_response(
                {"error": f"no stored snapshot for {cell} near that time"},
                status=404)
        state = {}          # per-station detail is live-only; see "live_state"
    else:
        cells = await silence_cells_cached(mgr._station_db, mgr._sta_db_path)
        c = next((x for x in cells if x["cell"] == cell), None)
        if c is None:
            # F-35. This 404 is the copy failure the operator kept reporting.
            # While the feed was deaf the cell list was empty, so every cell on
            # their screen answered "no current silence data" — a sentence that
            # blames the cell for a fault in our own input, and one the export
            # button then showed as the reason the copy failed. Say which it is.
            deaf_since = mgr._station_db.deaf_since()
            if deaf_since:
                return web.json_response(
                    {"error": f"no APRS-IS feed for "
                              f"{int(time.time() - deaf_since) // 60} min — "
                              f"cannot see {cell} right now",
                     "deaf": True, "deaf_since": int(deaf_since)},
                    status=503)
            return web.json_response(
                {"error": f"no current silence data for {cell}"}, status=404)
        episode_start = mgr._silence_active.get(cell)
        if c["alert"] and episode_start:
            c["since"] = int(episode_start)
        try:
            state = mgr._station_db.silence_state(c["silent_calls"])
        except Exception:
            state = {}
    # The cell's past. A single frame cannot answer "is this the last station
    # still down after the others came back", which is the first thing anyone
    # asks — and a reader who cannot answer it from the file will invent an
    # answer instead. Off the event loop: it scans this cell's whole history.
    loop = asyncio.get_event_loop()
    try:
        history = await loop.run_in_executor(
            None, station_db_module.cell_silence_history,
            mgr._sta_db_path, cell)
    except Exception:
        history = {}

    now = int(time.time())
    seen_silent = history.get("per_station", {}) if history else {}
    stations = []
    for call in c["silent_calls"]:
        st = state.get(call)
        if not st:
            stations.append({
                "call": call,
                "detail": ("historical snapshot — per-station timing is not "
                           "stored, only the callsign that was silent"
                           if snapshot_ts else "no longer tracked"),
                "silent_in_past_snapshots": seen_silent.get(call, 0),
                "on_still_missing_list": call in mgr._missing,
            })
            continue
        stations.append({
            **st,
            "silent_for_s": max(0, now - st["last_seen"]),
            # Counted across stored snapshots: distinguishes a station that
            # never came back from one that goes quiet regularly.
            "silent_in_past_snapshots": seen_silent.get(call, 0),
            # On the still-missing list = caught in an alert and never heard
            # since. Absent = it did come back, whatever it is doing now.
            "on_still_missing_list": call in mgr._missing,
        })

    try:
        cfg = mgr.get_config()
    except (Exception, SystemExit):
        cfg = {}
    ai_cfg = cfg.get("extensions", {}).get("ai_gateway", {})
    note = mgr._silence_ai_notes.get(cell, "")

    return _evidence(request, {
        "schema": "aprs-agent.silence-evidence/1",
        "generated_at": now,
        # Present when the timeline was scrubbed: this bundle describes the
        # stored snapshot at that moment, not the live cell.
        "snapshot_ts": snapshot_ts,
        "is_historical": bool(snapshot_ts),
        "generated_by": {
            "app": "APRS-Agent", "version": cfg_module.VERSION,
            "station": cfg.get("callsign", ""),
        },
        "cell": c,
        "stations": stations,
        # Sparse by design: only cells with at least one silent station are
        # snapshotted, so a gap means "nothing was silent here", not "not
        # recorded". Stated in the caveats too.
        "cell_history": history,
        # Where the current state sits in this cell's own past, so "is this
        # unusual for here" does not require reading every snapshot row.
        "context": _cell_context_stats(c, history),
        # Which gate each silent station arrived through, and what we know
        # about those gates. When one gate carries all of them, that single
        # line decides the cell — and until now it was not in the file.
        "gates": _gate_evidence(mgr, c),
        "quakes": _quake_evidence(c),
        "assessment": {
            "note": note,
            "automated": True,
            "provider": ai_cfg.get("provider", "") if note else "",
            "model": ai_cfg.get("model", "") if note else "",
        },
        # What selected this cell in the first place. Without it an outside
        # reader cannot tell a 3-of-3 cell (one igate, one power strip) from
        # a 40-of-60 one, and would weigh them the same.
        "detection": {
            "min_silent": 3, "min_ratio": 0.5,
            "station_silent_rule": "gap > 3x the station's own smoothed "
                                   "beacon interval, minimum 15 minutes",
            "quake_radius_km": _QUAKE_RADIUS_KM,
            "quake_window_s": _QUAKE_WINDOW_S,
            # min_silent is applied to `sites` as well as to `silent`, which is
            # what demotes a cell whose callsigns all belong to one operator.
            "site_rule": "distinct operators (base callsign); a cell with "
                         "fewer than min_silent of them cannot alert",
            "site_radius_m": int(station_db_module._SITE_RADIUS_KM * 1000),
        },
        "caveats": [
            "Point-in-time snapshot: the cell may have recovered since "
            "generated_at. Use cell_history for what came before it, and do "
            "not infer a past outage the history does not show.",
            "cell_history is sparse by design: only cells with at least one "
            "silent station are snapshotted, so a gap means nothing was "
            "silent, not that nothing was recorded.",
            "station 'type' comes from the APRS symbol its operator chose. "
            "That symbol is a FIXED SETTING, picked once when the station was "
            "configured: it does not change with conditions and reports "
            "nothing about the weather now. A rain-cloud icon does not mean "
            "it is raining, and a D-Star gateway beaconing a weather symbol "
            "reads as a weather station here.",
            "A quake within the search radius is a candidate, not a cause. "
            "Weigh offset_s: a long gap between quake and silence is "
            "coincidence, not causation.",
            "cell.suspect_position counts how many of the silent stations "
            "beacon a US callsign from an eastern longitude while running "
            "MMDVM/D-Star/Pi-Star firmware — the well-known case of a hotspot "
            "configured without the minus sign on its longitude, which places "
            "a US gateway on the far side of the planet. The packet really "
            "does say E, so this is the sender's error and not a decoding "
            "one, but if this number approaches 'silent' then the cell is not "
            "describing the region it is drawn on and its cause should not be "
            "read as a regional one.",
            "cell.silent counts CALLSIGNS, which are not witnesses. "
            "cell.sites is how many distinct operators those callsigns belong "
            "to — three SSIDs of one base callsign are three radios in one "
            "shack, on one aerial and one power strip, and cannot fail "
            "independently. A cell with sites below min_silent is demoted out "
            "of 'alert' for that reason alone (few_sites), and must not be "
            "read as evidence of a regional event however many callsigns it "
            "holds. cell.sites_colocated additionally merges stations within "
            "detection.site_radius_m of each other; it is REPORTED ONLY and "
            "changes no decision, because a position cannot distinguish one "
            "club site with two callsigns from two neighbours with separate "
            "power.",
            "cell.independent_gates counts gates belonging to somebody else. "
            "cell.self_gated counts silent stations that reached APRS-IS "
            "through their OWN uplink, which means nothing independent ever "
            "observed them. A cell with independent_gates = 0 has no "
            "corroboration at all, whatever its gate list looks like.",
            "No APRS signal is a weak welfare signal, not a confirmed "
            "emergency. Stations go quiet for ordinary reasons.",
            "The assessment note is machine-generated and unreviewed.",
        ],
    })


@routes.get("/api/missing")
async def get_missing(request: web.Request) -> web.Response:
    """Stations still off the air after being caught in a silence alert.

    Triage order is by wall-clock time since the station was actually last
    heard, longest first. The cadence-relative measure (how far past its own
    threshold it is) is the better *detection* signal and is what flags a
    station in the first place — but it makes a confusing triage list: a
    station beaconing hourly is not counted silent for three hours, so it
    can sort below one heard more recently. "Last heard 16 hours ago" is
    the number a human responder acts on, and the one that went into the
    Colombia report.
    """
    mgr: AgentManager = request.app["manager"]
    try:
        state = mgr._station_db.silence_state(list(mgr._missing))
    except Exception:
        state = {}
    out = []
    for call, meta in mgr._missing.items():
        st = state.get(call)
        if not st or not st["silent"]:
            continue
        out.append({**st, "cell": meta.get("cell", ""),
                    "flagged": int(meta.get("flagged", 0))})
    out.sort(key=lambda s: s["last_seen"])
    # Measured 2026-08-15: 135 KB, seven times in two minutes, every one a full
    # body, because this endpoint had no validator at all while /api/stations
    # beside it answered 14 of 19 polls with a 304. The list changes only when
    # a station is flagged or comes back — minutes apart — so almost every poll
    # can be free. Hashing the built payload is the honest validator here: it
    # cannot go stale or claim a match that is not one, and at this size it
    # costs well under a millisecond.
    body = json.dumps({"missing": out}, separators=(",", ":"))
    etag = '"' + hashlib.sha1(body.encode("utf-8")).hexdigest()[:24] + '"'
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={"ETag": etag})
    return web.Response(body=body.encode("utf-8"),
                        content_type="application/json",
                        headers={"ETag": etag})


@routes.get("/api/prop")
async def get_prop(request: web.Request) -> web.Response:
    """RF propagation: recent anomalous links + calibration statistics."""
    mgr: AgentManager = request.app["manager"]
    try:
        data = mgr._station_db.prop_summary()
    except Exception:
        data = {"links": [], "total_links": 0, "anomalous": 0,
                "gates": 0, "deaf_gates": 0, "deaf": [], "hist": []}
    return web.json_response(data)


def _prop_position_corroboration(link: dict) -> dict:
    """The third question, which had no evidence at all until now.

    Six outside readings agreed the physical reality of a link could not be
    established, all at about 95% confidence, all for the same reason: both
    coordinates are self-reported and nothing corroborated them. That is a
    correct answer and a useless one, and it was the file's fault — the one
    independent fact available was never offered.

    A callsign prefix is allocated by country. The station's own transmitted
    position either falls inside that allocation or does not. The two
    directions are NOT symmetric and the reading below says so:

      consistent   weak corroboration. It rules out a position invented at
                   random; it does not rule out an error inside the right
                   country, which is most errors.
      inconsistent ambiguous. A wrong position and an operator transmitting
                   away from home look identical from here.
      0,0          not ambiguous at all: an unset GPS, and any distance
                   computed from it is meaningless.
    """
    sender = station_db_module.position_corroboration(
        link.get("call"), link.get("s_lat"), link.get("s_lon"))
    gate = station_db_module.position_corroboration(
        link.get("gate"), link.get("g_lat"), link.get("g_lon"))
    both = [sender.get("consistent"), gate.get("consistent")]
    if False in both:
        verdict = "contradicted"
        reading = (
            "At least one end reports a position outside the area its own "
            "callsign is allocated to, so the distance between them may not be "
            "a distance between those two places at all. This does not prove "
            "the link is bogus — an operator away from home looks exactly the "
            "same — but it is the one thing here that argues against taking "
            "the geometry at face value."
        )
    elif both == [True, True]:
        verdict = "both_consistent"
        reading = (
            "Both stations report positions inside the areas their own "
            "callsigns are allocated to. Two independent allocations agreeing "
            "with two self-reported positions is weak corroboration: it rules "
            "out coordinates invented at random, and it does not rule out an "
            "error inside the right country. Treat it as the difference "
            "between 'unverified' and 'unverified but not obviously wrong' — "
            "not as confirmation that RF crossed this path."
        )
    elif True in both:
        verdict = "one_consistent"
        reading = (
            "One end agrees with its own callsign's allocation and the other "
            "cannot be checked — an unrecognised prefix, or an APRS object "
            "name rather than a callsign. Half of the geometry has weak "
            "corroboration and half has none."
        )
    else:
        verdict = "unknown"
        reading = (
            "Neither end can be checked against a callsign allocation, so this "
            "adds nothing to the physical question: the distance rests "
            "entirely on what the two stations said about themselves."
        )
    return {"sender": sender, "gate": gate, "verdict": verdict,
            "reading": reading,
            "method": "callsign prefix allocation vs the station's own "
                      "reported position; weak evidence in the positive "
                      "direction, ambiguous in the negative"}


def _prop_opening_status(event: dict | None, ctx: dict) -> dict:
    """Which of the three situations `opening: null` used to cover (F-09).

    Six outside readings treated a null `opening` as "this was not an
    opening". Two of those three states do not support that: the rule can be
    met right now with nothing written — the episode was already active, or
    the link was excluded from the grouping — and a link older than the ring
    simply cannot be answered either way. Only the third is the absence a
    reader was inferring.
    """
    if event:
        return {
            "state": "recorded",
            "reading": ("this link belongs to a stored opening event: two or "
                        "more distinct senders in one field within 30 "
                        "minutes. The event travels in `opening`"),
        }
    fld = ctx.get("in_field") or {}
    if fld.get("rule_met"):
        return {
            "state": "rule_met_not_recorded",
            "reading": ("two or more distinct senders are in this field "
                        "inside the window, but no event was written. That "
                        "happens when the episode was already open, or when "
                        "a link was excluded from the grouping — a "
                        "contradicted position, or a gate's own repeated "
                        "geometry. This is NOT evidence that nothing "
                        "happened here"),
        }
    if not ctx.get("field"):
        return {
            "state": "unknown",
            "reading": ("this link carries no usable pair of positions, so "
                        "no field could be computed and the rule could not "
                        "be evaluated either way"),
        }
    # `<= 1`, not `== 0`. Caught on the first live bundle after v3.2.91: ten
    # minutes past a restart the ring held exactly one link — the one being
    # asked about — and the state read `single_sender`. "No second sender
    # appeared here" from a buffer whose only entry is the subject is the
    # false absence this whole finding is about, arriving one notch up.
    #
    # The bar is not a tuned threshold: it is "the buffer contains nothing
    # besides the link in question", which is the point at which the process
    # has made no other observation at all.
    if (ctx.get("buffer") or {}).get("anomalous_links_held", 0) <= 1:
        return {
            "state": "unknown",
            "reading": ("the anomalous-link buffer holds nothing besides this "
                        "link — usually a recent restart, which empties it — "
                        "so the absence of other senders here is a fact about "
                        "this process and not about the band"),
        }
    return {
        "state": "single_sender",
        "reading": ("no second distinct sender appears in this field inside "
                    "the window, in what this process still holds. One long "
                    "link is not an opening: a single misconfigured GPS can "
                    "fake any distance"),
    }


def _prop_vs_baseline(link: dict, base: dict, params: dict) -> dict:
    """Put the link's distance and the gate's own figure in one statement.

    This changes no detection. It reports what the numbers already say — most
    importantly, whether the link would still have been flagged had the gate
    been established, because on the live feed 78% of "anomalously long" links
    do not reach twice their own gate's average and 7% are shorter than it.
    """
    km = link.get("km")
    # Flag-time first (F-16). The current baseline has moved since, sometimes
    # all the way back to zero via a restart, and reading it produced two
    # confident opposite verdicts on one physical link an hour apart.
    at = link.get("at_flag") or {}
    ema = at.get("ema_km") or base.get("ema_km", base.get("mean_km"))
    base = dict(base)
    if at.get("ema_km"):
        base["samples"] = at.get("samples", base.get("samples", 0))
        base["established"] = at.get("established", base.get("established"))
    if not km or not ema:
        return {"comparable": False,
                "note": "no baseline figure for this gate, so the distance "
                        "cannot be placed against anything it has heard "
                        "before — see gate_baseline for why"}
    ratio = km / ema
    # The counterfactual, and it belongs to YOUNG gates only: what this gate's
    # own average would have said had it been trusted. 3x the mean is the rule
    # an established gate is held to (station_db._ingest_prop_link).
    est_threshold = 3.0 * ema
    would_survive = km >= est_threshold
    # The bar the decision actually used, off the link. Unlike the figures
    # above it cannot approach zero — the 300 km floor is folded into it — so
    # it is the ratio this bundle and the popup quote.
    thr = at.get("threshold_km")
    bar = at.get("gate_bar_km")
    times_thr = at.get("times_threshold")
    established = bool(base.get("established"))
    floor = float(params.get("min_km", 300.0))
    # Three cases, because two of them were being read out in one sentence and
    # that sentence was false in the third. A gate can be established by sample
    # count while the bar its own history sets sits UNDER the floor — then
    # "would it still be flagged if the gate were established" is not a
    # hypothetical at all, it is arithmetic against a near-zero number, and it
    # printed as corroboration: "3x that figure, which here would be 0 km, so
    # this link clears that bar". Measured on the live feed, this is not the
    # rare case (F-2026-08-16-01b).
    # Off the link when it is there; recomputed only for links recorded
    # before the flag existed.
    gate_decided = at.get("gate_decided")
    if gate_decided is None:
        gate_decided = established and bar is not None and float(bar) >= floor
    if gate_decided:
        reading = (
            "this gate has {n} samples and its own history set the bar at "
            "{b:.0f} km. The link cleared it by {x}x — {km:.0f} km against "
            "{b:.0f} km. That is the comparison the decision actually made."
        ).format(n=base.get("samples", 0), b=float(bar), x=times_thr, km=km)
    elif established:
        reading = (
            "this gate has {n} samples, so it counts as established — but the "
            "bar its own history sets is {b}, below the {f:.0f} km floor, so "
            "the floor is what this link had to clear, and it did by {x}x. "
            "The gate's history decided nothing here. Its average is {e:.1f} "
            "km, and the {r:.0f}x that average this link represents measures "
            "how near zero that average is, not how far the signal went — the "
            "gate next door would have produced a different number for the "
            "same distance."
        ).format(n=base.get("samples", 0),
                 b=("%.1f km" % float(bar)) if bar is not None
                   else "not recorded for this link",
                 f=floor, x=times_thr, e=ema, r=ratio)
    else:
        reading = (
            "{bar}this link is {r:.2f}x the figure this gate has produced so "
            "far ({e:.0f} km). An established gate is only flagged at or "
            "beyond 3x that figure, which here would be {t:.0f} km, so this "
            "link {verdict}. The gate is NOT established ({n} of {need} "
            "samples), so the figure is itself weak — but it is the only "
            "thing measured about this gate, and reading it as no information "
            "at all is how a 12x outlier and a link shorter than its own gate "
            "average come to be described identically."
        ).format(
            bar=("it cleared the {f:.0f} km floor, which is what judged it, "
                 "by {x}x. Against the gate's own figure instead, ".format(
                     f=floor, x=times_thr) if times_thr else ""),
            r=ratio, e=ema, t=est_threshold,
            verdict=("clears that bar and would still be flagged"
                     if would_survive else
                     "does NOT reach it and would not have been flagged"),
            n=base.get("samples", 0),
            need=params.get("gate_min_samples", 20))
    return {
        "comparable": True,
        # What judged it.
        "threshold_km": thr,
        "times_threshold": times_thr,
        "gate_bar_km": bar,
        "gate_history_decided": gate_decided,
        "link_km": km,
        "gate_established": established,
        # The gate's own average, and the ratio to it. Present because it is
        # the only thing measured about a young gate — NOT as a headline.
        "gate_figure_km": round(ema, 1),
        "times_gate_figure": round(ratio, 2),
        # The counterfactual applies to a young gate and nothing else. On an
        # established one the real bar is known, so the question is not open
        # and a number here would only be read as a second opinion.
        "established_threshold_km": (None if established
                                     else round(est_threshold, 1)),
        "would_flag_if_gate_established": (None if established
                                           else would_survive),
        "ratio_note": (
            "quote times_threshold, not times_gate_figure. They answer "
            "different questions and can differ by three orders of magnitude: "
            "the first is how far past the bar the decision used this link "
            "sits, and its denominator can never fall below the {f:.0f} km "
            "floor. The second divides by what this gate usually hears, which "
            "on a gate that mostly hears its neighbours is a number near zero "
            "— one measured link read 5382x that way, and 2696x against the "
            "gate next door for the same distance."
        ).format(f=floor),
        "reading": reading,
    }


@routes.get("/api/prop/evidence")
async def get_prop_evidence(request: web.Request) -> web.Response:
    """Everything behind one propagation link's popup, as a portable bundle.

    The popup shows a distance. On its own that number means nothing: 400 km
    is an ordinary day for a mountain-top gate and a genuine opening for a
    rooftop one. What makes it a finding is the gate's own baseline and the
    fact that a second, unrelated sender did the same thing in the same field
    — and neither of those is on the map. So both travel with the link.
    """
    mgr: AgentManager = request.app["manager"]
    call = (request.query.get("call") or "").strip().upper()
    gate = (request.query.get("gate") or "").strip().upper()
    if not call or not gate:
        return web.json_response(
            {"error": "call and gate parameters required"}, status=400)
    try:
        want_ts = int(request.query.get("ts", "0"))
    except ValueError:
        want_ts = 0

    db = mgr._station_db
    link = None
    ring = [l for l in list(db._prop_links)
            if l.get("call") == call and l.get("gate") == gate]

    # The exact link asked for, before anything else. A sender beaconing every
    # 15 s puts twenty records for the same pair inside the 300 s tolerance
    # below, and the ring was walked newest-first — so a tolerance match
    # answered with a LATER link than the one requested, carrying a later
    # baseline, and every assertion the reader made compared two different
    # events. That is the circle this bundle exists to close, arriving through
    # the door the fix was not applied to: v3.2.81 taught check_prop_bundle to
    # send the timestamp and refuse on a mismatch, and stopped there. Measured
    # on the live feed 2026-08-25: SV6NMP-9 -> SV1TNT-10 answered ts+289 s for
    # six consecutive requests.
    if want_ts:
        link = next((dict(l) for l in reversed(ring)
                     if int(l.get("ts", 0) or 0) == want_ts), None)

    # Fallback, for a ts that came from a stored event rather than from the
    # ring: those are rounded to the event, not to the link. NEAREST within the
    # tolerance, never newest — newest is what produced the bug above.
    if link is None and ring:
        if not want_ts:
            link = dict(ring[-1])
        else:
            near = min(ring, key=lambda l: abs(int(l.get("ts", 0) or 0) - want_ts))
            if abs(int(near.get("ts", 0) or 0) - want_ts) <= 300:
                link = dict(near)

    loop = asyncio.get_event_loop()
    event = await loop.run_in_executor(
        None, station_db_module.find_prop_event,
        mgr._sta_db_path, call, gate, want_ts or int(time.time()))

    if link is None and event:
        # Scrubbed to a past opening: the link is no longer in the live ring
        # buffer, but the stored event still carries it. Same rule as the ring,
        # because this is the second door: an event's link list can hold the
        # same pair more than once — the ±3600 s event window is twelve times
        # the ring's tolerance — and taking the first match is the newest-wins
        # bug wearing a different hat.
        stored = [l for l in event["links"]
                  if l.get("call") == call and l.get("gate") == gate]
        if stored:
            if want_ts:
                stored.sort(key=lambda l: abs(int(l.get("ts", 0) or 0) - want_ts))
            link = dict(stored[0])
    if link is None:
        return web.json_response(
            {"error": f"no propagation link found for {call} via {gate}"},
            status=404)

    try:
        summary = db.prop_summary(max_links=0)
    except Exception:
        summary = {}
    # The counts F-09, F-22 and F-23 all want, read once. A failure here must
    # not cost the reader the rest of the bundle, so it degrades to empty and
    # _prop_opening_status reports "unknown" rather than inventing an absence.
    try:
        ctx = db.prop_link_context(link)
    except Exception as e:
        ctx = {"error": f"context unavailable: {e}"}
    try:
        cfg = mgr.get_config()
    except (Exception, SystemExit):
        cfg = {}
    ai_cfg = cfg.get("extensions", {}).get("ai_gateway", {})
    note = (event or {}).get("note", "") or link.get("note", "")

    return _evidence(request, {
        "schema": "aprs-agent.propagation-evidence/1",
        "generated_at": int(time.time()),
        "generated_by": {
            "app": "APRS-Agent", "version": cfg_module.VERSION,
            "station": cfg.get("callsign", ""),
        },
        "link": link,
        # The number the distance was judged against, AS IT STOOD AT THE FLAG.
        # This name carried the live figure until now, and the live figure
        # includes the event being judged plus everything that arrived after
        # it — 1 to 29 samples on the measured feed (F-2026-08-16-01).
        "gate_baseline": db.gate_baseline_at_flag(link),
        # The same gate as of this export, named for what it is. Both are
        # published because the pair is the finding: a baseline that has moved
        # a long way since the flag is itself worth seeing, and hiding it would
        # trade one silent substitution for another (F-16).
        "gate_baseline_now": db.gate_baseline(gate),
        # The two numbers above, RELATED. They were both already in this file
        # and never in the same sentence, and five independent readings proved
        # what that costs: a link at 0.7x its gate's own average and one at
        # 11.9x drew word-for-word the same verdict at the same confidence.
        # `established: false` was doing all the work in the reader's mind
        # while the figure that separates a real outlier from a non-event sat
        # two lines away, unrelated. So the relation is computed here rather
        # than left as arithmetic the reader is trusted to do — four of four,
        # then five of five, did not do it.
        "vs_gate_baseline": _prop_vs_baseline(link, db.gate_baseline_at_flag(link),
                                              db.prop_detection_params()),
        # The third question every outside reading has had to answer with
        # "unverified": whether the two stations are really where they say.
        "position_corroboration": _prop_position_corroboration(link),
        # The opening this link belongs to, if it was part of one. Absent
        # means the link was anomalous on its own but never met the
        # two-distinct-senders rule — which is not an opening.
        "opening": event,
        # `opening: null` was one word for three different situations, and a
        # reader could not tell them apart: nothing else was heard here, or
        # the rule is met right now and no event was written, or the link
        # simply predates what this process still holds. `state` names which
        # (F-09), and `context` carries the counts it was decided from —
        # including the same question asked of the receiving gate (F-22) and
        # the gate's own anomalous share (F-23).
        "opening_status": _prop_opening_status(event, ctx),
        "context": ctx,
        "detection": db.prop_detection_params(),
        "calibration": {
            "links_measured": summary.get("total_links", 0),
            "anomalous": summary.get("anomalous", 0),
            "gates_with_baselines": summary.get("gates", 0),
            # How many of those can no longer raise a flag at all: their own
            # bar has climbed past the ceiling, so nothing clears it. A reader
            # weighing "no opening was reported here" needs to know some of
            # the gates were incapable of reporting one (F-2026-08-26-01).
            "gates_that_can_no_longer_flag": summary.get("deaf_gates", 0),
            "distance_histogram": summary.get("hist", []),
        },
        "assessment": {
            "note": note, "automated": True,
            "provider": ai_cfg.get("provider", "") if note else "",
            "model": ai_cfg.get("model", "") if note else "",
        },
        "caveats": [
            "One long link is not an opening. The opening rule needs two or "
            "more distinct senders in the same field within 30 minutes, "
            "because a single misconfigured GPS can fake any distance.",
            "An absent `opening` is not the same as a negative finding. Read "
            "`opening_status.state`: only `single_sender` is the absence it "
            "looks like. `rule_met_not_recorded` means the rule IS met and no "
            "event was written, and `unknown` means this process cannot "
            "answer — usually a restart emptied the buffer these counts come "
            "from.",
            "`context.at_this_gate` groups by the receiving gate instead of "
            "by the midpoint field. One gate hearing several unrelated "
            "distant senders is stronger evidence than two links sharing a "
            "midpoint, and the field rule cannot see it. It is reported here "
            "and acted on nowhere: a gate that is not where it says it is "
            "would otherwise manufacture openings out of everything it "
            "hears.",
            "Distance is computed from positions the stations transmitted "
            "themselves. A wrong position produces a wrong distance, and the "
            "station will not know it. position_corroboration checks each "
            "position against the area its own callsign prefix is allocated "
            "to — the only independent fact available here. Read its two "
            "directions differently: agreement is weak evidence, because most "
            "errors land inside the right country anyway, while disagreement "
            "is ambiguous between a wrong position and an operator "
            "transmitting away from home.",
            "The gate baseline is a smoothed average that the link itself "
            "then updates, so a permanently unusual gate slowly becomes its "
            "own normal and stops being flagged. gate_baseline is the figure "
            "as it stood when the flag was raised; gate_baseline_now is the "
            "same gate at export time and will usually differ, because the "
            "judged event and everything after it are folded into it. Judge "
            "the link by the first and read the second as what happened next.",
            "Read vs_gate_baseline before concluding from `established: "
            "false` that nothing is known. On the live feed 78% of flagged "
            "links do not reach twice their own gate's figure and 7% are "
            "SHORTER than it, while a small tail runs to 12x and 19x. Those "
            "are not the same finding, and an unestablished baseline is weak "
            "evidence rather than no evidence.",
            "The assessment note is machine-generated and unreviewed.",
        ],
    })


@routes.get("/api/prop/history")
async def get_prop_history(request: web.Request) -> web.Response:
    """Links of propagation events near ?ts= (map timeline scrubbing)."""
    mgr: AgentManager = request.app["manager"]
    try:
        ts = int(request.query.get("ts", "0"))
    except ValueError:
        ts = 0
    loop = asyncio.get_event_loop()
    links = await loop.run_in_executor(
        None, station_db_module.load_prop_history, mgr._sta_db_path, ts)
    return web.json_response({"links": links})


@routes.get("/api/messages")
async def get_messages(request: web.Request) -> web.Response:
    """Recent APRS messages (newest last). Admin only — not on the public app."""
    mgr: AgentManager = request.app["manager"]
    return web.json_response({"msgs": list(mgr._messages)})


@routes.get("/api/silence/range")
async def get_silence_range(request: web.Request) -> web.Response:
    """Time range of stored silence snapshots (map timeline slider bounds)."""
    mgr: AgentManager = request.app["manager"]
    rng = station_db_module.silence_history_range(mgr._sta_db_path)
    return web.json_response({"range": rng})


@routes.get("/api/silence/history")
async def get_silence_history(request: web.Request) -> web.Response:
    """Silence-cell snapshot nearest to ?ts= (map timeline scrubbing)."""
    mgr: AgentManager = request.app["manager"]
    try:
        ts = int(request.query.get("ts", "0"))
    except ValueError:
        ts = 0
    snap = station_db_module.load_silence_history(mgr._sta_db_path, ts)
    return web.json_response(snap)


@routes.get("/api/stations/{callsign}")
async def get_station(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    callsign = request.match_info["callsign"].upper()
    rec = mgr._station_db.get_one(callsign)
    if rec is None:
        raise web.HTTPNotFound()
    return web.json_response(rec)


@routes.get("/logo.svg")
async def logo_svg(request: web.Request) -> web.Response:
    """The project mark, square-cropped and transparent — one file for the
    dark app header and the light project site alike."""
    svg = _STATIC_DIR / "logo.svg"
    if svg.exists():
        return web.FileResponse(svg, headers=_REVALIDATE)
    raise web.HTTPNotFound()


@routes.get("/favicon.ico")
async def favicon(request: web.Request) -> web.Response:
    ico = _resolve_path("aprs-agent.ico")
    if ico.exists():
        return web.FileResponse(ico, headers=_REVALIDATE)
    raise web.HTTPNotFound()


@routes.get("/aprs-symbols-24-{table}.png")
async def symbols(request: web.Request) -> web.Response:
    table = request.match_info["table"]
    if table not in ("0", "1", "2"):
        raise web.HTTPNotFound()
    img = _resolve_path(f"aprs-symbols-24-{table}.png")
    if img.exists():
        return web.FileResponse(img, headers=_DAY_CACHE)
    raise web.HTTPNotFound()


# ── App lifecycle ───────────────────────────────────────────────────────────

@web.middleware
async def _same_origin_only(request: web.Request, handler):
    """Refuse cross-site state changes.

    The admin panel is protected by a session cookie, and a cookie is attached
    by the browser no matter which site caused the request — so any page the
    operator happens to visit could POST to /api/config or /api/stop. aiohttp
    reads the body as JSON without consulting Content-Type, so such a request
    does not even need a preflight to be accepted.

    Browsers default to SameSite=Lax, which already blocks most of this, but
    that is the browser's policy and not ours. When a request carries an Origin
    that is not ours, it is refused here.

    Server-to-server callers (the WhatsApp webhook) send no Origin at all and
    are unaffected; they authenticate by HMAC instead.
    """
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("Origin")
        if origin:
            from urllib.parse import urlsplit
            src = urlsplit(origin).netloc.lower()
            # ProxyPreserveHost is the norm, but fall back to the forwarded
            # host so a proxy that rewrites Host cannot lock the operator out
            # of their own admin panel.
            allowed = {h.lower() for h in (
                request.headers.get("Host", ""),
                request.headers.get("X-Forwarded-Host", ""),
            ) if h}
            if src and src not in allowed:
                print(f"[web] cross-origin {request.method} {request.path} "
                      f"from {origin} refused", file=sys.stderr)
                raise web.HTTPForbidden(text="cross-origin request refused")
    return await handler(request)


def _build_public_app(mgr: "AgentManager") -> web.Application:
    """Read-only public app: monitoring page + whitelisted GET endpoints.

    Admin endpoints (config read/write, start/stop, webhooks) are simply not
    registered here — this port can be exposed to the internet while the main
    admin port stays on the local network.
    """
    papp = web.Application()
    papp["manager"] = mgr
    papp["public"] = True
    papp.add_routes([
        web.get("/", public_index),
        web.get("/ws", public_websocket_handler),
        web.get("/manifest.json", manifest),
        web.get("/sw.js", service_worker),
        web.get("/icon-{size}.png", pwa_icon),
        web.get("/favicon.ico", favicon),
        web.get("/logo.svg", logo_svg),
        web.get("/aprs-symbols-24-{table}.png", symbols),
        web.get("/api/info", info),
        web.get("/api/counters", counters),
        web.get("/api/status", get_status),
        web.get("/api/stations", get_stations),
        web.get("/api/stations/{callsign}", get_station),
        web.get("/api/silence", get_silence),
        # The evidence behind a popup, for re-analysis elsewhere. Built from
        # the same facts /api/silence and /api/missing already serve, plus the
        # detection parameters and the provider/model name behind the shown
        # note — no keys, no paths, no config.
        web.get("/api/silence/evidence", get_silence_evidence),
        # Same facts /api/silence already exposes (callsigns, positions,
        # silence times), just organised for triage — nothing new is revealed.
        web.get("/api/missing", get_missing),
        web.get("/api/silence/range", get_silence_range),
        web.get("/api/silence/history", get_silence_history),
        web.get("/api/prop", get_prop),
        web.get("/api/prop/evidence", get_prop_evidence),
        web.get("/api/prop/history", get_prop_history),
    ])
    return papp


async def _persist_loop(mgr: "AgentManager") -> None:
    """Flush station records to SQLite once a minute; every 10 minutes also
    record a silence-cell snapshot for the map timeline."""
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, mgr._station_db.save_sqlite, mgr._sta_db_path)
        except Exception as e:
            print(f"[station-db] SQLite save failed: {e}", file=sys.__stderr__)
        if mgr.running:
            # Checkpoint the lifelong counter so a crash costs at most a minute
            await asyncio.get_event_loop().run_in_executor(None, mgr._save_uptime)
        if tick % 10 == 0 and mgr.running:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, mgr._station_db.record_silence_history,
                    mgr._sta_db_path, dict(mgr._silence_ai_notes),
                    dict(mgr._silence_active))
            except Exception as e:
                print(f"[station-db] history snapshot failed: {e}",
                      file=sys.__stderr__)


async def on_startup(app: web.Application) -> None:
    mgr: AgentManager = app["manager"]
    app["log_task"] = asyncio.create_task(mgr.broadcast_logs())
    app["persist_task"] = asyncio.create_task(_persist_loop(mgr))
    # Build the silence-cell cache once, in the background, so the first
    # operator request after a restart is not the one that pays for it. Cold,
    # that rebuild costs about a second on a large registry — long enough for
    # a browser to abandon a clipboard write, which is exactly how the first
    # click after a restart came to fail while every later one worked.
    app["cells_warm_task"] = asyncio.create_task(
        silence_cells_cached(mgr._station_db, mgr._sta_db_path))
    # Optional read-only public server on a separate port. A broken config
    # raises ConfigError; the admin app must still come up so the operator
    # can see the error and fix the file.
    try:
        pport = int(mgr.get_config().get("public_port", 0) or 0)
    except Exception:
        pport = 0
    if pport:
        prunner = web.AppRunner(_build_public_app(mgr))
        await prunner.setup()
        await web.TCPSite(prunner, "0.0.0.0", pport).start()
        app["public_runner"] = prunner
        print(f"[public] Read-only monitoring page → port {pport}",
              file=sys.__stderr__)
    try:
        cfg = mgr.get_config()
        if cfg.get("auto_start_agent", False):
            mgr.start()
    except (Exception, SystemExit):
        pass


async def on_shutdown(app: web.Application) -> None:
    app["log_task"].cancel()
    app["persist_task"].cancel()
    mgr: AgentManager = app["manager"]
    # Close live WebSockets first. Their handlers sit in `async for _ in ws`
    # until the client disconnects, and aiohttp's graceful shutdown waits for
    # them — with a browser attached that wait runs out systemd's stop timeout
    # and the process is SIGKILLed before it can save anything.
    for ws in list(mgr._ws_clients) + list(mgr._public_ws):
        try:
            await ws.close(code=WSCloseCode.GOING_AWAY,
                           message=b"server shutdown")
        except Exception:
            pass
    mgr._ws_clients.clear()
    mgr._public_ws.clear()
    if "public_runner" in app:
        try:
            await app["public_runner"].cleanup()
        except Exception:
            pass
    if mgr.running:
        mgr.stop()
    try:
        mgr._station_db.save_sqlite(mgr._sta_db_path)
        mgr._save_uptime()
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="APRS-Agent Web GUI — browser-based interface",
    )
    parser.add_argument(
        "-c", "--config", default=str(_DEFAULT_CFG),
        help="Path to config file (default: ./aprsconfig.toml)",
    )
    parser.add_argument(
        "-p", "--port", type=int, default=8080,
        help="Web server port (default: 8080)",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Listen address (default: 0.0.0.0 = all interfaces)",
    )
    parser.add_argument(
        "--no-browser", action="store_true",
        help="Don't auto-open browser on startup",
    )
    args = parser.parse_args()

    mgr = AgentManager(args.config)

    app = web.Application(middlewares=[_same_origin_only])
    app["manager"] = mgr
    app.add_routes(routes)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    url = f"http://{'localhost' if args.host in ('0.0.0.0', '::') else args.host}:{args.port}"
    print(f"APRS-Agent Web GUI → {url}", file=sys.__stderr__)

    if sys.platform == "win32" and not args.no_browser:
        def _open():
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    # Bound the graceful-shutdown wait well under systemd's stop timeout, so a
    # stuck connection can never turn a restart into a SIGKILL.
    web.run_app(app, host=args.host, port=args.port, print=None,
                shutdown_timeout=15)


if __name__ == "__main__":
    main()
