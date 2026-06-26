"""
Telegram Extension (Bidirectional)
===================================
Forwards APRS messages to a Telegram chat and optionally receives
Telegram messages back as APRS packets.

Outbound (APRS → Telegram):
  APRS message addressed to trigger alias (e.g. TGSEND) is forwarded
  to the configured Telegram chat as a bot message.

Inbound (Telegram → APRS):
  Polls the Telegram bot for new messages. Messages starting with a
  callsign are forwarded as APRS packets.
  Format: "TA3HRJ-7 Hello from Telegram!"

Setup:
  1. Message @BotFather on Telegram, create a bot, get the token
  2. Message your bot, then get your chat_id from @userinfobot
  3. Enter bot_token and chat_id in config

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import asyncio
import json
import time
import urllib.request
import urllib.error
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid


def _tg_api(token: str, method: str, params: Optional[dict] = None) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _to_ascii(text: str) -> str:
    tr_map = str.maketrans(
        "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
        "cCgGiIoOsSuUaAiIuU",
    )
    text = text.translate(tr_map)
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _mask(v: str) -> str:
    return v[:4] + "****" + v[-4:] if len(v) > 8 else "***"


class Telegram(Extension):

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self._queue: Optional[asyncio.Queue] = None
        self._msg_counter = 0
        self._last_update_id = 0

        self.log(
            f"initialized | token={_mask(config['bot_token'])} "
            f"| chat_id={config.get('chat_id', '')} "
            f"| poll={'on' if config.get('poll_enabled') else 'off'}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("bot_token"):
            raise ValueError("Telegram: bot_token is required")
        if not cfg.get("chat_id"):
            raise ValueError("Telegram: chat_id is required")

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def is_spawnable(self) -> bool:
        return False

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._queue = q
        if self._config.get("poll_enabled"):
            asyncio.create_task(self._poll_loop())

    async def _send_tg(self, text: str) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _do():
            _tg_api(cfg["bot_token"], "sendMessage", {
                "chat_id": cfg["chat_id"],
                "text": text,
            })

        try:
            await loop.run_in_executor(None, _do)
            self.log(f"sent to Telegram: {text[:60]}...")
        except Exception as e:
            self.error(f"send failed: {type(e).__name__}: {e}")

    async def handle(self, line: str) -> Optional[bytes]:
        cfg = self._config

        if line.startswith("#"):
            return None

        try:
            packet = aprslib.parse(line)
        except Exception:
            return None

        if packet.get("format") != "message":
            return None

        sender_full = packet.get("from", "")
        sender_call = strip_ssid(sender_full)
        if not any(s.upper() == sender_call.upper()
                   for s in cfg.get("allowed_senders", [])):
            return None

        recipient = packet.get("addresse", "").strip()
        if recipient not in cfg.get("allowed_recepients", []):
            return None

        message = packet.get("message_text", "")
        path = ",".join(packet.get("path", []))
        dest = packet.get("to", "")

        text = f"{message}\nfrom {sender_full}>{dest},{path}"
        if cfg.get("add_hash_tag", True):
            text += " #APRS"

        await self._send_tg(text)

        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None
        ack = f"{recipient}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\n"
        return ack.encode("utf-8")

    # ── Inbound: Telegram → APRS ──

    async def _poll_loop(self) -> None:
        interval = int(self._config.get("poll_interval_secs", 5))
        self.log(f"polling Telegram every {interval}s")
        await asyncio.sleep(5)
        while True:
            try:
                await self._check_updates()
            except Exception as e:
                self.error(f"poll error: {type(e).__name__}: {e}")
            await asyncio.sleep(interval)

    async def _check_updates(self) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()
        token = cfg["bot_token"]
        aprs_dest = cfg.get("aprs_destination", "").upper()
        from_call = cfg.get("from_callsign", "").upper() or "TG-BOT"

        def _fetch():
            return _tg_api(token, "getUpdates", {
                "offset": self._last_update_id + 1,
                "timeout": 1,
            })

        result = await loop.run_in_executor(None, _fetch)
        if not result.get("ok"):
            return

        for update in result.get("result", []):
            self._last_update_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            if not text:
                continue

            sender_name = msg.get("from", {}).get("first_name", "TG")

            tokens = text.split(None, 1)
            if len(tokens) >= 2 and len(tokens[0]) <= 9:
                to_call = tokens[0].upper()
                message = _to_ascii(tokens[1])
            elif aprs_dest:
                to_call = aprs_dest
                message = _to_ascii(text)
            else:
                continue

            if not message:
                continue

            if len(message) > 64:
                message = message[:61] + "..."

            self.log(f"RX from Telegram ({sender_name}): {to_call} {message}")
            await self._send_aprs(from_call, to_call, message)

    def _next_msg_id(self) -> str:
        self._msg_counter = (self._msg_counter + 1) % 999 + 1
        return str(self._msg_counter)

    async def _send_aprs(self, from_call: str, to_call: str, message: str) -> None:
        if not self._queue:
            self.error("no own_writer queue")
            return
        mid = self._next_msg_id()
        pkt = f"{from_call}>APRS,TCPIP*::{to_call:<9}:{message}{{{mid}}}\n"
        await self._queue.put(pkt.encode("utf-8"))
        self.log(f"TX to APRS: {to_call} {message}")
