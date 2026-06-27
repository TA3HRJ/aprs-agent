"""
Bluesky Extension
=================
Posts incoming APRS messages to a Bluesky account.

How it works:
1. Monitors the APRS-IS stream for message packets (data type ':')
2. Checks if the sender is in the allowed_senders list
3. Checks if the APRS recipient is in the allowed_recepients list
   (e.g. "BSKYSEND" is a common alias used for this purpose)
4. Posts the message to Bluesky
5. Sends an APRS ACK back to the sender

Requires a Bluesky account and an App Password.
Create App Password at: bsky.app → Settings → App Passwords

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import asyncio
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid

_MAX_CHARS = 300   # Bluesky post character limit


def _mask_secret(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return value[:3] + "****" + value[-3:]


class Bluesky(Extension):
    """
    Forwards APRS messages to Bluesky when addressed to a configured alias.
    Uses atproto library with App Password authentication (no OAuth needed).
    """

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self.log(
            f"Bluesky initialized | user={config['username']} "
            f"| app_password={_mask_secret(config['app_password'])} "
            f"| senders={config['allowed_senders']} "
            f"| recipients={config['allowed_recepients']}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("username"):
            raise ValueError("Bluesky extension: username is required")
        if not cfg.get("app_password"):
            raise ValueError("Bluesky extension: app_password is required")
        if not cfg.get("allowed_recepients") or not cfg.get("allowed_senders"):
            raise ValueError(
                "Bluesky extension: allowed_recepients and allowed_senders cannot be empty"
            )

    @property
    def name(self) -> str:
        return "bluesky"

    @property
    def is_spawnable(self) -> bool:
        return False

    async def _send_post(self, text: str) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _do_post():
            from atproto import Client
            client = Client()
            client.login(cfg["username"], cfg["app_password"])
            client.send_post(text=text[:_MAX_CHARS])

        try:
            await loop.run_in_executor(None, _do_post)
            self.log(f"post sent: {text[:60]}...")
        except Exception as e:
            self.error(f"post error: {type(e).__name__}: {e}")

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

        message  = packet.get("message_text", "")
        path     = ",".join(packet.get("path", []))
        dest     = packet.get("to", "")

        post_text = f"{message}\nfrom {sender_full}>{dest},{path}"
        if cfg.get("add_hash_tag", True):
            post_text += " #APRS"

        await self._send_post(post_text)

        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None

        ack = f"{recipient}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\r\n"
        return ack.encode("utf-8")
