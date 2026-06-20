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

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


import asyncio
import smtplib
from email.mime.text import MIMEText
from email.utils import formatdate
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid


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
        ack = f"{dest}>{sender_full},{path}::{sender_full:<9}:ack{msg_id}\n"
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
            msg["From"] = cfg.get("from_email", "aprs@example.com")
            msg["To"] = to_addr
            msg["Date"] = formatdate(localtime=True)

            with smtplib.SMTP(host, port) as server:
                server.ehlo()
                server.starttls()
                server.login(cfg["smtp_username"], cfg["smtp_password"])
                server.sendmail(msg["From"], [to_addr], msg.as_string())

            self.log(f"email sent to {to_addr} from {aprs_sender}")
            return True

        except smtplib.SMTPException as e:
            self.error(f"SMTP error: {e}")
            return False
        except Exception as e:
            self.error(f"unexpected email error: {e}")
            return False
