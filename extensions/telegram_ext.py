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
  Format: "TA1ABC-7 Hello from Telegram!"

Setup:
  1. Message @BotFather on Telegram, create a bot, get the token
  2. Message your bot, then get your chat_id from @userinfobot
  3. Enter bot_token and chat_id in config

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations

import asyncio
import time
import json
import urllib.request
import urllib.error
from typing import Optional

import aprslib

from . import Extension
from .bridge_source import aprs_origin, gateway_callsign
from .bridge_links import looks_like_callsign
from config import TOCALL, aprs_message_text
from config import strip_ssid


# getUpdates is a long poll: Telegram holds the request this long when there
# is nothing to deliver. The HTTP client must outwait it with room for the
# round trip, or an idle bot "times out" several times an hour.
_POLL_WAIT_S = 10
_POLL_HTTP_TIMEOUT_S = _POLL_WAIT_S + 20

# Consecutive failed polls before it is an outage worth an error line. One
# failure heals on the next poll; the error counter is for what does not.
_POLL_OUTAGE_AFTER = 3


def _failure_kind(e: BaseException) -> str:
    """A name for a poll failure that the error counter will not read as one.

    The counter matches "error" anywhere in a line, and `TimeoutError` is
    spelt with it, so the exception's own class name cannot appear here.
    """
    if isinstance(e, TimeoutError) or "timed out" in str(e):
        return "timeout"
    if isinstance(e, ConnectionError) or "reset" in str(e):
        return "connection reset"
    return "network"


def _tg_api(token: str, method: str, params: Optional[dict] = None,
            timeout: float = 15) -> dict:
    url = f"https://api.telegram.org/bot{token}/{method}"
    if params:
        data = json.dumps(params).encode("utf-8")
        req = urllib.request.Request(url, data=data,
                                     headers={"Content-Type": "application/json"})
    else:
        req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
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


# A linked amateur's messages on air per hour, per chat
_LINKED_PER_HOUR = 20

_HELP_TEXT = (
    "APRS köprüsü yalnızca lisanslı amatörler içindir (Yönetmelik Md.23/1-c).\n"
    "1) /bagla ÇAĞRI  — bir kod alırsınız\n"
    "2) Telsizinizden {alias} adresine: LINK <kod>\n"
    "Sonra: ÇAĞRI mesaj  → telsize. /coz bağlantıyı kaldırır.\n\n"
    "The APRS bridge is for licensed amateurs only.\n"
    "1) /link CALL  — you get a code\n"
    "2) From your radio, to {alias}: LINK <code>\n"
    "Then: CALL message → on air. /unlink removes the link.")


def _to_text(s: str) -> str:
    return (s or "").strip()


