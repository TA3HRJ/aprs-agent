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
import re
import time
import unicodedata
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid, resolve_ai_api_key

_TR_MAP = str.maketrans(
    "çÇğĞıİöÖşŞüÜâÂîÎûÛ",
    "cCgGiIoOsSuUaAiIuU",
)

_UNICODE_REPLACE = {
    "\u2026": "...", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"',
    # Dashes are spaced on purpose. An unspaced dash straight after a
    # callsign reads as an SSID: "operated by TA3HRJ\u2014more at ..."
    # arrived as "TA3HRJ-more", which looks like a station rather than a
    # sentence. Doubled spaces are collapsed in _to_ascii.
    "\u2013": " - ", "\u2014": " - ",
    "\u00a0": " ", "\u200b": "",
    "\u00b0": " derece",
}

# Letters with no canonical decomposition, so stripping combining marks
# cannot reach them. Everything else - e-acute, a-tilde, n-tilde, u-umlaut
# and the rest of Latin script - is handled by the NFD pass below.
_LATIN_EXTRA = {
    "\u00df": "ss", "\u00e6": "ae", "\u00c6": "AE",
    "\u0153": "oe", "\u0152": "OE",
    "\u00f8": "o", "\u00d8": "O", "\u0111": "d", "\u0110": "D",
    "\u0142": "l", "\u0141": "L",
    "\u00fe": "th", "\u00de": "Th", "\u00f0": "d", "\u00d0": "D",
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


_CRLF = "\r\n"


def _to_ascii(text: str) -> str:
    """Fold to printable ASCII without losing the letter under the accent.

    Order matters. The Turkish map runs first because dotless i has no
    decomposition and would simply disappear in the NFD pass; after it, the
    Turkish letters are already ASCII. Everything else in Latin script then
    loses its combining marks rather than itself.
    """
    for k, v in _UNICODE_REPLACE.items():
        text = text.replace(k, v)
    text = text.translate(_TR_MAP)
    for k, v in _LATIN_EXTRA.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(ch for ch in text if 32 <= ord(ch) <= 126)
    return re.sub(r" {2,}", " ", text).strip()


# A callsign as it appears in a question: prefix, digit, suffix, optional SSID.
# The same shape station_db uses to tell a callsign from an APRS object name -
# TABOR and TAPIOLA start with a Turkish prefix and are neither.
_CALL_IN_TEXT = re.compile(r"\b([A-Z0-9]{1,2}[0-9][A-Z]{1,4})(-[0-9]{1,2})?\b")


def _ago(seconds: float) -> str:
    """Plain age, because a position without one arrives in the present tense."""
    s = int(max(0, seconds))
    if s < 90:
        return "%ds ago" % s
    if s < 5400:
        return "%dmin ago" % round(s / 60)
    if s < 172800:
        return "%dh ago" % round(s / 3600)
    return "%dd ago" % round(s / 86400)


def _station_answer(db, wanted: str, rec: "Optional[dict]") -> str:
    """One line about one station, or a plain statement that we have nothing.

    Everything a model could get wrong here is a fixed field: the age is
    always printed, the source is always named as this station's own feed,
    and aprs.fi is offered because it has the history we do not.
    """
    if not rec:
        return ("%s is not in my records. It may not have been heard here. "
                "Try aprs.fi" % wanted)
    lat, lon = rec.get("lat"), rec.get("lon")
    ago = rec.get("last_seen_ago_s")
    bits = [wanted + ":"]
    if lat is not None and lon is not None:
        bits.append("%.3f,%.3f" % (lat, lon))
        loc = (rec.get("locator") or "")[:6]
        if loc:
            bits.append("(%s)" % loc)
    else:
        bits.append("heard, no position")
    if ago is not None:
        bits.append(_ago(ago))
    gate = rec.get("last_gate")
    if gate:
        bits.append("via " + str(gate))
    return " ".join(bits) + ". My own feed only; full history: aprs.fi"


# A 4- or 6-character Maidenhead locator, standing alone in a question.
_GRID_IN_TEXT = re.compile(r"\b([A-R]{2}[0-9]{2}(?:[A-X]{2})?)\b")

_WX_RADIUS_KM = 100.0        # beyond this, somebody else's weather


def _grid_to_latlon(grid: str):
    """Centre of a Maidenhead square. Enough for "which station is nearest"."""
    g = grid.upper()
    try:
        lon = (ord(g[0]) - 65) * 20 - 180
        lat = (ord(g[1]) - 65) * 10 - 90
        lon += int(g[2]) * 2
        lat += int(g[3]) * 1
        if len(g) >= 6:
            lon += (ord(g[4]) - 65) * 5 / 60.0
            lat += (ord(g[5]) - 65) * 2.5 / 60.0
            return lat + 1.25 / 60.0, lon + 2.5 / 60.0
        return lat + 0.5, lon + 1.0
    except (IndexError, ValueError):
        return None


def _wx_answer(rec: dict, dist_km: float) -> str:
    """One weather station's reading, with the two facts that qualify it.

    Distance and age are fields, not sentences, so neither can be dropped:
    a reading from 90 km away six hours ago is not the weather here, and the
    reader has to be able to see that without being told.
    """
    bits = []
    t = rec.get("wx_temp_c")
    if t is not None:
        bits.append("%.1fC" % t)
    h = rec.get("wx_humidity")
    if h is not None:
        bits.append("%d%%RH" % h)
    p = rec.get("wx_pressure_mb")
    if p:
        bits.append("%.0fmb" % p)
    g = rec.get("wx_wind_gust_ms")
    if g:
        bits.append("gust %.1fm/s" % g)
    ago = rec.get("last_seen_ago_s")
    return "%s %.0fkm away, %s: %s. My own feed only, not a forecast" % (
        rec.get("callsign", "?"), dist_km,
        _ago(ago) if ago is not None else "age unknown",
        ", ".join(bits) or "no readings")


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

    # How long a message counts as already seen. Long enough to swallow a
    # sender's retries, short enough that asking again later is answered.
    _DEDUP_TTL_S = 600.0

    # How many times one answer may be replayed to a sender who keeps asking.
    # Two covers a path that dropped the reply twice; beyond that the sender is
    # stuck rather than unlucky, and a shared channel should not carry the
    # difference.
    _MAX_REPLAYS = 2

    def __init__(self, config: dict, config_path: str = ""):
        self._config = config
        self._config_path = config_path
        self._cfg_read_at = 0.0
        self._cfg_mtime = 0.0
        self._validate()
        # key -> (expiry, answer, replays left). The answer is kept so a
        # retry is served from cache rather than met with silence.
        self._processed: dict[str, tuple] = {}
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
        self._status_started = False
        self._station_db = None        # set by set_station_db()
        self._provider = config.get("provider", "puter")
        self._base_url = config.get("base_url", "") or _PROVIDER_URLS.get(
            self._provider, _PROVIDER_URLS["puter"])
        self._model = config.get("model", "") or _PROVIDER_MODELS.get(
            self._provider, "gpt-4o-mini")
        self.log(
            f"initialized | provider={self._provider} "
            f"| model={self._model} "
            f"| callsign={config.get('callsign', '')}"
        )

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

    def set_station_db(self, db) -> None:
        self._station_db = db

    def set_own_writer(self, q: asyncio.Queue) -> None:
        self._own_writer = q
        if not self._status_started:
            self._status_started = True
            asyncio.create_task(self._status_loop())

    async def _status_loop(self) -> None:
        """Say, on the network itself, who operates this service.

        The addressee is not a callsign — it identifies a piece of software,
        not a station — so nothing here is a substitute for a licence. But
        somebody who meets DMWGPT on aprs.fi should be able to find the
        operator without asking, and an APRS status packet is where every
        other service callsign puts that. Empty text = no status sent.
        """
        while True:
            cfg = self._live_config()
            mins = int(cfg.get("status_interval_mins", 0) or 0)
            text = (cfg.get("status_text") or "").strip()
            if mins <= 0 or not text or not self._own_writer:
                await asyncio.sleep(300)
                continue
            call = cfg.get("callsign", "").upper()
            if call:
                pkt = f"{call}>APRS,TCPIP*:>{_to_ascii(text)[:62]}" + _CRLF
                try:
                    await self._own_writer.put(pkt.encode("utf-8"))
                    # Logged on success, not only on failure: this packet is
                    # how the service identifies its operator, and an operator
                    # asked whether it was going out could otherwise only
                    # answer from the absence of an error.
                    self.log(f"status sent: {pkt.strip()}")
                except Exception as e:
                    self.error(f"status packet failed: {type(e).__name__}: {e}")
            await asyncio.sleep(mins * 60)

    async def _wx_lookup(self, question: str,
                         sender_full: str) -> "Optional[str]":
        """Nearest weather station to the sender, or to a grid they name.

        Returns None when the question is not about weather, so everything
        else follows the ordinary path.

        No geocoding: a city name is refused rather than guessed. We have no
        gazetteer, and naming the wrong Izmir is worse than saying no.
        """
        db = self._station_db
        if db is None:
            return None
        text = question.upper()
        if not any(w in text for w in ("WEATHER", "WX ", " WX", "TEMP", "FORECAST",
                                       "HAVA DURUMU", "HAVA NASIL", "SICAKLIK",
                                       "YAGMUR", "RAIN")):
            return None

        # where to measure from
        origin, origin_note = None, ""
        grid = _GRID_IN_TEXT.search(text)
        if grid:
            origin = _grid_to_latlon(grid.group(1))
            origin_note = grid.group(1)
        if origin is None:
            try:
                me = db.get_one(sender_full) or db.get_one(strip_ssid(sender_full))
            except Exception as e:
                self.error(f"wx lookup failed: {e}")
                return None
            if me and me.get("lat") is not None:
                origin, origin_note = (me["lat"], me["lon"]), "your last position"
        if origin is None:
            return ("I do not know where you are and I cannot look up place "
                    "names. Send a grid like KM38, or use a weather service.")

        # Nearest station carrying a reading. The scan walks the whole
        # registry, so it goes to a thread - the same rule silence_cells()
        # earned the hard way twice.
        try:
            hit = await asyncio.get_event_loop().run_in_executor(
                None, db.nearest_wx, origin[0], origin[1], _WX_RADIUS_KM)
        except Exception as e:
            self.error(f"wx scan failed: {e}")
            return None

        if hit is None:
            return ("No APRS weather station within %.0fkm of %s in my records. "
                    "Try a weather service." % (_WX_RADIUS_KM, origin_note))
        rec, dist_km = hit
        self.log("wx lookup: %s -> %s at %.0fkm"
                 % (sender_full, rec.get("callsign"), dist_km))
        return _wx_answer(rec, dist_km)

    def _self_lookup(self, question: str, sender_base: str) -> "Optional[str]":
        """Answer about the sender's own station, or hand back to the model.

        Returns None when the question is not one of these, so everything else
        follows the ordinary path.

        Only the sender's own base callsign is served. A different one gets a
        flat refusal rather than a lookup: the data is public and aprs.fi
        serves it, but a service that answers "where is XX1YYY" on request is
        a different object from a map somebody chose to open, and the people
        most interested in that difference are not the ones it would help.
        """
        db = self._station_db
        if db is None or not sender_base:
            return None
        text = question.upper()
        if not any(w in text for w in ("WHERE", "LOCAT", "LAST HEARD", "HEARD",
                                       "NEREDE", "KONUM", "SON DUYUL")):
            return None
        found = _CALL_IN_TEXT.findall(text)
        if not found:
            return None
        for base, ssid in found:
            if base == sender_base:
                wanted = base + (ssid or "")
                try:
                    rec = db.get_one(wanted) or db.get_one(base)
                except Exception as e:
                    self.error(f"registry lookup failed: {e}")
                    return None
                self.log(f"self-lookup: {sender_base} asked about {wanted}")
                return _station_answer(db, wanted, rec)
        return ("I only look up your own callsign. For other stations, "
                "aprs.fi or findu.com.")

    async def _ask_ai(self, question: str, sender: str = "") -> str:
        cfg = self._config
        extra = int(cfg.get("extra_sms", 0))
        total_parts = 1 + extra
        char_limit = 64 if total_parts == 1 else (total_parts - 1) * 62 + 64

        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # The mechanical constraints always apply. They used to live inside the
        # default prompt, so setting system_prompt in the config discarded them
        # along with everything else: measured live, 3 of 4 answers then ran
        # past the limit and were cut mid-sentence, and the model no longer
        # knew the date. An operator's prompt is about content and identity;
        # the length of an APRS message is not theirs to choose.
        rules = (
            "You are an AI reached over APRS on amateur radio. "
            f"Current date/time: {today}. "
            f"Your whole answer must be under {int(char_limit * 0.85)} "
            "characters - models count these badly, so aim well short: "
            "stopping early costs a reader nothing, being cut off mid-sentence "
            "costs them the end of the answer. "
            "Be concise and direct. "
            "Use only ASCII characters (a-z, A-Z, 0-9, punctuation). "
            "No emoji, no unicode. "
            "Answer in the same language as the question."
        )
        if sender:
            # The sender's callsign is in the packet header, so asking them for
            # it is asking for something already known. TG5ALY-14 sent
            # "Callsign" and was told "your callsign isn't in the message".
            rules += (
                f" You are talking to {sender}; that is the station asking, "
                "not you. You are not a station and have no callsign of your "
                "own. Never sign as another callsign, never use DE with one, "
                "and do not role-play a QSO - answer as a service."
            )
        operator = cfg.get("system_prompt", "").strip()
        system_prompt = (rules + " " + operator) if operator else rules

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

        # An addressee carries an SSID as often as not, and MYBOT-1 is the
        # same service as MYBOT — those messages used to fall through in
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
        # Retries have to be absorbed, but a repeat is not a retry. With no
        # msgNo the key is sender+text, and it used to live forever: asking
        # the same question an hour later was met with silence, which is
        # indistinguishable from the gateway being down. Seen live -
        # CT4TX-10 asked "what APRS mean?" twice, seven minutes apart, and
        # was answered once.
        now_ts = time.time()
        if self._processed:
            for k in [k for k, v in self._processed.items() if v[0] <= now_ts]:
                del self._processed[k]
        dedup_key = f"{sender_full}:{msg_id or raw_msg}"
        seen = self._processed.get(dedup_key)
        if seen is not None:
            # Asking again almost always means the answer never arrived — an
            # igate did not gate it back, or the path dropped it. Staying
            # silent turns a delivery failure into a permanent one, so the
            # cached answer goes out again. No AI call; the cost is one more
            # transmission on a path that already failed once.
            exp, cached, left = seen
            if cached and left > 0 and self._own_writer:
                self._processed[dedup_key] = (exp, cached, left - 1)
                self.log(f"replaying answer to {sender_full} ({left - 1} left)")
                for i, part in enumerate(_split_message(
                        cached, 1 + int(cfg.get("extra_sms", 0)))):
                    await self._send_reply(my_call, sender_full, part)
                    if i:
                        await asyncio.sleep(5)
            return None
        self._processed[dedup_key] = (now_ts + self._DEDUP_TTL_S, "", self._MAX_REPLAYS)

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

        self.log(f"RX from {sender_full}: {question}")

        # A question naming a callsign is answered from the registry, not by
        # the model — but only about the sender's own. All the risk in this
        # feature is third-party lookup; asking about yourself carries none of
        # it, and the packet header already says who is asking.
        answer = self._self_lookup(question, sender_base)
        if answer is None:
            answer = await self._wx_lookup(question, sender_full)
        if answer is None:
            # Only now, with the free answers exhausted, does this cost money.
            allowed, notice = self._allow_daily(cfg)
            if not allowed:
                self.warn(f"daily limit reached, refused {sender_full}"
                          + (" (told)" if notice else ""))
                if notice:
                    await self._send_reply(my_call, sender_full, notice)
                return None
            answer = await self._ask_ai(question, sender_full)
        if not answer:
            return None

        self.log(f"AI response: {answer}")
        # Kept so a retry can be served without asking again.
        prev = self._processed.get(dedup_key)
        if prev is not None:
            self._processed[dedup_key] = (prev[0], answer, prev[2])

        parts = _split_message(answer, 1 + int(cfg.get("extra_sms", 0)))

        for i, part in enumerate(parts):
            await self._send_reply(my_call, sender_full, part)
            self.log(f"TX to {sender_full}: {part}")
            if i < len(parts) - 1:
                await asyncio.sleep(5)

        return None
