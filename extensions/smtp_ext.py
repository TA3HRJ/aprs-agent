"""
SMTP Email Extension
====================
Forwards APRS messages to email addresses via an SMTP server.

How it works:
1. Monitors APRS-IS for message packets addressed to a configured alias
   (e.g. "EMAIL")
2. Parses the message body: first word = destination email, rest = email content
   Example APRS message: "friend@example.com Hello, how are you?"
3. Sends an email to that address
4. Sends an APRS ACK back to the original sender

Supports Gmail (use App Password), Outlook, or any standard SMTP server.

Developed by TA3HX & TA3PKS
"""
from __future__ import annotations


import asyncio
import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid


# What the config template ships with. A config still carrying one of these
# was never finished: the extension starts, is reported active, and fails on
# every send. One ran that way from July to September 2026 unnoticed.
_PLACEHOLDERS = ("example.com", "example.org", "example.net", "your@email.com")


def placeholder_fields(cfg: dict) -> list[str]:
    """Names of the settings that still hold a template value."""
    return [key for key in ("smtp_server", "smtp_username", "from_email")
            if any(p in str(cfg.get(key, "")).lower() for p in _PLACEHOLDERS)]


def sender_addresses(cfg: dict) -> tuple[str, str]:
    """(From header, envelope sender) for the configured account.

    `from_email` is free text typed by a person, and the envelope sender must
    be a bare address. An unquoted comma in the display name - "Name, CALL
    <a@b>" - is two mailboxes, and handed to sendmail() as it stood it became
    `MAIL FROM:<Name, CALL <a@b>>`, which no server accepts. A from_email
    that does not parse as exactly one address falls back to the login.
    """
    user = str(cfg.get("smtp_username", ""))
    found = getaddresses([str(cfg.get("from_email", "") or user)])
    if len(found) == 1 and "@" in found[0][1]:
        name, addr = found[0]
        return formataddr((name, addr)), addr
    return user, user


class SmtpEmailer(Extension):
    """Forwards APRS messages to email via SMTP."""

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self.log(
            f"SMTP initialized | server={config['smtp_server']} "
            f"| senders={config['allowed_senders']} "
            f"| recipients={config['allowed_recipients']}"
        )
        bad = placeholder_fields(config)
        if bad:
            self.error(f"{', '.join(bad)} still hold the template's example "
                       f"values - no email can be sent until they are set")
            self.mark_broken("template values: " + ", ".join(bad))

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("allowed_senders") or not cfg.get("allowed_recipients"):
            raise ValueError(
                "SMTP extension: allowed_senders and allowed_recipients cannot be empty"
            )

    @property
    def name(self) -> str:
        return "smtp"

    async def handle(self, line: str) -> Optional[bytes]:
        cfg = self._config

        # Skip comment lines
        if line.startswith("#"):
            return None

        # Parse APRS packet
        try:
            packet = aprslib.parse(line)
        except Exception:
            return None

        # Only handle message packets
        if packet.get("format") != "message":
            return None

        # Check sender
        sender_full = packet.get("from", "")
        sender_call = strip_ssid(sender_full)
        if not any(
            s.upper() == sender_call.upper() for s in cfg.get("allowed_senders", [])
        ):
            return None

        # Check APRS message recipient (addressee)
        recipient = packet.get("addresse", "").strip().upper()
        if not any(
            r.upper() == recipient for r in cfg.get("allowed_recipients", [])
        ):
            return None

        # Parse message body: first word = email address, rest = content
        message_text = packet.get("message_text", "")
        parts = message_text.split(" ", 1)
        if len(parts) < 2:
            self.error(
                f"message from {sender_full} has no email+content format: '{message_text}'"
            )
            return None

        receiver_email, email_content = parts[0], parts[1]

        # Check allowed receiver emails (if configured)
        allowed_emails = cfg.get("allowed_receiver_emails", [])
        if allowed_emails and not any(
            e.upper() == receiver_email.upper() for e in allowed_emails
        ):
            self.error(f"receiver email '{receiver_email}' is not in allowed list")
            return None

        # Send email in a thread to avoid blocking the async loop
        loop = asyncio.get_running_loop()
        success = await loop.run_in_executor(
            None,
            self._send_email,
            receiver_email,
            email_content,
            sender_full,
            cfg,
        )

        if not success:
            return None

        # Build and return APRS ACK packet
        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None

        path = ",".join(packet.get("path", []))
        dest = packet.get("to", "")
        ack = f"{dest}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\r\n"
        return ack.encode("utf-8")

    def _send_email(
        self, to_addr: str, content: str, aprs_sender: str, cfg: dict
    ) -> bool:
        """Blocking SMTP send - runs in a thread executor."""
        try:
            smtp_server = cfg.get("smtp_server", "")
            if ":" not in smtp_server:
                self.error(f"Invalid smtp_server format '{smtp_server}'. Use 'host:port'")
                return False

            host, port_str = smtp_server.rsplit(":", 1)
            port = int(port_str)

            msg = MIMEText(content)
            msg["Subject"] = (
                f"APRS message from {aprs_sender} via APRS-Agent"
            )
            header_from, envelope_from = sender_addresses(cfg)
            msg["From"] = header_from
            msg["To"] = to_addr
            msg["Date"] = formatdate(localtime=True)

            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["smtp_username"], cfg["smtp_password"])
                server.sendmail(envelope_from, [to_addr], msg.as_string())

            self.log(f"email sent to {to_addr} from {aprs_sender}")
            self.mark_working()
            return True

        except smtplib.SMTPException as e:
            self.error(f"SMTP error: {e}")
            self.mark_broken(f"SMTP error: {e}")
            return False
        except Exception as e:
            self.error(f"unexpected email error: {e}")
            self.mark_broken(f"unexpected email error: {type(e).__name__}")
            return False