class Telegram(Extension):

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self._queue: Optional[asyncio.Queue] = None
        self._msg_counter = 0
        self._last_update_id = 0
        self._poll_task: Optional[asyncio.Task] = None
        # callsign <-> chat links (bridge_links.BridgeLinks), given by the
        # web GUI; None = operator-only, as before links existed
        self._links = None
        self._sent_at: dict = {}        # chat id -> recent send times
        # The bot's @name from getMe, so SERVICES can say which bot to
        # write to; "" until Telegram has answered once
        self.bot_username = ""

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
        if cfg.get("poll_enabled") and not cfg.get("from_callsign"):
            raise ValueError("Telegram: from_callsign is required when poll_enabled is on")

    @property
    def name(self) -> str:
        return "telegram"

    @property
    def is_spawnable(self) -> bool:
        return False

    def set_links(self, links) -> None:
        self._links = links

    async def _learn_username(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            me = await loop.run_in_executor(None, lambda: _tg_api(
                self._config["bot_token"], "getMe"))
        except Exception:
            return      # asked again after the next good poll
        name = ((me or {}).get("result") or {}).get("username") or ""
        if name and name != self.bot_username:
            self.bot_username = name
            self.log(f"bot is @{name}")

    def _within_rate(self, chat_id: str) -> bool:
        """A linked user may put _LINKED_PER_HOUR messages an hour on air."""
        now = time.time()
        recent = [x for x in self._sent_at.get(chat_id, []) if now - x < 3600]
        if len(recent) >= _LINKED_PER_HOUR:
            self._sent_at[chat_id] = recent
            return False
        recent.append(now)
        self._sent_at[chat_id] = recent
        return True

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._queue = q
        # Called again on every APRS-IS reconnect (routine over a
        # long-running process), not just once at startup. The poll loop
        # itself doesn't depend on the APRS-IS connection at all -- it only
        # talks to Telegram -- so a still-running loop from a previous
        # connection is still perfectly good; spawning another one here
        # unconditionally silently piled up duplicate long-polling loops
        # every reconnect. Over 25 days of uptime that grew to ~16
        # concurrent pollers, which exhausted the shared executor thread
        # pool (every other run_in_executor call, including AI requests,
        # queued behind them) and froze the whole API.
        if self._config.get("poll_enabled") and (
                self._poll_task is None or self._poll_task.done()):
            self._poll_task = asyncio.create_task(self._poll_loop())

    async def _send_tg(self, text: str, chat_id: Optional[str] = None) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()

        def _do():
            _tg_api(cfg["bot_token"], "sendMessage", {
                "chat_id": chat_id or cfg["chat_id"],
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
        operator = any(s.upper() == sender_call.upper()
                       for s in cfg.get("allowed_senders", []))

        recipient = packet.get("addresse", "").strip()
        allowed = list(cfg.get("allowed_recepients", []))
        from_call_cfg = cfg.get("from_callsign", "").upper()
        if from_call_cfg and from_call_cfg not in allowed:
            allowed.append(from_call_cfg)
        if recipient not in allowed:
            return None

        message = packet.get("message_text", "")
        words = message.split(None, 1)
        head = words[0].upper() if words else ""
        links = self._links

        if links is not None and head == "LINK" and len(words) == 2:
            # the radio half of linking: the code the bot gave in Telegram
            entry = links.confirm("telegram", sender_full, words[1])
            if entry:
                self.count("tg_linked")
                self.log(f"linked {entry['call']} to a Telegram chat")
                await self._send_tg(f"Bağlandı / Linked: {entry['call']}", entry["target"])
            else:
                self.count("tg_bad_code")
                self.warn(f"LINK from {sender_full}: unknown or expired code")
        elif links is not None and head == "UNLINK":
            gone = links.unlink_call("telegram", sender_full)
            if gone:
                self.log(f"unlinked {gone['call']}")
                await self._send_tg(f"Bağlantı kaldırıldı / Unlinked: {gone['call']}", gone["target"])
        elif (links is not None and len(words) == 2 and looks_like_callsign(head)
              and links.by_call("telegram", head)):
            # to another licensed amateur's linked Telegram
            target = links.by_call("telegram", head)
            await self._send_tg(f"{sender_full}: {_to_text(words[1])}\n(APRS)", target["target"])
            self.log(f"{sender_full} -> {target['call']} on Telegram")
        elif operator:
            path = ",".join(packet.get("path", []))
            dest = packet.get("to", "")
            text = f"{message}\nfrom {sender_full}>{dest},{path}"
            if cfg.get("add_hash_tag", True):
                text += " #APRS"
            await self._send_tg(text)
        elif links is not None and links.by_call("telegram", sender_full):
            # a linked amateur writing to their own Telegram
            own = links.by_call("telegram", sender_full)
            await self._send_tg(f"{message}\n(APRS, {sender_full})", own["target"])
        else:
            return None

        msg_id = packet.get("msgNo", "")
        if not msg_id:
            return None
        # From the alias that was addressed, to the sender. It used to carry
        # the sender's callsign as its tocall and the question's own path.
        ack = f"{recipient}>{TOCALL},TCPIP*::{sender_full:<9}:ack{msg_id}\r\n"
        return ack.encode("utf-8")

    # ── Inbound: Telegram → APRS ──

    async def _poll_loop(self) -> None:
        interval = int(self._config.get("poll_interval_secs", 5))
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: _tg_api(
                self._config["bot_token"], "deleteWebhook"))
            self.log("webhook cleared")
        except Exception:
            pass
        await self._learn_username()
        self.log(f"polling Telegram every {interval}s")
        await asyncio.sleep(5)
        failed = 0
        while True:
            try:
                await self._check_updates()
            except urllib.error.HTTPError as e:
                if e.code == 409:
                    self.error("409 Conflict — another bot instance is polling this token. Stop the other process.")
                    await asyncio.sleep(30)
                else:
                    self.error(f"poll error: {e}")
            except Exception as e:
                # A lone timeout or reset is the network, not the bot, and
                # the next poll carries on where this one stopped — offsets
                # mean nothing is lost. Counted as an error once, when it
                # has become an outage, and not again until it recovers.
                failed += 1
                if failed == _POLL_OUTAGE_AFTER:
                    self.error(f"poll error: {failed} polls in a row failed, "
                               f"last {type(e).__name__}: {e}")
                elif failed < _POLL_OUTAGE_AFTER:
                    self.log(f"poll: {_failure_kind(e)}, retrying")
            else:
                if failed >= _POLL_OUTAGE_AFTER:
                    self.log(f"poll recovered after {failed} missed polls")
                failed = 0
                if not self.bot_username:
                    await self._learn_username()
            await asyncio.sleep(interval)

    async def _check_updates(self) -> None:
        cfg = self._config
        loop = asyncio.get_running_loop()
        token = cfg["bot_token"]
        aprs_dest = cfg.get("aprs_destination", "").upper()
        from_call = cfg.get("from_callsign", "").upper()

        def _fetch():
            return _tg_api(token, "getUpdates", {
                "offset": self._last_update_id + 1,
                "timeout": _POLL_WAIT_S,
            }, timeout=_POLL_HTTP_TIMEOUT_S)

        result = await loop.run_in_executor(None, _fetch)
        if not result.get("ok"):
            self.error(f"getUpdates failed: {result}")
            return

        for update in result.get("result", []):
            self._last_update_id = update["update_id"]
            msg = update.get("message", {})
            text = msg.get("text", "").strip()
            if not text:
                continue

            sender_name = msg.get("from", {}).get("first_name", "TG")

            chat_id = str(msg.get("chat", {}).get("id", ""))
            own_chat = chat_id == str(cfg.get("chat_id", "")).strip()
            alias = gateway_callsign(cfg) or "TGSEND"

            # Linking commands, open to any chat: they put nothing on air
            if self._links is not None and text.startswith("/"):
                cmd, _, arg = text.partition(" ")
                cmd = cmd.split("@")[0].lower()
                if cmd in ("/link", "/bagla"):
                    code = self._links.request("telegram", arg.strip(), chat_id)
                    self.count("tg_code" if code else "tg_code_refused")
                    if code:
                        await self._send_tg(
                            f"Telsizinizden {alias} adresine şu mesajı gönderin: LINK {code}\n"
                            f"From your radio, send to {alias}: LINK {code}\n"
                            f"(10 dk / 10 min)", chat_id)
                    else:
                        await self._send_tg("Çağrı işareti? / Callsign? — /bagla TA1ABC", chat_id)
                    continue
                if cmd in ("/unlink", "/coz"):
                    gone = self._links.unlink_target("telegram", chat_id)
                    await self._send_tg(
                        f"Bağlantı kaldırıldı / Unlinked: {gone['call']}" if gone
                        else "Bağlı çağrı işareti yok / No linked callsign", chat_id)
                    continue
                if cmd in ("/start", "/help", "/yardim"):
                    await self._send_tg(_HELP_TEXT.format(alias=alias), chat_id)
                    continue

            # Who may put text on APRS, and under which callsign: the
            # configured chat as the operator (from_callsign), a linked chat
            # as its own amateur. Anyone else is not relayed - the bot is
            # findable by name, and until 2026-10-26 it relayed every chat
            # under the operator's callsign (F-2026-10-26-01).
            linked = self._links.by_target("telegram", chat_id) if self._links else None
            if own_chat:
                originator = from_call
            elif linked:
                originator = linked["call"]
                if not self._within_rate(chat_id):
                    self.count("tg_rate")
                    await self._send_tg(f"Saatlik sınır / Hourly limit: {_LINKED_PER_HOUR}", chat_id)
                    continue
            else:
                self.count("tg_ignored")
                self.warn(f"ignored a message from chat {chat_id or '?'} "
                          f"({sender_name}): not the configured chat, not linked")
                if self._links is not None:
                    await self._send_tg(_HELP_TEXT.format(alias=alias), chat_id)
                continue

            tokens = text.split(None, 1)
            if (len(tokens) >= 2
                    and len(tokens[0]) <= 9
                    and any(c.isdigit() for c in tokens[0])):
                to_call = tokens[0].upper()
                message = _to_ascii(tokens[1])
            elif aprs_dest and own_chat:
                to_call = aprs_dest
                message = _to_ascii(text)
            else:
                self.warn(f"skipped from {sender_name}: no callsign prefix and aprs_destination not set")
                continue

            if not message:
                continue

            # "own" sends from the originator's callsign, "gateway" from
            # the bridge alias with the callsign in the text (bridge_source)
            src, message, used = aprs_origin(cfg, originator, message)
            self.log(f"RX from Telegram ({sender_name}): {to_call} {message} [{used}: {src}]")
            if linked and not own_chat:
                self.count("tg_on_air")
            await self._send_aprs(src, to_call, message)

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
        self.log(f"TX to APRS: {to_call} {message}")
