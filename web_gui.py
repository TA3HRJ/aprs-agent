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
import json
import queue
import re
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any, Optional, Set

from aiohttp import web

import config as cfg_module
import aprs_connection
import extension_server as ext_server_module
from extensions import ExtensionRegistry


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


class _QueueWriter:
    def __init__(self, q: queue.Queue):
        self._q = q

    def write(self, text: str) -> None:
        if text:
            self._q.put(text)

    def flush(self) -> None:
        pass


class AgentManager:

    def __init__(self, config_path: str):
        self.config_path = config_path
        self.running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._ws_clients: Set[web.WebSocketResponse] = set()
        self._thread: Optional[threading.Thread] = None
        self._agent_loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._original_stderr = sys.stderr

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
        from extensions.telegram_ext import Telegram
        from extensions.ai_gateway_ext import AIGateway
        from extensions.imap_ext import ImapReceiver
        from extensions.smtp_ext import SmtpEmailer
        from extensions.fixed_beacon import FixedBeacon

        ext_cfg = config.get("extensions", {})
        pairs = [
            ("twitter",      Twitter,      ext_cfg.get("twitter", {})),
            ("bluesky",      Bluesky,      ext_cfg.get("bluesky", {})),
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

    async def broadcast_logs(self) -> None:
        while True:
            messages = []
            try:
                while True:
                    messages.append(self._log_queue.get_nowait())
            except queue.Empty:
                pass

            if messages:
                text = "".join(messages)
                text = re.sub(r"\x1b\[[0-9;]*m", "", text)
                dead: Set[web.WebSocketResponse] = set()
                for ws in list(self._ws_clients):
                    try:
                        await ws.send_json({"type": "log", "text": text})
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
    return web.FileResponse(_STATIC_DIR / "index.html")


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
    try:
        async for _ in ws:
            pass
    finally:
        mgr.remove_ws(ws)
    return ws


@routes.get("/favicon.ico")
async def favicon(request: web.Request) -> web.Response:
    ico = _resolve_path("aprs-agent.ico")
    if ico.exists():
        return web.FileResponse(ico)
    raise web.HTTPNotFound()


@routes.get("/aprs-symbols-24-{table}.png")
async def symbols(request: web.Request) -> web.Response:
    table = request.match_info["table"]
    if table not in ("0", "1"):
        raise web.HTTPNotFound()
    img = _resolve_path(f"aprs-symbols-24-{table}.png")
    if img.exists():
        return web.FileResponse(img)
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
