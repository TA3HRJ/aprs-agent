"""
WhatsApp Extension (Bidirectional)
===================================
Forwards APRS messages to WhatsApp and receives WhatsApp messages
as APRS packets via Meta Cloud API webhook.

Outbound (APRS → WhatsApp):
  APRS message addressed to trigger alias (e.g. WASEND) is forwarded
  to the configured WhatsApp recipient.

Inbound (WhatsApp → APRS):
  Requires webhook endpoint on the web server. Messages starting with
  a callsign are forwarded as APRS packets.
  Format: "TA3HRJ-7 Hello from WhatsApp!"

Setup:
  1. Create a Meta Business account at business.facebook.com
  2. Create a WhatsApp Business app at developers.facebook.com
  3. Get phone_number_id and access_token from the dashboard
  4. Set webhook URL to: https://YOUR_SERVER/webhook/whatsapp
  5. Set verify_token to match your config

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import asyncio
import json
import urllib.request
import urllib.error
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid

_GRAPH_API = "https://graph.facebook.com/v25.0"


def _to_ascii(text: str) -> str:
    tr_map = str.maketrans(
        "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
        "cCgGiIoOsSuUaAiIuU",
    )
    text = text.translate(tr_map)
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _mask(v: str) -> str:
    return v[:6] + "****" + v[-4:] if len(v) > 10 else "***"


class WhatsApp(Extension):

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self._queue: Optional[asyncio.Queue] = None
        self._msg_counter = 0

        self.log(
            f"initialized | phone_id={config.get('phone_number_id', '')} "
            f"| token={_mask(config.get('access_token', ''))}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("phone_number_id"):
            raise ValueError("WhatsApp: phone_number_id is required")
        if not cfg.get("access_token"):
            raise ValueError("WhatsApp: access_token is required")

    @property
    def name(self) -> str:
        return "whatsapp"

    @property
    def is_spawnable(self) -> bool:
        return False

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._queue = q

    async def _send_wa(self, phone: str, text: str) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _do():
            url = f"{_GRAPH_API}/{cfg['phone_number_id']}/messages"
            payload = json.dumps({
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": phone,
                "type": "text",
                "text": {"body": text},
            }).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {cfg['access_token']}",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read())

        try:
            result = await loop.run_in_executor(None, _do)
            self.log(f"sent to {phone}: {text[:60]}...")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")[:200]
            self.error(f"send failed: {e.code} {e.reason} — {body}")
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

        phone = cfg.get("recipient_phone", "")
        if not phone:
            self.error("recipient_phone not configured")
            return None

        text = f"{message}\nfrom {sender_full}>{dest},{path}"
        if cfg.get("add_hash_tag", True):
            text += " #APRS"

        await self._send_wa(phone, text)

        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None
        ack = f"{recipient}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\r\n"
        return ack.encode("utf-8")

    # ── Inbound: WhatsApp webhook → APRS ──

    async def process_webhook(self, data: dict) -> None:
        if data.get("object") != "whatsapp_business_account":
            return

        cfg = self._config
        aprs_dest = cfg.get("aprs_destination", "").upper()
        from_call = cfg.get("from_callsign", "").upper()

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    text = msg.get("text", {}).get("body", "").strip()
                    sender_phone = msg.get("from", "")
                    if not text:
                        continue

                    allowed = [a.strip() for a in cfg.get("allowed_phones", []) if a.strip()]
                    if allowed and sender_phone not in allowed:
                        self.warn(f"blocked phone {sender_phone}")
                        continue

                    tokens = text.split(None, 1)
                    if (len(tokens) >= 2
                            and len(tokens[0]) <= 9
                            and any(c.isdigit() for c in tokens[0])):
                        to_call = tokens[0].upper()
                        message = _to_ascii(tokens[1])
                    elif aprs_dest:
                        to_call = aprs_dest
                        message = _to_ascii(text)
                    else:
                        self.warn(f"skipped: no callsign prefix and aprs_destination not set")
                        continue

                    if not message:
                        continue
                    if len(message) > 64:
                        message = message[:61] + "..."

                    self.log(f"RX from WhatsApp ({sender_phone}): {to_call} {message}")
                    await self._send_aprs(from_call, to_call, message)

    def _next_msg_id(self) -> str:
        self._msg_counter = (self._msg_counter + 1) % 999 + 1
        return str(self._msg_counter)

    async def _send_aprs(self, from_call: str, to_call: str, message: str) -> None:
        if not self._queue:
            self.error("no own_writer queue")
            return
        mid = self._next_msg_id()
        pkt = f"{from_call}>APRS,TCPIP*::{to_call:<9}:{message}{{{mid}\r\n"
        await self._queue.put(pkt.encode("utf-8"))
        self.log(f"TX to APRS: {to_call} {message}")
