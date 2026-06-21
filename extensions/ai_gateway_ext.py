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
Inspired by aprs-ai-gateway by TA3EKM (Arda Yalin Ozkan)
  https://github.com/ArdaYalinOzkan/aprs-ai-gateway
  Original licensed under CC BY-NC 4.0
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid

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
}

_PROVIDER_MODELS = {
    "puter":      "gpt-4o-mini",
    "groq":       "llama-3.3-70b-versatile",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
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


class AIGateway(Extension):

    def __init__(self, config: dict):
        self._config = config
        self._validate()
        self._processed: set[str] = set()
        self._own_writer: Optional[asyncio.Queue] = None
        self._msg_counter = 0

        provider = config.get("provider", "puter")
        self._base_url = config.get("base_url", "") or _PROVIDER_URLS.get(provider, _PROVIDER_URLS["puter"])
        self._model = config.get("model", "") or _PROVIDER_MODELS.get(provider, "gpt-4o-mini")
        self._client = None

        self.log(
            f"initialized | provider={provider} "
            f"| model={self._model} "
            f"| callsign={config.get('callsign', '')}"
        )

    def _validate(self) -> None:
        cfg = self._config
        if not cfg.get("callsign"):
            raise ValueError("AI Gateway: callsign is required")
        if not cfg.get("api_key"):
            raise ValueError("AI Gateway: api_key is required")

    def _ensure_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._config["api_key"], base_url=self._base_url)
        return self._client

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

        system_prompt = cfg.get("system_prompt", "") or (
            "You are an AI running on an APRS amateur radio system. "
            f"Keep your answer under {char_limit} characters. "
            "Be concise and direct. "
            "Use only ASCII characters (a-z, A-Z, 0-9, punctuation). "
            "No emoji, no unicode, no special characters. "
            "Answer in the same language as the question."
        )

        client = self._ensure_client()
        model = self._model
        loop = asyncio.get_running_loop()

        def _do_ask():
            resp = client.chat.completions.create(
                model=model,
                max_tokens=40 + (extra * 35),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
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
        pkt = f"{from_call}>APRS,TCPIP*::{to_call:<9}:{message}{{{mid}}}\n"
        await self._own_writer.put(pkt.encode("utf-8"))

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

        my_call = cfg.get("callsign", "").upper()
        recipient = packet.get("addresse", "").strip().upper()

        aliases = {my_call}
        for a in cfg.get("trigger_aliases", []):
            aliases.add(a.upper())

        if recipient not in aliases:
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
            if whitelist and not any(
                sender_base.startswith(w[:-1]) if w.endswith("*") else sender_base == w
                for w in whitelist
            ):
                self.warn(f"blocked {sender_full} — not in whitelist")
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

        if msg_id:
            ack = f"{my_call}>APRS,TCPIP*::{sender_full:<9}:ack{msg_id}\n"
            return ack.encode("utf-8")

        return None
