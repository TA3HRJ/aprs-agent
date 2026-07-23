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
import json
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

# In-memory gzip cache for index.html, keyed by file mtime/size so edits
# during development are picked up automatically.
_GZ_CACHE: dict = {}


def _gzipped_index(public: bool = False) -> tuple[bytes, bytes, str]:
    """Return (raw_html, gzipped_html, etag). The public variant injects a
    window.PUBLIC flag so the page renders in read-only view mode."""
    path = _STATIC_DIR / "index.html"
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    ck = "index-pub" if public else "index"
    cached = _GZ_CACHE.get(ck)
    if not cached or cached[0] != key:
        raw = path.read_bytes()
        if public:
            raw = raw.replace(
                b"</head>",
                b"<script>window.PUBLIC=true</script></head>", 1)
        body = gzip.compress(raw, 9)
        suffix = "-p" if public else ""
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}{suffix}"'
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
        # Silence watch (Phase 4): active alert episodes + AI assessments
        self._silence_active: dict[str, float] = {}
        self._silence_ai_notes: dict[str, str] = {}
        # Digest mode: alerts queued here between flushes (list of (ts, cell
        # dict, ai note)); lost on restart, same as the episode state above.
        self._silence_pending: list = []
        self._silence_last_flush = time.time()
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
        except Exception as e:
            print(f"[station-db] uptime save failed: {e}", file=sys.__stderr__)

    async def _agent_main(self) -> None:
        config = cfg_module.load_config(self.config_path)

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
            ("ai_gateway",   AIGateway,    ext_cfg.get("ai_gateway", {})),
            ("imap",         ImapReceiver, ext_cfg.get("imap", {})),
            ("logger",       Logger,       ext_cfg.get("logger", {})),
            ("smtp",         SmtpEmailer,  ext_cfg.get("smtp", {})),
            ("fixed_beacon", FixedBeacon,  ext_cfg.get("fixed_beacon", {})),
        ]
        for name, cls, cfg in pairs:
            if cfg.get("enabled"):
                try:
                    ExtensionRegistry.register(cls(cfg))
                except Exception as e:
                    print(f"[{name}] Init failed: {e}", file=sys.stderr)

        server_task = asyncio.create_task(
            aprs_connection.start_server(config, ext_store)
        )

        # Silence watch is always on: detection is cheap, and AI/notification
        # steps degrade gracefully when their configs are missing.
        asyncio.create_task(self._silence_watch_loop(config))
        print("[silence] Silence watch started (first scan in 15m)",
              file=sys.stderr)

        mon_cfg = config.get("monitor", {})
        if mon_cfg.get("enabled") and config.get("repeater_db_path", "").strip():
            asyncio.create_task(self._monitor_loop(config))
            print("[monitor] Repeater monitor started", file=sys.stderr)
        elif mon_cfg.get("enabled"):
            print("[monitor] WARNING: monitor enabled but repeater_db_path not set", file=sys.stderr)

        sai_cfg = config.get("station_ai", {})
        if sai_cfg.get("enabled"):
            ai_ext = config.get("extensions", {}).get("ai_gateway", {})
            if ai_ext.get("provider") or ai_ext.get("base_url"):
                asyncio.create_task(self._ai_analysis_loop(config))
                hours = sai_cfg.get("interval_hours", 24)
                print(f"[station-ai] AI analysis started (every {hours}h, first run in 10m)", file=sys.stderr)
            else:
                print("[station-ai] WARNING: station_ai enabled but ai_gateway not configured", file=sys.stderr)

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
        ai_ok = bool(ai_cfg.get("provider") or ai_cfg.get("base_url"))

        await asyncio.sleep(900)   # let cadence baselines settle first
        while True:
            try:
                cells = self._station_db.silence_cells()
            except Exception:
                cells = []
            alerts = {c["cell"]: c for c in cells if c["alert"]}

            for cell, c in alerts.items():
                if cell in self._silence_active:
                    continue                     # already alerted this episode
                self._silence_active[cell] = time.time()
                note = ""
                if ai_ok:
                    try:
                        note = await self._assess_silence(c, ai_cfg)
                    except Exception as e:
                        print(f"[silence] AI assessment failed: {e}",
                              file=sys.stderr)
                if note:
                    self._silence_ai_notes[cell] = note
                print(f"[silence] ALERT {cell}: {c['silent']}/{c['baseline']}"
                      f" silent ({c['cause']})", file=sys.stderr)
                if channel:
                    if digest_mins > 0:
                        self._silence_pending.append((time.time(), c, note))
                    else:
                        try:
                            await self._send_notification(
                                self._format_silence_msg(c, note),
                                channel, config)
                        except Exception as e:
                            print(f"[silence] notification error: {e}",
                                  file=sys.stderr)

            # Episode over: cell recovered — allow future re-alerts
            for cell in list(self._silence_active):
                if cell not in alerts:
                    del self._silence_active[cell]
                    self._silence_ai_notes.pop(cell, None)
                    print(f"[silence] cleared: {cell}", file=sys.stderr)

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
                    print(f"[silence] digest notification error: {e}",
                          file=sys.stderr)

            await asyncio.sleep(300)

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

    async def _assess_silence(self, c: dict, ai_cfg: dict) -> str:
        """Ask the AI Gateway to interpret a silence cluster. Returns a short
        note like "[power_outage/high] …summary…" or "" on failure."""
        provider = ai_cfg.get("provider", "puter")
        api_key  = ai_cfg.get("api_key", "")
        base_url = self._ai_base_url(provider, ai_cfg.get("base_url", ""))
        model    = ai_cfg.get("model", "")

        mins = ""
        if c.get("since"):
            mins = f"Silence began ~{max(0, int(time.time() - c['since']) // 60)} minutes ago.\n"
        pre = ("all silent stations shared one igate which is itself silent"
               if c["cause"] == "igate" else
               "multiple igates involved — infrastructure/power outage possible")
        prompt = (
            "APRS network silence event.\n"
            f"Maidenhead grid cell: {c['cell']}\n"
            f"{c['silent']} of {c['baseline']} recently-active stations fell "
            f"silent together (ratio {c['ratio']}).\n"
            f"Preliminary signal: {pre}.\n"
            f"Silent stations: {', '.join(c['silent_calls'][:10])}\n"
            f"{mins}"
            f"{self._cell_context(c)}\n"
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
        return base_url

    @staticmethod
    def _format_silence_msg(c: dict, note: str) -> str:
        icon = "🟡" if c["cause"] == "igate" else "🔴"
        cause = ("IGate failure" if c["cause"] == "igate"
                 else "Regional silence — possible outage")
        msg = (f"{icon} SILENCE ALERT — {c['cell']}\n"
               f"{c['silent']} of {c['baseline']} stations silent "
               f"({int(c['ratio'] * 100)}%)\n{cause}\n"
               f"Stations: {', '.join(c['silent_calls'][:8])}")
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
            icon = "🟡" if c["cause"] == "igate" else "🔴"
            hhmm = time.strftime("%H:%M", time.localtime(ts))
            line = (f"{icon} {hhmm} {c['cell']} — {c['silent']}/"
                    f"{c['baseline']} silent"
                    + (" (igate)" if c["cause"] == "igate" else ""))
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

        while True:
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
        api_key   = ai_cfg.get("api_key", "")
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

    @staticmethod
    def _call_ai_api(provider: str, base_url: str, api_key: str,
                     model: str, prompt: str) -> "dict | None":
        import urllib.request, json as _json

        default_models = {
            "puter": "gpt-4o-mini",
            "groq":  "llama-3.1-8b-instant",
        }
        payload = {
            "model": model or default_models.get(provider, ""),
            "messages": [
                {"role": "system",
                 "content": "You extract structured data from APRS beacon text. "
                            "Return ONLY valid JSON, no prose."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 120,
            "temperature": 0,
        }
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
            "unique": self._unique_count,
            "unique_calls": self._unique_calls,
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
                dead: Set[web.WebSocketResponse] = set()
                for ws in list(clients):
                    try:
                        for payload in plist:
                            await ws.send_json(payload)
                    except Exception:
                        dead.add(ws)
                clients -= dead

            await asyncio.sleep(0.15)

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
    return web.FileResponse(_STATIC_DIR / f"icon-{size}.png", headers=_DAY_CACHE)


@routes.get("/api/info")
async def info(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    try:
        cfg = mgr.get_config()
    except (Exception, SystemExit):
        cfg = {}
    data = {
        "version": cfg_module.VERSION,
        "running": mgr.running,
        # Public page header identity (callsign is public by definition — it
        # is beaconed to APRS-IS)
        "callsign": cfg.get("callsign", ""),
        "public_title": cfg.get("public_title", ""),
        "public_subtitle": cfg.get("public_subtitle", ""),
    }
    if not request.app.get("public"):
        # The config file path is operator information — admin app only
        data["config_path"] = mgr.config_path
    return web.json_response(data)


@routes.get("/api/config")
async def get_config(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    cfg = mgr.get_config()
    return web.json_response(cfg)


@routes.post("/api/config")
async def save_config(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    try:
        data = await request.json()
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
    verify_token = cfg.get("extensions", {}).get("whatsapp", {}).get("verify_token", "")
    mode = request.query.get("hub.mode", "")
    token = request.query.get("hub.verify_token", "")
    challenge = request.query.get("hub.challenge", "")
    if mode == "subscribe" and token == verify_token and verify_token:
        return web.Response(text=challenge)
    raise web.HTTPForbidden()


@routes.post("/webhook/whatsapp")
async def wa_webhook_incoming(request: web.Request) -> web.Response:
    mgr: AgentManager = request.app["manager"]
    cfg = mgr.get_config()
    app_secret = cfg.get("extensions", {}).get("whatsapp", {}).get("app_secret", "")
    if app_secret:
        import hashlib, hmac as _hmac
        raw_body = await request.read()
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + _hmac.new(
            app_secret.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not _hmac.compare_digest(expected, sig_header):
            print("[whatsapp-webhook] invalid signature", file=sys.stderr)
            raise web.HTTPForbidden()
        data = json.loads(raw_body)
    else:
        data = await request.json()
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
    raw = request.query.get("bbox", "")
    if raw:
        try:
            s, w, n, e = (float(x) for x in raw.split(","))
            bbox = (s, w, n, e)
        except (ValueError, TypeError):
            bbox = None
    stations, total = mgr._station_db.get_slim(limit, bbox)
    return web.json_response(
        {"stations": stations, "count": total,
         "capped": total > len(stations)})


@routes.get("/api/silence")
async def get_silence(request: web.Request) -> web.Response:
    """Maidenhead cells with recently-silent station clusters (map overlay)."""
    mgr: AgentManager = request.app["manager"]
    try:
        cells = mgr._station_db.silence_cells()
    except Exception:
        cells = []
    for c in cells:
        c["ai_note"] = mgr._silence_ai_notes.get(c["cell"], "")
        # "since" is the start of the current alert *episode*, not the
        # longest-silent individual station in the cluster — a cell that
        # recovered and re-alerted should show the new episode's start, not
        # get anchored to one station that never came back.
        episode_start = mgr._silence_active.get(c["cell"])
        if c["alert"] and episode_start:
            c["since"] = int(episode_start)
    return web.json_response({"cells": cells})


@routes.get("/api/prop")
async def get_prop(request: web.Request) -> web.Response:
    """RF propagation: recent anomalous links + calibration statistics."""
    mgr: AgentManager = request.app["manager"]
    try:
        data = mgr._station_db.prop_summary()
    except Exception:
        data = {"links": [], "total_links": 0, "anomalous": 0,
                "gates": 0, "hist": []}
    return web.json_response(data)


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


@routes.get("/favicon.ico")
async def favicon(request: web.Request) -> web.Response:
    ico = _resolve_path("aprs-agent.ico")
    if ico.exists():
        return web.FileResponse(ico, headers=_DAY_CACHE)
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
        web.get("/aprs-symbols-24-{table}.png", symbols),
        web.get("/api/info", info),
        web.get("/api/status", get_status),
        web.get("/api/stations", get_stations),
        web.get("/api/stations/{callsign}", get_station),
        web.get("/api/silence", get_silence),
        web.get("/api/silence/range", get_silence_range),
        web.get("/api/silence/history", get_silence_history),
        web.get("/api/prop", get_prop),
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
    # Optional read-only public server on a separate port.
    # load_config() calls sys.exit on a broken file — catch SystemExit too so
    # a config problem can't silently kill the whole web app at startup.
    try:
        pport = int(mgr.get_config().get("public_port", 0) or 0)
    except (Exception, SystemExit):
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

    app = web.Application()
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
