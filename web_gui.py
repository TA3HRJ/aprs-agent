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
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional, Set

from aiohttp import web

import config as cfg_module
import aprs_connection
import extension_server as ext_server_module
from extensions import ExtensionRegistry
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


def _gzipped_index() -> tuple[Path, bytes, str]:
    path = _STATIC_DIR / "index.html"
    st = path.stat()
    key = (st.st_mtime_ns, st.st_size)
    cached = _GZ_CACHE.get("index")
    if not cached or cached[0] != key:
        body = gzip.compress(path.read_bytes(), 9)
        etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
        cached = (key, body, etag)
        _GZ_CACHE["index"] = cached
    return path, cached[1], cached[2]


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

_MAX_STATIONS = 200     # last-heard chip table (most recent N callsigns)
_STATS_INTERVAL = 2.0   # seconds between stats pushes to browsers


class AgentManager:

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.running = False
        self._log_queue: queue.Queue = queue.Queue(maxsize=2000)
        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._thread: Optional[threading.Thread] = None
        self._agent_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._original_stderr = sys.stderr
        # Live stats shown in the browser (packet counter + last-heard stations)
        self._started_at: Optional[float] = None
        self._pkt_count = 0
        self._unique_count = 0          # distinct call+SSID pairs ever heard
        self._unique_calls = 0          # distinct base callsigns (SSID stripped)
        self._stations: "OrderedDict[str, list]" = OrderedDict()  # call -> [last_ts, count]
        self._seen_calls: "set[str]" = set()       # full call+SSID
        self._seen_base_calls: "set[str]" = set()  # base callsign only
        self._last_stats_sent = 0.0
        self._station_db: StationDB = StationDB()

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
        self._stations.clear()
        self._seen_calls.clear()
        self._seen_base_calls.clear()
        self._station_db.reset()
        try:
            cfg = cfg_module.load_config(self.config_path)
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
            self._agent_loop.close()
            self._agent_loop = None

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

    def _track_stations(self, text: str) -> None:
        now = time.time()
        for raw_line in _SRC_LINE_RE.findall(text):
            self._station_db.ingest(raw_line)
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

    def _stats_payload(self) -> dict:
        now = time.time()
        recent = list(self._stations.items())[-12:]  # 12 most recently heard
        recent.reverse()
        return {
            "type": "stats",
            "running": self.running,
            "uptime": int(now - self._started_at) if self.running and self._started_at else 0,
            "packets": self._pkt_count,
            "unique": self._unique_count,
            "unique_calls": self._unique_calls,
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
                payloads.append({"type": "log", "text": text})

            now = time.time()
            if now - self._last_stats_sent >= _STATS_INTERVAL:
                self._last_stats_sent = now
                payloads.append(self._stats_payload())

            if payloads and self._ws_clients:
                dead: Set[web.WebSocketResponse] = set()
                for ws in list(self._ws_clients):
                    try:
                        for payload in payloads:
                            await ws.send_json(payload)
                    except Exception:
                        dead.add(ws)
                self._ws_clients -= dead

            await asyncio.sleep(0.15)

    def add_ws(self, ws: web.WebSocketResponse) -> None:
        self._ws_clients.add(ws)

    def remove_ws(self, ws: web.WebSocketResponse) -> None:
        self._ws_clients.discard(ws)


# ── Routes ──────────────────────────────────────────────────────────────────

routes = web.RouteTableDef()


@routes.get("/")
async def index(request: web.Request) -> web.Response:
    path, gz_body, etag = _gzipped_index()
    if request.headers.get("If-None-Match") == etag:
        return web.Response(status=304, headers={**_NO_CACHE, "ETag": etag})
    if "gzip" in request.headers.get("Accept-Encoding", ""):
        return web.Response(
            body=gz_body,
            content_type="text/html",
            charset="utf-8",
            headers={**_NO_CACHE, "ETag": etag, "Content-Encoding": "gzip"},
        )
    return web.FileResponse(path, headers={**_NO_CACHE, "ETag": etag})


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
    return web.json_response({
        "version": cfg_module.VERSION,
        "config_path": mgr.config_path,
        "running": mgr.running,
    })


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


@routes.get("/ws")
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    mgr: AgentManager = request.app["manager"]
    mgr.add_ws(ws)
    await ws.send_json({"type": "status", "running": mgr.running})
    await ws.send_json(mgr._stats_payload())
    try:
        async for _ in ws:
            pass
    finally:
        mgr.remove_ws(ws)
    return ws


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
    mgr: AgentManager = request.app["manager"]
    stations = mgr._station_db.get_all()
    return web.json_response({"stations": stations, "count": len(stations)})


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
    if table not in ("0", "1"):
        raise web.HTTPNotFound()
    img = _resolve_path(f"aprs-symbols-24-{table}.png")
    if img.exists():
        return web.FileResponse(img, headers=_DAY_CACHE)
    raise web.HTTPNotFound()


# ── App lifecycle ───────────────────────────────────────────────────────────

async def on_startup(app: web.Application) -> None:
    mgr: AgentManager = app["manager"]
    app["log_task"] = asyncio.create_task(mgr.broadcast_logs())
    try:
        cfg = mgr.get_config()
        if cfg.get("auto_start_agent", False):
            mgr.start()
    except Exception:
        pass


async def on_shutdown(app: web.Application) -> None:
    app["log_task"].cancel()
    mgr: AgentManager = app["manager"]
    if mgr.running:
        mgr.stop()


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

    web.run_app(app, host=args.host, port=args.port, print=None)


if __name__ == "__main__":
    main()
