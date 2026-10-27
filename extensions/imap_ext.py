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
  TA1ABC-7 Hello, your beacon is working fine!

Requires IMAP access (Gmail: enable IMAP + use App Password).

Person to person (allow_links, with `maildir`): the server's own MTA takes
mail for CALL@mail_domain and delivers it to a Maildir this extension reads
and empties. A mail goes on air only when the receiving MTA judged it
`dmarc=pass` for its From domain (Authentication-Results from auth_serv_id)
and that address is linked to a callsign (bridge_links, kind "email", proven
from the radio). It is sent under that callsign, so both ends are licensed
amateurs and the originator is named (KEGM Yön. Md.23/1-c, 1-f, 1-g). The
first line of the body is the text (a reply's quote is left out); anything
else is dropped without an answer - no backscatter.

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations

import asyncio
import email
import email.header
import email.policy
import email.utils
import imaplib
import os
import re
import time
from pathlib import Path
from typing import Optional

from . import Extension
from .bridge_links import looks_like_callsign
from .bridge_source import aprs_origin
from config import TOCALL, aprs_message_text

# A linked address's messages on air per hour
_LINKED_PER_HOUR = 20
# Where a reply's own text ends: the quote and its "On ... wrote:" line
_QUOTE_START = re.compile(
    r"^(>|-{2,}\s*$|_{5,}|On .+ wrote:?$|.+ tarihinde .+ yazd[ıi]:?$|.+ şunu yazdı:?$"
    r"|From: |Kimden: |-----Original Message)", re.I)
_SUBJECT_PREFIX = re.compile(r"^\s*((re|ynt|fw|fwd|ilt|aw|sv|vs)\s*:\s*)+", re.I)


# What the MTA refused at the door, by the reason in its log line (Postfix
# wording). Order matters: the first match names the event.
_MTA_REASONS = (
    ("User unknown", "mta_reject_unknown_recipient"),
    ("Relay access denied", "mta_reject_relay"),
    ("Sender address rejected", "mta_reject_sender"),
    ("Helo command rejected", "mta_reject_helo"),
    ("Client host rejected", "mta_reject_client"),
)


def _mta_event(line: str) -> "Optional[str]":
    if "reject:" in line:
        for text, name in _MTA_REASONS:
            if text in line:
                return name
        return "mta_reject_other"
    if "lost connection after" in line or "too many errors after" in line:
        return "mta_dropped_connection"
    return None


def _authenticated(msg, authserv_id: str, from_domain: str) -> bool:
    """dmarc=pass for from_domain in the topmost Authentication-Results
    header our own MTA wrote. The MTA prepends its headers, so ones a sender
    forged with the same authserv-id sit below it."""
    want = (authserv_id or "").strip().lower()
    if not want or not from_domain:
        return False
    for h in msg.get_all("Authentication-Results") or []:
        v = " ".join(str(h).split())
        serv = v.split(";", 1)[0].strip().split(" ")[0].lower()
        if serv != want:
            continue
        m = re.search(r"\bdmarc=(\w+)", v, re.I)
        if not m:
            continue
        hf = re.search(r"\bheader\.from=([^\s;)]+)", v, re.I)
        return (m.group(1).lower() == "pass" and bool(hf)
                and hf.group(1).lower() == from_domain)
    return False


def _first_line(msg) -> str:
    """The first line the sender wrote, from the plain-text part."""
    part = msg.get_body(preferencelist=("plain",)) if hasattr(msg, "get_body") else None
    if part is None:
        return ""
    try:
        body = part.get_content()
    except Exception:
        return ""
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if _QUOTE_START.match(s):
            return ""
        return s
    return ""


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


def _mask_addr(addr: str) -> str:
    local, _, dom = (addr or "").partition("@")
    return f"{local[:1]}***@{dom}" if dom else "?"


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
        # callsign <-> address links (bridge_links.BridgeLinks), given by the
        # web GUI when allow_links is on
        self._links = None
        self._sent_at: dict = {}        # address -> recent send times
        # events from the reading thread, counted on the event loop
        self._events: list = []
        self._mta_pos: Optional[int] = None     # read position in mta_log
        self._mta_ino = None

        if config.get("maildir"):
            self.log(f"initialized | maildir={config['maildir']} "
                     f"| domain={config.get('mail_domain', '')} "
                     f"| authserv={config.get('auth_serv_id', '')}")
            return
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
        if cfg.get("maildir"):
            # the server's own MTA delivers here; no login, but nothing is
            # believed without its DMARC verdict
            if not cfg.get("auth_serv_id") or not cfg.get("mail_domain"):
                raise ValueError("IMAP extension: maildir needs auth_serv_id and mail_domain")
            return
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

    def set_links(self, links) -> None:
        self._links = links

    def _within_rate(self, addr: str) -> bool:
        now = time.time()
        recent = [x for x in self._sent_at.get(addr, []) if now - x < 3600]
        if len(recent) >= _LINKED_PER_HOUR:
            self._sent_at[addr] = recent
            return False
        recent.append(now)
        self._sent_at[addr] = recent
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
        if self._config.get("maildir"):
            # a local directory: cheap to look at, so every 20 s
            interval = int(self._config.get("poll_interval_secs", 20))
            self.log(f"reading {self._config['maildir']} every {interval}s")
            while True:
                try:
                    await self._check_maildir()
                except Exception as e:
                    self.error(f"maildir read failed: {type(e).__name__}: {e}")
                await asyncio.sleep(interval)
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
            # An e-mail sender has no callsign until addresses are linked to
            # calls, so this is always the gateway form: from the bridge's
            # callsign, the sender's address opening the text (bridge_source).
            src, text, _used = aprs_origin(self._config, sender, _to_ascii(subject_text),
                                           limit=None)
            from_call = src or self._config.get("from_callsign", "EMAIL-5")
            parts = _split_message(text)
            for i, part in enumerate(parts):
                await self._send_aprs(from_call, to_call, part)
                self.log(f"TX {sender} -> {to_call}: {part}")
                if i < len(parts) - 1:
                    await asyncio.sleep(5)

    # ── Maildir: person to person through the server's own MTA ──

    async def _check_maildir(self) -> None:
        loop = asyncio.get_running_loop()
        got = await loop.run_in_executor(None, self._read_maildir)
        if self._config.get("mta_log"):
            await loop.run_in_executor(None, self._read_mta_log)
        events, self._events = self._events, []
        for e, w in events:
            self.count(e, w)
        for src, to_call, text, who in got:
            self.count("mail_in", who)
            parts = _split_message(text)
            for i, part in enumerate(parts):
                await self._send_aprs(src, to_call, part)
                if i < len(parts) - 1:
                    await asyncio.sleep(5)
            self.log(f"TX {who} -> {to_call} by e-mail ({len(parts)} part(s))")

    def _read_mta_log(self) -> None:
        """Count what the MTA refused before a mail ever reached the Maildir,
        from the lines of its log added since the last read (`mta_log`: a
        file of the MTA's reject and dropped-connection lines only). Counted
        by reason, nothing else kept. The first read starts at the end: what
        happened before this process is not counted twice."""
        path = Path(self._config["mta_log"])
        try:
            st = path.stat()
        except OSError:
            return
        pos = self._mta_pos
        if pos is None or st.st_ino != self._mta_ino or st.st_size < pos:
            # first look, or the file was rotated or truncated
            pos = st.st_size if pos is None else 0
            self._mta_ino = st.st_ino
        if st.st_size == pos:
            self._mta_pos = pos
            return
        try:
            with open(path, "rb") as f:
                f.seek(pos)
                data = f.read(1 << 20)
        except OSError as e:
            self.error(f"cannot read {path}: {e}")
            return
        # whole lines only; a half-written last line waits for the next read
        end = data.rfind(b"\n") + 1
        self._mta_pos = pos + end
        for line in data[:end].decode("utf-8", "replace").splitlines():
            ev = _mta_event(line)
            if ev:
                self._events.append((ev, ""))   # the reason only

    def _read_maildir(self) -> "list[tuple[str, str, str, str]]":
        """Every new mail is read once and deleted, kept or not: the server
        stores no mail. What goes on air: (source, destination, text, who)."""
        root = Path(self._config["maildir"])
        out = []
        for sub in ("new", "cur"):
            d = root / sub
            if not d.is_dir():
                continue
            for f in sorted(d.iterdir()):
                if not f.is_file():
                    continue
                try:
                    raw = f.read_bytes()
                finally:
                    try:
                        os.remove(f)
                    except OSError as e:
                        self.error(f"cannot delete {f.name}: {e}")
                got = self._judge(raw)
                if got:
                    out.append(got)
        return out

    def _judge(self, raw: bytes) -> "Optional[tuple[str, str, str, str]]":
        cfg = self._config
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        sender = email.utils.parseaddr(str(msg.get("From", "")))[1].lower()
        domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
        who = _mask_addr(sender)
        if not _authenticated(msg, cfg.get("auth_serv_id", ""), domain):
            self._events.append(("mail_in_unauthenticated", who))
            self.warn(f"dropped mail from {who}: no dmarc=pass from our MTA")
            return None
        linked = self._links.by_target("email", sender) if self._links else None
        if not linked:
            self._events.append(("mail_in_unlinked", who))
            self.warn(f"dropped mail from {who}: address not linked to a callsign")
            return None
        # The destination is the address it was delivered to: CALL@domain
        rcpt = email.utils.parseaddr(str(msg.get("Delivered-To", "")
                                         or msg.get("X-Original-To", "")))[1].lower()
        local, _, rdom = rcpt.partition("@")
        if rdom != str(cfg.get("mail_domain", "")).strip().lower() \
                or not looks_like_callsign(local):
            self._events.append(("mail_in_bad_recipient", who))
            self.warn(f"dropped mail from {who}: not to a callsign at the mail domain")
            return None
        to_call = local.upper()
        text = _to_ascii(_first_line(msg))
        if not text:
            subject = _SUBJECT_PREFIX.sub("", _decode_header(str(msg.get("Subject", ""))))
            text = _to_ascii(re.sub(r"^APRS:\s*\S+\s*", "", subject).strip())
        if not text:
            self._events.append(("mail_in_empty", who))
            self.warn(f"dropped mail from {who}: nothing to send")
            return None
        if not self._within_rate(sender):
            self._events.append(("mail_in_rate", who))
            self.warn(f"dropped mail from {who}: {_LINKED_PER_HOUR} an hour")
            return None
        src, text, _used = aprs_origin(cfg, linked["call"], text, limit=None)
        return src, to_call, text, linked["call"]

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
        pkt = f"{from_call}>{TOCALL},TCPIP*::{to_call:<9}:{aprs_message_text(message)}{{{mid}\r\n"
        await self._queue.put(pkt.encode("utf-8"))
