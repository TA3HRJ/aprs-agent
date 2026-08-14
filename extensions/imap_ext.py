"""
IMAP Email Receiver Extension
==============================
Polls an IMAP inbox and forwards new emails as APRS messages.

How it works:
1. Connects to an IMAP server at a configurable interval
2. Fetches unread (UNSEEN) emails
3. Parses the subject line: first word = destination callsign,
   rest = message text
4. Sends each email as one or more APRS messages (64-char parts)
5. Marks the email as read (SEEN)

Email subject format:
  TA3HRJ-7 Hello, your beacon is working fine!

Requires IMAP access (Gmail: enable IMAP + use App Password).

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import asyncio
import email
import email.header
import email.utils
import imaplib
from typing import Optional

from . import Extension


def _to_ascii(text: str) -> str:
    tr_map = str.maketrans(
        "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
        "cCgGiIoOsSuUaAiIuU",
    )
    text = text.translate(tr_map)
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _split_message(text: str, max_parts: int = 3) -> list[str]:
    if len(text) <= 64:
        return [text]
    parts: list[str] = []
    remaining = text
    for i in range(max_parts):
        if not remaining:
            break
        if i == max_parts - 1 or len(remaining) <= 64:
            chunk = remaining[:64]
            if len(remaining) > 64:
                cut = remaining[:61].rsplit(" ", 1)[0] or remaining[:61]
                chunk = cut + "..."
            parts.append(chunk)
            break
        cut = remaining[:61].rsplit(" ", 1)[0] or remaining[:61]
        parts.append(cut + " --")
        remaining = remaining[len(cut):].strip()
    return parts


def _decode_header(raw: str) -> str:
    parts = email.header.decode_header(raw)
    decoded = []
    for data, charset in parts:
        if isinstance(data, bytes):
            decoded.append(data.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(data)
    return " ".join(decoded)


def _mask_secret(value: str) -> str:
    if len(value) <= 6:
        return "***"
    return value[:3] + "****" + value[-3:]


class ImapReceiver(Extension):

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self._queue: Optional[asyncio.Queue] = None
        self._msg_counter = 0
        self._poll_task: Optional[asyncio.Task] = None

        server = config.get("imap_server", "")
        self.log(
            f"initialized | server={server} "
            f"| user={config.get('imap_username', '')} "
            f"| password={_mask_secret(config.get('imap_password', ''))} "
            f"| poll={config.get('poll_interval_mins', 5)}min "
            f"| from={config.get('from_callsign', '')}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("imap_server"):
            raise ValueError("IMAP extension: imap_server is required")
        if not cfg.get("imap_username") or not cfg.get("imap_password"):
            raise ValueError("IMAP extension: imap_username and imap_password are required")
        if not cfg.get("from_callsign"):
            raise ValueError("IMAP extension: from_callsign is required")

    @property
    def name(self) -> str:
        return "imap"

    @property
    def is_spawnable(self) -> bool:
        return True

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._queue = q
        # Called again on every APRS-IS reconnect, not just once at startup
        # -- guard against spawning a duplicate poll loop on top of one
        # already running (see the identical fix + full explanation in
        # telegram_ext.py's set_own_writer).
        if self._poll_task is None or self._poll_task.done():
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def handle(self, line: str) -> Optional[bytes]:
        return None

    async def _poll_loop(self) -> None:
        interval = int(self._config.get("poll_interval_mins", 5)) * 60
        self.log(f"polling every {interval // 60} min")
        await asyncio.sleep(10)
        while True:
            try:
                await self._check_inbox()
            except Exception as e:
                self.error(f"poll failed: {type(e).__name__}: {e}")
            await asyncio.sleep(interval)

    async def _check_inbox(self) -> None:
        loop = asyncio.get_running_loop()
        messages = await loop.run_in_executor(None, self._fetch_emails)
        for to_call, subject_text, sender in messages:
            parts = _split_message(_to_ascii(subject_text))
            from_call = self._config.get("from_callsign", "EMAIL-5")
            for i, part in enumerate(parts):
                await self._send_aprs(from_call, to_call, part)
                self.log(f"TX {sender} -> {to_call}: {part}")
                if i < len(parts) - 1:
                    await asyncio.sleep(5)

    def _fetch_emails(self) -> list[tuple[str, str, str]]:
        cfg = self._config
        server_str = cfg.get("imap_server", "imap.gmail.com:993")
        if ":" in server_str:
            host, port_str = server_str.rsplit(":", 1)
            port = int(port_str)
        else:
            host = server_str
            port = 993

        username = cfg["imap_username"]
        password = cfg["imap_password"]
        allowed = [a.strip().lower() for a in cfg.get("allowed_senders", []) if a.strip()]

        results: list[tuple[str, str, str]] = []

        conn = imaplib.IMAP4_SSL(host, port)
        try:
            conn.login(username, password)
            conn.select("INBOX")
            _, data = conn.search(None, "UNSEEN")
            msg_nums = data[0].split()

            for num in msg_nums:
                _, msg_data = conn.fetch(num, "(RFC822)")
                if not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                sender_raw = msg.get("From", "")
                sender_addr = email.utils.parseaddr(sender_raw)[1].lower()

                if allowed and sender_addr not in allowed:
                    conn.store(num, "+FLAGS", "\\Seen")
                    continue

                subject = _decode_header(msg.get("Subject", ""))
                if not subject.strip():
                    conn.store(num, "+FLAGS", "\\Seen")
                    continue

                tokens = subject.strip().split(None, 1)
                if len(tokens) < 2:
                    conn.store(num, "+FLAGS", "\\Seen")
                    continue

                to_call = tokens[0].upper().strip()
                message_text = tokens[1].strip()

                if not any(c.isdigit() for c in to_call):
                    conn.store(num, "+FLAGS", "\\Seen")
                    continue

                if not to_call or not message_text:
                    conn.store(num, "+FLAGS", "\\Seen")
                    continue

                results.append((to_call, message_text, sender_addr))
                conn.store(num, "+FLAGS", "\\Seen")

        finally:
            try:
                conn.logout()
            except Exception:
                pass

        return results

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
