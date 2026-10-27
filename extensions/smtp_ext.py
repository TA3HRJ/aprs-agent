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

Person to person (allow_links): a licensed amateur links an address to their
callsign from the radio - "LINK addr@example.com" to the alias mails a code
to that address, "LINK <code>" from the same callsign confirms it. Any
station may then send "CALL text" to the alias and it is mailed to CALL's
linked address; a linked station's plain text goes to its own address. Only
linked addresses receive this traffic: both ends are licensed amateurs (KEGM
Yön. Md.23/1-c), and the mail names the sending callsign (1-g). It goes out
through its own transport (links_smtp_server, links_from_email - on
aprsagent.com the server's own Postfix as noreply@aprsagent.com), never the
operator's account: that would be letting others use it (1-f).

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations


import asyncio
import re
import smtplib
import time
from email.message import EmailMessage
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, getaddresses, make_msgid
from typing import Optional

import aprslib

from . import Extension
from config import TOCALL, aprs_message_text
from config import strip_ssid
from .bridge_links import CODE_TTL_S, base_call, looks_like_callsign

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$")

# Limits on what a station can make this server mail. A code mail goes to an
# address the requester names, so without them the gateway is a way to send
# mail to anyone: one live request per callsign, three code mails per address
# a day, twenty code mails an hour in all; a sender's person-to-person mails,
# twenty an hour.
_CODE_ADDR_PER_DAY = 3
_CODES_PER_HOUR = 20
_LINKED_PER_HOUR = 20
_LOOPBACK = ("localhost", "127.0.0.1", "::1")


def mask_address(addr: str) -> str:
    """t***@gmail.com - what goes on air, where everything is public."""
    local, _, domain = (addr or "").partition("@")
    return f"{local[:1]}***@{domain}" if domain else "***"


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


_CODE_BODY = """\
{call} asked to link this e-mail address to their amateur radio callsign
on the aprsagent.com APRS gateway.

To confirm, send this APRS message from that callsign's radio to {alias}:

    LINK {code}

The code is valid for {mins} minutes. If this was not you, ignore this mail:
nothing is stored unless the code comes back from the radio.

---
{call} bu e-posta adresini aprsagent.com APRS geçidinde amatör telsiz çağrı
işaretine bağlamak istedi. Onaylamak için o çağrı işaretinin telsizinden
{alias} adresine şu APRS mesajını gönderin:

    LINK {code}

Kod {mins} dakika geçerlidir. Siz istemediyseniz bu iletiyi yok sayın; kod
telsizden gelmedikçe hiçbir şey saklanmaz.

This address takes no mail. / Bu adrese yazılan okunmaz.
https://aprsagent.com/
"""

_LINKED_BODY = """\
This address is now linked to {call} on the aprsagent.com APRS gateway.
APRS messages sent to {alias} as "{call} text" will be mailed here, naming
the sender's callsign. To remove the link, send UNLINK to {alias} from
your radio.

---
Bu adres aprsagent.com APRS geçidinde {call} çağrı işaretine bağlandı.
{alias} adresine "{call} metin" olarak gönderilen APRS mesajları, gönderenin
çağrı işaretiyle buraya iletilir. Bağlantıyı kaldırmak için telsizinizden
{alias} adresine UNLINK gönderin.

{inbound}"""

# The last lines of _LINKED_BODY: whether mail can come back
_INBOUND_OFF = "This address takes no mail. / Bu adrese yazılan okunmaz.\n"
_INBOUND_ON = """\
To send an APRS message as {call}, write from this address to the station's
callsign at {domain}, e.g. ta1abc-7@{domain}: the first line of the mail goes
on air, about 180 characters.
/ {call} olarak APRS mesajı göndermek için bu adresten istasyonun çağrı
işaretine @{domain} yazın, örneğin ta1abc-7@{domain}: e-postanın ilk satırı
yayına çıkar, en çok 180 karakter kadar.
"""

_P2P_BODY = """\
{text}

---
{sender} sent this to {call} over APRS, through the aprsagent.com gateway.
{answer_en}
To stop these mails, send UNLINK to {alias} from your radio.
/ {sender} bunu APRS üzerinden {call} için gönderdi. {answer_tr}
Durdurmak için telsizinizden {alias} adresine UNLINK gönderin.
"""
_ANSWER_OFF = ("Answer over APRS: to {sender} directly, or this mail address takes no mail.",
               "Telsizden {sender}\nistasyonuna cevap verin; bu adrese yazılan okunmaz.")
_ANSWER_ON = ("Reply to this mail to answer {sender} over APRS: the first line goes on air.",
              "Bu e-postayı\nyanıtlarsanız ilk satır APRS'ten {sender} istasyonuna gider.")

_OWN_BODY = """\
{text}

---
Sent from your radio as {sender} over APRS, through the aprsagent.com
gateway. UNLINK to {alias} removes the link.
/ Telsizinizden {sender} olarak gönderildi. {alias} adresine UNLINK
bağlantıyı kaldırır.
"""


class SmtpEmailer(Extension):
    """Forwards APRS messages to email via SMTP."""

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        # callsign <-> address links (bridge_links.BridgeLinks), given by the
        # web GUI when allow_links is on; None = operator-only, as before
        self._links = None
        self._queue: Optional[asyncio.Queue] = None
        self._msg_counter = 0
        self._code_at: dict = {}        # base call -> last code mail
        self._addr_codes: dict = {}     # address -> code mail times
        self._codes: list = []          # all code mail times
        self._sent_at: dict = {}        # base call -> person-to-person times
        # The domain mail comes back on (CALL@domain), given by the web GUI
        # when the inbound side is on; "" = this server takes no mail
        self._reply_domain = ""
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

    def set_links(self, links) -> None:
        self._links = links

    def set_reply_domain(self, domain: str) -> None:
        self._reply_domain = (domain or "").strip().lower()

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._queue = q

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

        # Check APRS message recipient (addressee)
        recipient = packet.get("addresse", "").strip().upper()
        if not any(
            r.upper() == recipient for r in cfg.get("allowed_recipients", [])
        ):
            return None

        sender_full = packet.get("from", "")
        sender_call = strip_ssid(sender_full)
        operator = any(
            s.upper() == sender_call.upper() for s in cfg.get("allowed_senders", [])
        )
        message_text = packet.get("message_text", "")

        if self._links is not None:
            done = await self._linked(sender_full, recipient, message_text, operator)
            if done:
                return self._ack(packet, recipient, sender_full)

        # Check sender
        if not operator:
            return None

        # Parse message body: first word = email address, rest = content
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

        return self._ack(packet, recipient, sender_full)

    @staticmethod
    def _ack(packet: dict, recipient: str, sender_full: str) -> Optional[bytes]:
        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None
        # From the alias that was addressed, to the sender. It used to be
        # built as <the question's tocall>><sender>,<the question's path>.
        ack = f"{recipient}>{TOCALL},TCPIP*::{sender_full:<9}:ack{msg_id}\r\n"
        return ack.encode("utf-8")

    # ── person to person ──────────────────────────────────────────────
    async def _linked(self, sender_full: str, alias: str, text: str,
                      operator: bool) -> bool:
        """The linking commands and mail to linked addresses. True when the
        message was one of them (handled, whatever the outcome); False
        leaves it to the operator's path."""
        links = self._links
        words = text.strip().split(None, 1)
        head = words[0].upper() if words else ""
        if head == "LINK" and len(words) == 2:
            arg = words[1].strip()
            if "@" in arg:
                await self._request_link(sender_full, alias, arg)
            else:
                entry = links.confirm("email", sender_full, arg)
                if entry:
                    self.log(f"linked {entry['call']} to an e-mail address")
                    await self._reply(alias, sender_full,
                                      f"Baglandi/Linked: {mask_address(entry['target'])}")
                    dom = self._reply_domain
                    inbound = (_INBOUND_ON.format(call=entry["call"], domain=dom) if dom
                               else _INBOUND_OFF)
                    await self._mail_linked(entry["target"], "aprsagent.com: linked",
                                            _LINKED_BODY.format(call=entry["call"], alias=alias,
                                                                inbound=inbound))
                else:
                    self.warn(f"LINK from {sender_full}: unknown or expired code")
                    await self._reply(alias, sender_full, "Kod gecersiz/Code unknown or expired")
            return True
        if head == "UNLINK":
            gone = links.unlink_call("email", sender_full)
            if gone:
                self.log(f"unlinked {gone['call']} from its e-mail address")
            await self._reply(alias, sender_full, "Baglanti kaldirildi/Unlinked" if gone
                              else "Bagli adres yok/No linked address")
            return True
        if len(words) == 2 and looks_like_callsign(head) and links.by_call("email", head):
            target = links.by_call("email", head)
            if not self._within_rate(sender_full):
                await self._reply(alias, sender_full, f"Saatlik sinir/Hourly limit {_LINKED_PER_HOUR}")
                return True
            # With the inbound side on, a reply to this mail comes back to
            # the sender's callsign at the reply domain and goes on air
            dom = self._reply_domain
            en, tr = _ANSWER_ON if dom else _ANSWER_OFF
            ok = await self._mail_linked(
                target["target"], f"APRS: {sender_full}",
                _P2P_BODY.format(text=words[1].strip(), sender=sender_full,
                                 alias=alias, call=target["call"],
                                 answer_en=en.format(sender=sender_full),
                                 answer_tr=tr.format(sender=sender_full)),
                reply_to=f"{sender_full.lower()}@{dom}" if dom else "")
            if ok:
                self.log(f"{sender_full} -> {target['call']} by e-mail")
            return True
        if not operator and links.by_call("email", sender_full):
            own = links.by_call("email", sender_full)
            if not self._within_rate(sender_full):
                return True
            await self._mail_linked(own["target"], f"APRS: {sender_full}",
                                    _OWN_BODY.format(text=text.strip(), sender=sender_full,
                                                     alias=alias))
            return True
        return False

    async def _request_link(self, sender_full: str, alias: str, addr: str) -> None:
        addr = addr.strip().lower()
        base = base_call(sender_full)
        now = time.time()
        if not _EMAIL_RE.match(addr) or not looks_like_callsign(base):
            await self._reply(alias, sender_full, "Adres?/Address? LINK ad@ornek.com")
            return
        if now - self._code_at.get(base, 0.0) < CODE_TTL_S:
            await self._reply(alias, sender_full, "Kod zaten gonderildi/Code already sent")
            return
        sent = [x for x in self._addr_codes.get(addr, []) if now - x < 86400]
        self._codes = [x for x in self._codes if now - x < 3600]
        if len(sent) >= _CODE_ADDR_PER_DAY or len(self._codes) >= _CODES_PER_HOUR:
            self.warn(f"code mail for {sender_full} refused: limit")
            await self._reply(alias, sender_full, "Sinir, sonra deneyin/Limit, try later")
            return
        code = self._links.request("email", base, addr)
        if not code:
            return
        ok = await self._mail_linked(
            addr, f"aprsagent.com: LINK {code}",
            _CODE_BODY.format(call=sender_full, alias=alias, code=code,
                              mins=CODE_TTL_S // 60))
        if ok:
            self._code_at[base] = now
            self._addr_codes[addr] = sent + [now]
            self._codes.append(now)
            self.log(f"link code mailed for {sender_full}")
            await self._reply(alias, sender_full, f"Kod gonderildi/Code sent: {mask_address(addr)}")
        else:
            await self._reply(alias, sender_full, "E-posta gonderilemedi/Mail failed")

    def _within_rate(self, sender_full: str) -> bool:
        base = base_call(sender_full)
        now = time.time()
        recent = [x for x in self._sent_at.get(base, []) if now - x < 3600]
        if len(recent) >= _LINKED_PER_HOUR:
            self._sent_at[base] = recent
            return False
        self._sent_at[base] = recent + [now]
        return True

    def _next_msg_id(self) -> str:
        self._msg_counter = (self._msg_counter + 1) % 999 + 1
        return str(self._msg_counter)

    async def _reply(self, alias: str, to_call: str, text: str) -> None:
        """A short APRS message from the alias back to the sender."""
        if not self._queue:
            return
        pkt = (f"{alias}>{TOCALL},TCPIP*::{to_call:<9}:{aprs_message_text(text)[:67]}"
               f"{{{self._next_msg_id()}\r\n")
        await self._queue.put(pkt.encode("utf-8"))

    async def _mail_linked(self, to_addr: str, subject: str, body: str,
                           reply_to: str = "") -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._send_links_mail,
                                          to_addr, subject, body, reply_to)

    def _send_links_mail(self, to_addr: str, subject: str, body: str,
                         reply_to: str = "") -> bool:
        """Blocking send through the links transport, never the operator's
        account: links_smtp_server (default localhost:25, no login) as
        links_from_email."""
        cfg = self._config
        server = str(cfg.get("links_smtp_server") or "localhost:25")
        found = getaddresses([str(cfg.get("links_from_email", ""))])
        if len(found) != 1 or "@" not in found[0][1]:
            self.error("links_from_email is not set - no person-to-person mail")
            return False
        name, envelope = found[0]
        try:
            host, port_str = server.rsplit(":", 1)
            msg = EmailMessage()
            msg["From"] = formataddr((name, envelope))
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["Date"] = formatdate(localtime=True)
            msg["Message-ID"] = make_msgid(domain=envelope.split("@", 1)[1])
            msg["Auto-Submitted"] = "auto-generated"
            if reply_to:
                msg["Reply-To"] = reply_to
            msg.set_content(body)
            with smtplib.SMTP(host, int(port_str), timeout=30) as s:
                s.ehlo()
                if host not in _LOOPBACK and s.has_extn("starttls"):
                    s.starttls()
                    s.ehlo()
                user = cfg.get("links_smtp_username", "")
                if user:
                    s.login(user, cfg.get("links_smtp_password", ""))
                s.send_message(msg, from_addr=envelope, to_addrs=[to_addr])
            self.mark_working()
            return True
        except Exception as e:
            self.error(f"links mail error: {type(e).__name__}: {e}")
            self.mark_broken(f"links mail error: {type(e).__name__}")
            return False

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
