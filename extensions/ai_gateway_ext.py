"""
AI Gateway Extension
====================
Auto-responds to incoming APRS messages using an AI provider.

Monitors the APRS-IS stream for message packets addressed to a
configured callsign, queries an OpenAI-compatible AI, and sends
the response back as APRS message(s).

Supported providers: Puter (free), Groq, OpenRouter, or any
OpenAI-compatible endpoint.

Developed by TA3HRJ & TA3PKS
Bidirectional design follows aprs-ai-gateway by TA3EKM (Arda Yalin Ozkan),
which is what made an APRS station able to answer rather than only report.
  https://github.com/ArdaYalinOzkan/aprs-ai-gateway
  Original licensed under CC BY-NC 4.0
Reaches the air through the own-writer channel from TA3PKS's extension design.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid, resolve_ai_api_key

_TR_MAP = str.maketrans(
    "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
    "cCgGiIoOsSuUaAiIuU",
)

_UNICODE_REPLACE = {
    "…": "...", "‘": "'", "’": "'",
    "“": '"', "”": '"', "–": "-",
    "—": "-", " ": " ", "​": "",
    "°": " derece", "é": "e", "è": "e",
    "à": "a",
}

_PROVIDER_URLS = {
    "puter":      "https://api.puter.com/puterai/openai/v1/",
    "groq":       "https://api.groq.com/openai/v1/",
    "openrouter": "https://openrouter.ai/api/v1/",
    "openai":     "https://api.openai.com/v1/",
    "deepseek":   "https://api.deepseek.com/v1/",
    # Anthropic is not OpenAI-compatible (see _do_ask) — this is the host
    # only, "/v1/messages" is appended where it's actually used.
    "anthropic":  "https://api.anthropic.com",
}

_PROVIDER_MODELS = {
    "puter":      "gpt-4o-mini",
    "groq":       "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "openai":     "gpt-4o-mini",
    # "deepseek-chat" is a legacy alias for this model, deprecating
    # 2026-07-24 -- using the real name directly so it keeps working.
    "deepseek":   "deepseek-v4-flash",
    "anthropic":  "claude-3-5-haiku-20241022",
}


def _to_ascii(text: str) -> str:
    for k, v in _UNICODE_REPLACE.items():
        text = text.replace(k, v)
    text = text.translate(_TR_MAP)
    return "".join(ch for ch in text if 32 <= ord(ch) <= 126)


def _split_message(text: str, max_parts: int) -> list[str]:
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
                cut = remaining[:61].rsplit(" ", 1)[0]
                chunk = (cut or remaining[:61]) + "..."
            parts.append(chunk)
            break
        cut = remaining[:61].rsplit(" ", 1)[0] or remaining[:61]
        parts.append(cut + " --")
        remaining = remaining[len(cut):].strip()
    return parts


# Sent back to a sender who has emptied their bucket, once per episode.
# {m} is replaced with the whole minutes until they can ask again.
_DEFAULT_RATE_NOTICE = "Too many questions - please wait {m} min, then ask again"
_DEFAULT_DAILY_NOTICE = "Daily question limit reached on this gateway - try tomorrow"


class AIGateway(Extension):

    # How often the gateway re-reads its own section from the config file.
    # The whitelist used to be a snapshot taken when the extension loaded, so
    # shutting the gate meant restarting the agent — no way to stop answering
    # in a hurry, which is not a state to be in with an AI addressable from
    # the whole of APRS-IS.
    _CFG_REFRESH_S = 5.0

    def __init__(self, config: dict, config_path: str = ""):
        self._config = config
        self._config_path = config_path
        self._cfg_read_at = 0.0
        self._cfg_mtime = 0.0
        self._validate()
        self._processed: set[str] = set()
        self._own_writer: Optional[asyncio.Queue] = None
        self._msg_counter = 0
        # Token bucket per sender: a burst of questions costs nothing, and the
        # refill only bites on sustained hammering. A flat cooldown would have
        # punished exactly the people worth having — someone meeting the thing
        # for the first time asks three or four questions back to back.
        self._buckets: dict[str, list] = {}   # sender -> [tokens, last_refill, told]
        self._day = ""
        self._day_count = 0
        self._day_told = False

    def _live_config(self) -> dict:
        """The gateway's own config section, re-read when the file changes.

        Cheap: a stat at most every _CFG_REFRESH_S, and a parse only when the
        mtime actually moved. Anything unreadable leaves the last good config
        in place — a broken edit must not silently open the gate.
        """
        if not self._config_path:
            return self._config
        now = time.time()
        if now - self._cfg_read_at < self._CFG_REFRESH_S:
            return self._config
        self._cfg_read_at = now
        try:
            mtime = os.path.getmtime(self._config_path)
            if mtime == self._cfg_mtime:
                return self._config
            import config as cfg_module
            fresh = (cfg_module.load_config(self._config_path)
                     .get("extensions", {}).get("ai_gateway", {}))
            if fresh:
                self._cfg_mtime = mtime
                if fresh.get("whitelist_enabled") != self._config.get("whitelist_enabled")                         or fresh.get("whitelist") != self._config.get("whitelist")                         or fresh.get("enabled") != self._config.get("enabled"):
                    self.log("config reloaded — whitelist_enabled=%s entries=%d enabled=%s"
                             % (fresh.get("whitelist_enabled"),
                                len(fresh.get("whitelist") or []),
                                fresh.get("enabled")))
                self._config = fresh
        except Exception as e:
            self.warn(f"config reload failed, keeping previous: {e}")
        return self._config

    def _allow_rate(self, sender: str, cfg: dict) -> "tuple[bool, Optional[str]]":
        """Token bucket. Returns (allowed, notice to send back or None).

        A refusal that says nothing looks like a broken service, and the person
        on the other end has no way to tell "you asked too fast" from "the
        gateway is down". So the first refusal of an episode answers.

        Only the first: telling someone off once per message would turn a
        hammering sender into a hammering transmitter, at our own expense and
        on a shared RF resource. The notice unlocks again only after they have
        earned a token back.
        """
        burst = float(cfg.get("rate_burst", 4) or 0)
        refill_s = float(cfg.get("rate_refill_s", 180) or 0)
        if burst <= 0 or refill_s <= 0:
            return True, None                 # limiter off
        now = time.time()
        b = self._buckets.get(sender)
        if b is None:
            self._buckets[sender] = [burst - 1.0, now, False]
            return True, None
        tokens = min(burst, b[0] + (now - b[1]) / refill_s)
        if tokens < 1.0:
            b[0], b[1] = tokens, now
            if b[2]:
                return False, None            # already told them this episode
            b[2] = True
            wait_min = max(1, int(round((1.0 - tokens) * refill_s / 60.0)))
            tmpl = cfg.get("rate_notice") or _DEFAULT_RATE_NOTICE
            return False, tmpl.replace("{m}", str(wait_min))[:64]
        b[0], b[1], b[2] = tokens - 1.0, now, False
        # Senders idle longer than a full refill are forgotten, so the dict
        # cannot grow without bound on a worldwide feed.
        if len(self._buckets) > 2000:
            cutoff = now - burst * refill_s
            for k in [k for k, v in self._buckets.items() if v[1] < cutoff]:
                del self._buckets[k]
        return True, None

    def _allow_daily(self, cfg: dict) -> "tuple[bool, Optional[str]]":
        """Whole-instance ceiling for the day. 0 = no ceiling.

        Left OFF by default deliberately: this instance runs open, and a limit
        nobody asked for is a surprise. But anyone who downloads this and points
        it at a paid provider is one viral post away from a bill they did not
        agree to, and per-sender buckets do not help — a thousand strangers
        asking one question each is a thousand calls. So the ceiling exists,
        with the operator choosing the number.
        """
        limit = int(cfg.get("daily_limit", 0) or 0)
        if limit <= 0:
            return True, None
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if today != self._day:
            self._day, self._day_count, self._day_told = today, 0, False
        if self._day_count >= limit:
            if self._day_told:
                return False, None
            self._day_told = True
            return False, (cfg.get("daily_notice") or _DEFAULT_DAILY_NOTICE)[:64]
        self._day_count += 1
        return True, None

        self._provider = config.get("provider", "puter")
        self._base_url = config.get("base_url", "") or _PROVIDER_URLS.get(self._provider, _PROVIDER_URLS["puter"])
        self._model = config.get("model", "") or _PROVIDER_MODELS.get(self._provider, "gpt-4o-mini")
        self.log(
            f"initialized | provider={self._provider} "
            f"| model={self._model} "
            f"| callsign={config.get('callsign', '')}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("callsign"):
            raise ValueError("AI Gateway: callsign is required")
        if not resolve_ai_api_key(cfg, cfg.get("provider", "puter")):
            raise ValueError("AI Gateway: api_key is required")

    @property
    def name(self) -> str:
        return "ai-gateway"

    @property
    def is_spawnable(self) -> bool:
        return False

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._own_writer = q

    async def _ask_ai(self, question: str) -> str:
        cfg = self._config
        extra = int(cfg.get("extra_sms", 0))
        total_parts = 1 + extra
        char_limit = 64 if total_parts == 1 else (total_parts - 1) * 62 + 64

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        system_prompt = cfg.get("system_prompt", "") or (
            "You are an AI running on an APRS amateur radio system. "
            f"Current date/time: {today}. "
            f"Keep your answer under {char_limit} characters. "
            "Be concise and direct. "
            "Use only ASCII characters (a-z, A-Z, 0-9, punctuation). "
            "No emoji, no unicode, no special characters. "
            "Answer in the same language as the question."
        )

        api_key = resolve_ai_api_key(cfg, self._provider)
        base_url = self._base_url
        model = self._model
        provider = self._provider
        max_tokens = 40 + (extra * 35)
        loop = asyncio.get_running_loop()

        def _do_ask():
            import httpx
            if provider == "anthropic":
                # Anthropic's Messages API is not OpenAI-compatible:
                # different endpoint, auth header, and response shape.
                with httpx.Client(timeout=20) as http_client:
                    r = http_client.post(
                        base_url.rstrip("/") + "/v1/messages",
                        headers={"x-api-key": api_key,
                                 "anthropic-version": "2023-06-01",
                                 "content-type": "application/json"},
                        json={
                            "model": model,
                            "max_tokens": max_tokens,
                            "system": system_prompt,
                            "messages": [{"role": "user", "content": question}],
                        },
                    )
                    r.raise_for_status()
                    data = r.json()
                    return "".join(
                        b.get("text", "") for b in data.get("content", [])
                        if b.get("type") == "text"
                    ).strip()
            from openai import OpenAI
            with httpx.Client() as http_client:
                client = OpenAI(
                    api_key=api_key,
                    base_url=base_url,
                    http_client=http_client,
                )
                extra_body = {}
                if provider == "deepseek":
                    # deepseek-v4-flash defaults to Thinking Mode on -- the
                    # legacy "deepseek-chat" alias was this same model with
                    # thinking off. Without this, the model can spend the
                    # whole max_tokens budget on reasoning_content and never
                    # reach an actual reply in content.
                    extra_body["thinking"] = {"type": "disabled"}
                resp = client.chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    extra_body=extra_body,
                )
                return resp.choices[0].message.content.strip()

        try:
            answer = await loop.run_in_executor(None, _do_ask)
            return _to_ascii(answer)
        except Exception as e:
            self.error(f"AI query failed: {type(e).__name__}: {e}")
            return ""

    def _next_msg_id(self) -> str:
        self._msg_counter = (self._msg_counter + 1) % 999 + 1
        return str(self._msg_counter)

    async def _send_reply(self, from_call: str, to_call: str, message: str) -> None:
        if not self._own_writer:
            self.error("no own_writer queue — cannot send reply")
            return
        mid = self._next_msg_id()
        pkt = f"{from_call}>APRS,TCPIP*::{to_call:<9}:{message}{{{mid}\r\n"
        await self._own_writer.put(pkt.encode("utf-8"))

    async def handle(self, line: str) -> Optional[bytes]:
        cfg = self._live_config()
        if not cfg.get("enabled", True):
            return None

        if line.startswith("#"):
            return None

        try:
            packet = aprslib.parse(line)
        except Exception:
            return None

        if packet.get("format") != "message":
            return None

        my_call = cfg.get("callsign", "").upper()
        recipient = packet.get("addresse", "").strip().upper()

        aliases = {my_call}
        for a in cfg.get("trigger_aliases", []):
            aliases.add(a.upper())
        aliases.discard("")

        # An addressee carries an SSID as often as not, and DMWGPT-1 is the
        # same service as DMWGPT — those messages used to fall through in
        # silence. The sender is already compared SSID-free just below.
        if recipient not in aliases and strip_ssid(recipient) not in {
                strip_ssid(a) for a in aliases}:
            return None

        sender_full = packet.get("from", "")
        sender_base = strip_ssid(sender_full).upper()

        if sender_base == strip_ssid(my_call).upper():
            return None

        raw_msg = packet.get("message_text", "")
        if not raw_msg or raw_msg.lower().startswith(("ack", "rej")):
            return None

        msg_id = packet.get("msgNo", "")
        dedup_key = f"{sender_full}:{msg_id or raw_msg}"
        if dedup_key in self._processed:
            return None
        self._processed.add(dedup_key)
        if len(self._processed) > 10000:
            self._processed = set(list(self._processed)[-5000:])

        # Ack immediately -- it means "your message was received", not
        # "answered", so it shouldn't wait on the AI call or the whitelist
        # check below. Previously the ack was only sent as handle()'s return
        # value, after the full AI round-trip completed. A slow/cold
        # provider call can easily outlast the sender's own retry timeout,
        # causing it to resend with a NEW message id before our ack arrives
        # -- each retry then looks like a genuinely new message and gets its
        # own AI call. Observed live: an 11s cold-start DeepSeek call led to
        # 3 retries 12-13s apart, 3 separate AI answers, for one question.
        if msg_id and self._own_writer:
            ack = f"{my_call}>APRS,TCPIP*::{sender_full:<9}:ack{msg_id}\r\n"
            await self._own_writer.put(ack.encode("utf-8"))

        prefix = cfg.get("trigger_prefix", "").upper()
        if prefix:
            if not raw_msg.upper().startswith(prefix):
                return None
            question = raw_msg[len(prefix):].strip(" :")
        else:
            question = raw_msg

        if not question:
            return None

        if cfg.get("whitelist_enabled"):
            whitelist = [w.upper().strip() for w in cfg.get("whitelist", []) if w.strip()]
            # An empty list with the gate switched ON means NOBODY, not
            # everybody. It used to mean everybody: the `if whitelist and ...`
            # guard skipped the check entirely, so clearing the list to reset
            # it silently opened an AI responder to the whole of APRS-IS while
            # the interface still showed the whitelist as enabled.
            if not whitelist:
                self.warn(f"blocked {sender_full} — whitelist enabled but empty")
                return None
            if not any(
                sender_base.startswith(w[:-1]) if w.endswith("*") else sender_base == w
                for w in whitelist
            ):
                self.warn(f"blocked {sender_full} — not in whitelist")
                return None

        allowed, notice = self._allow_rate(sender_base, cfg)
        if not allowed:
            self.warn(f"rate-limited {sender_full}"
                      + (" (told)" if notice else " (already told)"))
            if notice:
                await self._send_reply(my_call, sender_full, notice)
            return None

        allowed, notice = self._allow_daily(cfg)
        if not allowed:
            self.warn(f"daily limit reached, refused {sender_full}"
                      + (" (told)" if notice else ""))
            if notice:
                await self._send_reply(my_call, sender_full, notice)
            return None

        self.log(f"RX from {sender_full}: {question}")

        answer = await self._ask_ai(question)
        if not answer:
            return None

        self.log(f"AI response: {answer}")

        parts = _split_message(answer, 1 + int(cfg.get("extra_sms", 0)))

        for i, part in enumerate(parts):
            await self._send_reply(my_call, sender_full, part)
            self.log(f"TX to {sender_full}: {part}")
            if i < len(parts) - 1:
                await asyncio.sleep(5)

        return None
