"""
AI Gateway Extension
====================
Auto-responds to incoming APRS messages using an AI provider.

Monitors the APRS-IS stream for message packets addressed to a
configured callsign, queries an OpenAI-compatible AI, and sends
the response back as APRS message(s).

Supported providers: Puter (free), Groq, OpenRouter, or any
OpenAI-compatible endpoint.

Developed by TA3HX & TA3PKS
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
from pathlib import Path
from typing import Optional

import aprslib

from . import Extension
from config import strip_ssid, resolve_ai_api_key
from packet_parser import looks_like_callsign

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

# Asking about yourself without naming yourself. The packet header already
# says who is asking, so "where am I" is answerable and was not being
# answered: on 2026-09-10 TA3HRJ-1 asked "Time, date and my location?" and
# was told its position was not available, while its own beacon from four
# minutes earlier sat in the registry (F-2026-09-10-02). Kept to
# first-person forms - "where is the nearest digi" is not about the sender.
_SELF_IN_TEXT = re.compile(
    r"\bMY\s+(?:LAST\s+|CURRENT\s+)?"
    r"(?:LOCATION|POSITION|POSN|QTH|GRID|LOCATOR|BEACON)\b"
    r"|\bWHERE\s+AM\s+I\b|\bWHERE\s+I\s+AM\b"
    r"|\bKONUMUM\b|\bNEREDEYIM\b|\bBENIM\s+KONUM"
    r"|\bNEREDE\s+OLDUGUMU\b"
)


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
    # A qAC path names the APRS-IS server a station connected to, not an igate
    # that heard it. Printed as "via T2DENMARK" it describes a radio path that
    # does not exist - the same confusion the igate answer had to be taught
    # (2026-09-22, KC1MUR-7 asked where he was).
    try:
        from station_db import is_backbone_gate
        if gate and is_backbone_gate(gate):
            gate, = "",
            bits.append("internet-connected")
    except Exception:
        pass
    if gate:
        bits.append("via " + str(gate))
    return " ".join(bits) + ". My own feed only; full history: aprs.fi"


# A 4- or 6-character Maidenhead locator, standing alone in a question.
_GRID_IN_TEXT = re.compile(r"\b([A-R]{2}[0-9]{2}(?:[A-X]{2})?)\b")

# A UK postcode looks exactly like a four-character grid square followed by
# noise. 2M0SBP asked "PH39 4NX wx" on 2026-09-20 and PH39 was read as a
# locator, putting the origin at 10S 127E - open ocean north of Australia -
# and the answer, confidently, was that no weather station was within 250 km
# of it. Six-character locators are unambiguous and keep working.
# The space is load-bearing: without it this also swallows KM38OK and IO76BV,
# which are the locators the feature exists to accept.
_POSTCODE_IN_TEXT = re.compile(
    r"\b[A-Z]{1,2}[0-9][0-9A-Z]?\s+[0-9][A-Z]{2}\b")

# Beyond this it is somebody else's weather. Overridable per instance as
# wx_radius_km: measured on the live registry, 235 stations sat within
# 100 km of this operator and not one of them measured weather; the
# nearest that did was 213 km away. Dense in some countries, empty in
# others - only the operator knows which one they are in.
_WX_RADIUS_KM = 250.0

# Within the radius is not the same as local. Past this a reading is still
# worth giving - it may be the only one there is - but it leads with the
# distance and says it is not local. 30 km is roughly where valley, coast
# and altitude start to make a neighbour's weather a different weather.
_WX_LOCAL_KM = 30.0


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance, the same formula the registry uses."""
    import math
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


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


def _wx_answer(rec: dict, dist_km: float, origin_note: str = "") -> str:
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
    age = _ago(ago) if ago is not None else "age unknown"
    readings = ", ".join(bits) or "no readings"
    origin = origin_note or "you"
    # A reading that far off is somebody else's weather, and has to say so
    # before anything else. 2M0SBP asked for Arisaig on 2026-09-20 and got a
    # reading from 146 km away in the same shape as one from down the road:
    # the distance was there, behind the callsign, and was read past.
    if dist_km > _WX_LOCAL_KM:
        return ("Nearest APRS weather is %.0fkm from %s, not local: %s %s: "
                "%s. My own feed only, not a forecast" % (
                    dist_km, origin, rec.get("callsign", "?"), age, readings))
    # Where it was measured FROM, not just how far. N1QQA-7 asked for the
    # weather in Wakefield NH on 2026-09-20 and was sent a reading from a
    # station 10 km from himself; the number was right, and the answer still
    # let him read it as the weather in the place he had named.
    return "%s %.0fkm from %s, %s: %s. My own feed only, not a forecast" % (
        rec.get("callsign", "?"), dist_km, origin, age, readings)


# A ham sign-off with a callsign in it: "73 de TA1ABC-7", "de TA1ABC",
# "73 TA1ABC". The callsign must be upper case and callsign-shaped, which is
# what keeps this off the Turkish word "de" - "Ankara da guzel" has nothing
# matching a callsign after it.
_SIGNOFF_CUE = re.compile(
    # The separator is not always a space. Told on 2026-09-20 to sign off
    # only once, the model answered "thanks, 73" with "73, TA3HX-14." - the
    # asker's own callsign behind a comma, which a \s+ cue walked straight
    # past. Punctuation counts, and so does the callsign coming first.
    r"\b(?:73\s+de|73|de)[\s,:;–—-]+"
    r"[A-Z0-9]{1,2}[0-9][A-Z]{1,4}(?:-[0-9]{1,2})?\b"
    r"|\b[A-Z0-9]{1,2}[0-9][A-Z]{1,4}(?:-[0-9]{1,2})?[\s,:;–—-]+73\b"
)


def _strip_signature(text: str) -> str:
    """Remove a callsign sign-off from an answer before it goes on air.

    Measured live. Asked "Test", the model replied:

        Test received. 73 de TA3HRJ-10 gateway.

    TA3HRJ-10 is the station that ASKED. The gateway signed itself with
    somebody else's callsign, on the air, on a service that had just been
    announced publicly.

    The system prompt forbids this in as many words - "you are not a station
    and have no callsign of your own, never sign as another callsign, never
    use DE with one". It said so, and the model did it anyway. That is the
    lesson §G and §H already taught twice: where an answer must not contain
    something, do not ask the model nicely, take it out afterwards.

    The sign-off is cut rather than snipped out, because it is a terminal
    construct - the "gateway." trailing after it in the live case is noise
    too. Whatever came before it is the answer.

    An answer that is nothing but a sign-off becomes "73", which is a real
    thing to say on the air and claims no callsign. That case matters more
    than it looks: it is the one where the entire transmission would have
    been a false identification.
    """
    m = _SIGNOFF_CUE.search(text)
    if not m:
        return text
    head = text[:m.start()].rstrip(" ,.;:-\t")
    if head:
        return head + ("" if head[-1] in ".!?" else ".")
    tail = text[m.end():].strip(" ,.;:-\t")
    return tail or "73"


# A first-person claim to have RECEIVED the sender, and a report token, in one
# sentence. Both halves are required. "RST = Readability, Signal, Tone" and
# "599 is a typical CW report" are correct answers about reports and must
# survive; "receiving you 5x9" is a measurement this service cannot have made.
_RX_CLAIM = re.compile(
    r"\b(?:receiv\w*|read\w*|copy\w*|hear\w*|get\w*)\s+(?:you|u)\b"
    r"|\byou(?:'re|\s+are)\s+(?:coming\s+in\s+)?(?:loud|[0-9R])",
    re.I,
)
_RX_REPORT = re.compile(
    r"\b5\s*[x/by\s-]{1,4}\s*9\b|\b59\b|\b599\b|\bS9\b|\bR5\b|loud and clear",
    re.I,
)


def _strip_signal_report(text: str) -> str:
    """Remove an invented signal report before the answer goes on air.

    Measured live. VK2AHB-7 sent "test.from VK" and the model replied:

        OK VK2AHB-7, receiving you 5x9. Test acknowledged. 73.

    This service has no receiver. VK2AHB-7 reached it from Australia through
    somebody else's igate and the APRS-IS backbone, over TCP. "5x9" is a
    measurement of a radio path that was never measured, sent to a station
    whose operator may well be testing that exact path.

    The system prompt already says "answer as a service" and "do not role-play
    a QSO". It said so, and the model did it anyway - the same way it signed
    with somebody else's callsign while the prompt forbade that in as many
    words. So this follows _strip_signature: the rule lives in the code.

    The offending SENTENCE is dropped rather than the token patched out,
    because "receiving you 5x9" with the number removed is still a claim to
    have received. Whatever else the answer said is kept.
    """
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [p for p in parts
            if not (_RX_CLAIM.search(p) and _RX_REPORT.search(p))]
    if len(kept) == len(parts):
        return text
    out = " ".join(kept).strip()
    # Everything the answer said was the false report. Say the true thing
    # instead of nothing: silence would read as a failed gateway.
    return out or "Received. Internet-fed service, no signal report possible."


# A test or ping, and nothing else. Kept deliberately tight: the message must
# START with the word and be short, so "what is the SWR test procedure" is a
# question and goes to the model like any other.
_TEST_MSG = re.compile(r"^\s*(?:test|ping|deneme)\b", re.I)

# "What can you do?" — the question a newcomer sends before any real one.
# Tight in the same way: it has to be about the service, so "can you help me
# convert 5 miles" is a question and goes to the model.
_HELP_MSG = re.compile(
    r"^\s*(?:help|\?+|commands?|menu)\s*[?!.]*\s*$"
    r"|what\s+(?:else\s+)?(?:can|do)\s+(?:you|u)\s+do"
    r"|what\s+are\s+you\s+for"
    r"|^\s*(?:hello,?\s+)?can\s+you\s+help\s+me\s*[?!.]*\s*$"
    # Asked sideways, which is how two stations asked it on 2026-09-20:
    # "I wonder what you can help me with." Anchored at the end, so
    # "can you help me with converting miles" is a request and goes to
    # the model.
    r"|what\s+(?:you\s+can|can\s+you)\s+help\s+(?:me\s+)?with\s*[?!.]*\s*$"
    r"|^\s*can\s+you\s+help\s+me\s+with\s+(?:anything|something)\s*[?!.]*\s*$",
    re.I)
_HELP_MSG_TR = re.compile(
    r"^\s*(?:yardim|yardım|komutlar)\s*[?!.]*\s*$"
    r"|ne(?:ler)?\s+yapabilirsin"
    r"|nas[iı]l\s+kullan",
    re.I)

# Two facts and a boundary, in the order someone meeting it needs them.
# Deliberately not a command list: there are no commands, and promising some
# would be the next thing to go stale.
_HELP_TEXT = ("I answer short questions sent as APRS messages. Also: your own "
              "station (ask where am I), nearest APRS weather, and TEST. No "
              "news, no other stations' positions.")
_HELP_TEXT_TR = ("APRS mesajıyla gelen kısa soruları yanıtlarım. Ayrıca: kendi "
                 "istasyonun (neredeyim), en yakın APRS hava ölçümü ve TEST. "
                 "Haber yok, başka istasyonların konumu yok.")

# How much of a conversation rides along with the next question, and for how
# long. On 2026-09-20 DL5XL-9 asked for the best way from Bremen to Berlin,
# then "How long would it take by car?", and was told to name the two places:
# each question reached the model alone. He re-sent the same pair four times
# over. Three exchanges is enough for a follow-up and short enough that a
# stale subject cannot steer a new question; ten minutes is the same window
# the dedup cache uses. Kept in memory only and never written down - this is
# other people's traffic, public on the air but not ours to file.
_HISTORY_TURNS = 3
_HISTORY_TTL_S = 600.0

# Two packets carrying the same words but different message numbers. A client
# that gave up waiting and sent the question again numbers the second one
# afresh, so sender-plus-number sees two questions where the person asked one:
# KC1MUR-5 sent "When was Dream Police by cheap trick released" twice inside a
# minute on 2026-09-20 and it cost two provider calls and two near-identical
# answers on a shared channel. Two minutes is the shape of someone re-sending
# because nothing came back; past that, asking again is asking again.
_TEXT_DEDUP_S = 120.0
_PUNCT = re.compile(r"[^A-Z0-9]+")

# Infrastructure questions. An igate, a digipeater or a weather station
# beacons precisely so that others can find it; answering about one is not
# the same act as answering about a person who happens to carry a tracker.
_IGATE_NEAR = re.compile(
    r"\b(?:NEAREST|CLOSEST|LOCAL)\s+(?:APRS\s+)?(?:IGATE|I-GATE|GATE|DIGI\w*)"
    r"|\bIGATES?\s+NEAR\b|\bEN\s+YAKIN\s+(?:IGATE|DIGI\w*)", re.I)
_IGATE_MINE = re.compile(
    r"\bWHICH\s+IGATE\b|\bWHAT\s+IGATE\b|\bMY\s+IGATE\b"
    r"|\bWHO\s+IS\s+GATING\s+ME\b|\bGATED?\s+ME\b|\bHEARS?\s+ME\b"
    r"|\bBEN[İI]\s+(?:K[İI]M|HANG[İI]\s+IGATE)\s+DUYUYOR", re.I)

# Propagation: the program measures openings and draws them on its own map,
# and was sending people to another site to ask about them.
_PROP_ASK = re.compile(
    r"\bPROPAGATION\b|\bBAND\s+OPEN|\bOPENINGS?\b|\bDX\s+CONDITIONS?\b"
    r"|\bYAYILIM\b|\bA[CÇ]ILIM", re.I)

# Asking to be left out of third-party answers, and asking back in. A whole
# message and nothing else, so it cannot be tripped by a sentence about
# lookups.
_OPTOUT_MSG = re.compile(r"^\s*(NO\s*LOOKUP|NOLOOKUP|GORUNME|G[ÖO]R[ÜU]NME)\s*[.!]*\s*$", re.I)
_OPTIN_MSG = re.compile(r"^\s*(LOOKUP|GORUN|G[ÖO]R[ÜU]N)\s*[.!]*\s*$", re.I)
_OPTOUT_FILE = "ai_gateway_nolookup"

# A message meant for somebody else, arriving here by mistake or in the hope
# that this thing passes messages on. KE4PIC sent "CHASE DL7PJ gm Peter"
# twice on 2026-09-20 and the model read the greeting as addressed to itself
# and answered "Hi Peter" - to Frank. A greeting plus a callsign that is
# neither ours nor the sender's, and no question anywhere, is the shape of
# it; a question that merely names another station is still a question.
_GREETING = re.compile(
    r"\b(?:GM|GA|GE|GN|HI|HELLO|HEY|73|88|TNX|THANKS|THX|QSL|CQ"
    r"|SELAM|MERHABA|G[UÜ]NAYDIN|KOLAY\s+GELS[İI]N)\b", re.I)
_QUESTIONISH = re.compile(
    r"\?|\b(?:WHAT|WHERE|WHO|WHEN|WHY|HOW|WHICH|CAN|COULD|DOES|DO|IS|ARE"
    r"|TELL|GIVE|EXPLAIN|NEDIR|NEREDE|KIM|NASIL|NE\s+KADAR|MISIN|MUSUN)\b",
    re.I)

# How far out an opening still counts as "near me". Openings are measured
# between a station and the igate that heard it, and either end being close
# is what makes the opening relevant to the asker.
_PROP_NEAR_KM = 400.0
_PROP_RECENT_S = 3 * 3600.0
_IGATE_RADIUS_KM = 250.0
_IGATE_TYPES = ("igate", "gateway")

# Repeaters are infrastructure in the same sense: they beacon in order to be
# found, and the registry held 7,940 of them with positions on the day
# 2M0SBP-5 asked for the nearest one and was sent to a website.
_REPEATER_NEAR = re.compile(
    r"\b(?:NEAREST|CLOSEST|LOCAL)\s+(?:APRS\s+)?(?:REPEATER|RPT)"
    r"|\bREPEATERS?\s+(?:NEAR|AROUND)\b"
    r"|\bEN\s+YAKIN\s+(?:R[ÖO]LE|AKTAR\w*)", re.I)
_REPEATER_TYPES = ("repeater",)


def _text_key(sender_base: str, text: str) -> str:
    """Sender and question, with case, spacing and punctuation taken out."""
    return sender_base + ":" + _PUNCT.sub(" ", text.upper()).strip()

# The fixed answer goes out at most this often to one sender. It is free of
# the model and free of the token bucket, and that is exactly what would make
# it a way to key a distant transmitter on demand if it answered every time.
_HELP_REPEAT_S = 600.0

# A question that mentions the weather while asking for something else. The
# weather shortcut matches a word anywhere in the text, which is what sent a
# temperature reading to someone who asked for a joke about the weather.
_NOT_A_LOOKUP = re.compile(
    r"\b(joke|jokes|funny|pun|riddle|poem|haiku|song|story|limerick|"
    r"şaka|saka|fıkra|fikra|şiir|siir|şarkı|sarki|hikaye|bilmece)\b", re.I)


def _test_answer(question: str, sender_full: str, raw_line: str) -> "Optional[str]":
    """Answer a test message from the packet itself, without asking the model.

    A test is the commonest thing anyone sends a service callsign, and it is
    the one question where every true fact is already in our hands: who sent
    it, which igate put it on APRS-IS, and whether it touched RF at all. It is
    also the question the model answered by inventing a signal report.

    So it never reaches the model. What comes back is what the packet says,
    and an explicit statement that no signal report is possible here - which
    is the fact the tester actually needs.
    """
    if not _TEST_MSG.match(question) or len(question) > 32:
        return None
    gate, internet = "", False
    try:
        from packet_parser import parse_packet
        p = parse_packet(raw_line)
        gate = p.get("gate") or ""
        # qAC/qAS mean the sender was connected to APRS-IS directly; no igate
        # heard them, so naming one would be as invented as the 5x9 was.
        internet = bool(p.get("tcpip")) or p.get("q_type") in ("C", "S")
    except Exception:
        pass
    if internet or not gate:
        where = "via APRS-IS"
    else:
        where = "gated by " + gate
    return ("Test OK %s, %s. Internet-fed service - I cannot give a signal "
            "report." % (sender_full, where))


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


# Message numbers are how an APRS client recognises a message it has already
# shown: a repeat of sender and number is acknowledged and then discarded.
# The counter used to start from zero on every restart, so the first reply of
# every process was numbered 2 and 4 whoever it went to, and a station that
# had heard DMWGPT before could acknowledge a new answer and never display
# it (2026-09-19, tools/check_msg_ids.py). The counter is now kept next to
# the config file; without one it starts from the clock, so two lifetimes do
# not start from the same place.
_MSGID_MAX = 99999          # the APRS message format allows 1-5 characters
_MSGID_TICK_S = 30          # one number per 30 s of clock: a 35-day cycle
_MSGID_FILE = "ai_gateway_msgid"
_clock = time.time


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

    # Below this, a second copy is a client sending twice rather than a person
    # who gave up waiting. Our own answer is on its way within a second or
    # two; a client that retries takes tens of seconds to decide it did not
    # arrive.
    _REPLAY_MIN_AGE_S = 25.0

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
        self._msgid_path = (Path(config_path).with_name(_MSGID_FILE)
                            if config_path else None)
        self._msgid_warned = False
        self._msg_counter = self._load_msg_counter()
        # Token bucket per sender: a burst of questions costs nothing, and the
        # refill only bites on sustained hammering. A flat cooldown would have
        # punished exactly the people worth having — someone meeting the thing
        # for the first time asks three or four questions back to back.
        self._buckets: dict[str, list] = {}   # sender -> [tokens, last_refill, told]
        self._help_at: dict[str, float] = {}  # sender -> when the help text went out
        # sender -> [(ts, question, answer), ...], newest last. Memory only.
        self._history: dict[str, list] = {}
        # normalised question -> (expiry, the dedup key it was first filed
        # under), so a re-send with a fresh message number finds the original.
        self._text_keys: dict[str, tuple] = {}
        # Stations that asked not to be looked up by others. Public data, but
        # the subject gets a lever: that is what makes answering defensible.
        self._optout_path = (Path(config_path).with_name(_OPTOUT_FILE)
                             if config_path else None)
        self._optout: set = self._load_optout()
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

    async def _wx_lookup(self, question: str, sender_full: str,
                         cfg: dict) -> "Optional[str]":
        """Nearest weather station to the sender, or to a grid they name.

        Returns None when the question is not about weather, so everything
        else follows the ordinary path.

        No geocoding: a city name is refused rather than guessed. We have no
        gazetteer, and naming the wrong Izmir is worse than saying no.
        """
        db = self._station_db
        if db is None:
            return None
        radius = float(cfg.get("wx_radius_km") or _WX_RADIUS_KM)
        text = question.upper()
        if not any(w in text for w in ("WEATHER", "WX ", " WX", "TEMP", "FORECAST",
                                       "HAVA DURUMU", "HAVA NASIL", "SICAKLIK",
                                       "YAGMUR", "RAIN")):
            return None
        # Naming the weather is not asking for it. A reading is a poor answer
        # to "tell me a joke about the weather", which is what one went out as.
        if _NOT_A_LOOKUP.search(question):
            return None

        # where to measure from
        origin, origin_note = None, ""
        if _POSTCODE_IN_TEXT.search(text):
            return ("I cannot read postcodes or place names. Send a Maidenhead "
                    "grid like IO76 and I will measure from there.")
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
                None, db.nearest_wx, origin[0], origin[1], radius)
        except Exception as e:
            self.error(f"wx scan failed: {e}")
            return None

        if hit is None:
            return ("No APRS weather station within %.0fkm of %s in my records. "
                    "Try a weather service." % (radius, origin_note))
        rec, dist_km = hit
        self.log("wx lookup: %s -> %s at %.0fkm"
                 % (sender_full, rec.get("callsign"), dist_km))
        return _wx_answer(rec, dist_km,
                          "you" if origin_note == "your last position"
                          else origin_note)

    def _load_optout(self) -> set:
        """Callsigns that asked to be left out, from the file beside the config."""
        if self._optout_path is None:
            return set()
        try:
            return {ln.strip().upper() for ln
                    in self._optout_path.read_text(encoding="ascii").split()
                    if ln.strip()}
        except OSError:
            return set()

    def _save_optout(self) -> None:
        if self._optout_path is None:
            return
        try:
            tmp = self._optout_path.with_name(_OPTOUT_FILE + ".tmp")
            tmp.write_text("\n".join(sorted(self._optout)) + "\n",
                           encoding="ascii")
            os.replace(tmp, self._optout_path)
        except OSError as e:
            self.warn("opt-out list not saved: " + str(e))

    def _optout_command(self, question: str, sender_base: str) -> "Optional[str]":
        """Let a station take itself out of other people's answers, or back in.

        Only ever about the sender's own callsign - the packet header is the
        only proof of identity there is here, and it proves exactly one thing.
        """
        if not sender_base:
            return None
        if _OPTOUT_MSG.match(question):
            self._optout.add(sender_base)
            self._save_optout()
            self.log(f"opt-out: {sender_base} will not be looked up")
            return ("Noted. I will not tell others where %s is. Send LOOKUP "
                    "to undo. Your beacons stay public on aprs.fi."
                    % sender_base)
        if _OPTIN_MSG.match(question):
            if sender_base in self._optout:
                self._optout.discard(sender_base)
                self._save_optout()
            self.log(f"opt-in: {sender_base} may be looked up")
            return ("Noted. %s can be looked up here again. Send NOLOOKUP to "
                    "opt out." % sender_base)
        return None

    def _misaddressed(self, question: str, sender_base: str,
                      my_call: str) -> "Optional[str]":
        """A greeting for a third station, answered as what it is.

        The gateway is not a relay: anything it sends goes out under its own
        addressee, from somebody else's igate. Saying so is more use to the
        sender than a model pretending to be the person they meant.
        """
        if _QUESTIONISH.search(question) or not _GREETING.search(question):
            return None
        mine = {strip_ssid(my_call).upper(), sender_base}
        for base, ssid in _CALL_IN_TEXT.findall(question.upper()):
            if base not in mine:
                return ("I do not pass messages on - I only answer what is "
                        "sent to me. Send it to %s directly." % base)
        return None

    def _sender_origin(self, sender_full: str, sender_base: str):
        """Where the asker is, from their own beacon, or None."""
        db = self._station_db
        if db is None:
            return None
        try:
            rec = db.get_one(sender_full) or db.get_one(sender_base)
        except Exception as e:
            self.error(f"registry lookup failed: {e}")
            return None
        if rec and rec.get("lat") is not None and rec.get("lon") is not None:
            return (rec["lat"], rec["lon"])
        return None

    def _igate_mine(self, question: str, sender_full: str, sender_base: str,
                    raw_line: str) -> "Optional[str]":
        """Which igate put this sender on APRS-IS, from the packet in hand.

        The path is the truth here, and it is already parsed. A sender who
        came in over the internet has no igate at all, and being told that is
        the answer to the question they asked.
        """
        if not _IGATE_MINE.search(question):
            return None
        gate, internet = "", False
        try:
            from packet_parser import parse_packet
            p = parse_packet(raw_line)
            gate = p.get("gate") or ""
            internet = bool(p.get("tcpip")) or p.get("q_type") in ("C", "S")
        except Exception as e:
            self.error(f"path parse failed: {e}")
        # A qAC path names the core server that accepted the connection, not
        # an igate that heard anything. Reading it as an igate would tell a
        # phone-app user that a station in another hemisphere is receiving
        # them (station_db.is_backbone_gate, written for the same confusion).
        try:
            from station_db import is_backbone_gate
            if is_backbone_gate(gate):
                gate = ""
        except Exception:
            pass
        if internet and not gate:
            return ("No igate is hearing you: this message reached me over "
                    "the internet, not RF.")
        if not gate:
            db = self._station_db
            rec = None
            if db is not None:
                try:
                    rec = db.get_one(sender_full) or db.get_one(sender_base)
                except Exception:
                    rec = None
            gate = (rec or {}).get("last_gate") or ""
            if not gate:
                return ("I cannot see which igate heard you - this message "
                        "carries no gate in its path.")
            return "Last gated by %s, from my records." % gate
        extra = ""
        origin = self._sender_origin(sender_full, sender_base)
        db = self._station_db
        if origin and db is not None:
            try:
                grec = db.get_one(gate)
            except Exception:
                grec = None
            if grec and grec.get("lat") is not None:
                km = _haversine_km(origin[0], origin[1],
                                   grec["lat"], grec["lon"])
                extra = ", %.0fkm from you" % km
        return "%s gated this message%s." % (gate, extra)

    async def _igate_near(self, question: str, sender_full: str,
                          sender_base: str) -> "Optional[str]":
        """The closest igates - or repeaters - to the asker, from the registry.

        Both are infrastructure that beacons in order to be found. The origin
        is a grid if the question names one, and the asker's own last beacon
        otherwise; a postcode is neither, and says so.
        """
        if _REPEATER_NEAR.search(question):
            kinds, label = _REPEATER_TYPES, "repeaters"
        elif _IGATE_NEAR.search(question):
            kinds, label = _IGATE_TYPES, "igates"
        else:
            return None
        db = self._station_db
        if db is None:
            return None
        text = question.upper()
        if _POSTCODE_IN_TEXT.search(text):
            return ("I cannot read postcodes or place names. Send a Maidenhead "
                    "grid like IO76 and I will measure from there.")
        origin, whence = None, "you"
        grid = _GRID_IN_TEXT.search(text)
        if grid:
            origin = _grid_to_latlon(grid.group(1))
            whence = grid.group(1)
        if origin is None:
            origin = self._sender_origin(sender_full, sender_base)
        if origin is None:
            return ("I do not know where you are - I have no position for "
                    "your callsign. Send a beacon first, or name a grid.")
        try:
            hits = await asyncio.get_event_loop().run_in_executor(
                None, db.nearest_of_type, origin[0], origin[1],
                kinds, _IGATE_RADIUS_KM, 2)
        except Exception as e:
            self.error(f"{label} scan failed: {e}")
            return None
        if not hits:
            return ("No %s within %.0fkm of %s in my records."
                    % (label[:-1], _IGATE_RADIUS_KM, whence))
        bits = []
        for rec, km in hits:
            call = rec.get("callsign") or "?"
            seen = ""
            try:
                if db.has_gated(call):
                    seen = " (seen gating)"
            except Exception:
                pass
            bits.append("%s %.0fkm%s" % (call, km, seen))
        return ("Nearest %s to %s: %s. My own feed only."
                % (label, whence, "; ".join(bits)))

    async def _prop_near(self, question: str, sender_full: str,
                         sender_base: str) -> "Optional[str]":
        """Openings this program measured, near the asker.

        KR4MVP-5 asked for propagation and was sent to another site by the
        program that had just measured 247 openings that week.
        """
        if not _PROP_ASK.search(question):
            return None
        db = self._station_db
        if db is None:
            return None
        origin = self._sender_origin(sender_full, sender_base)
        if origin is None:
            return ("I do not know where you are, so I cannot pick out "
                    "openings near you. Send a beacon first.")
        try:
            summary = await asyncio.get_event_loop().run_in_executor(
                None, db.prop_summary, 200)
        except Exception as e:
            self.error(f"prop summary failed: {e}")
            return None
        now = _clock()
        near = []
        for ln in summary.get("links", []):
            if now - float(ln.get("ts") or 0) > _PROP_RECENT_S:
                continue
            for la, lo in ((ln.get("s_lat"), ln.get("s_lon")),
                           (ln.get("g_lat"), ln.get("g_lon"))):
                if la is None or lo is None:
                    continue
                if _haversine_km(origin[0], origin[1], la, lo) <= _PROP_NEAR_KM:
                    near.append(ln)
                    break
        if not near:
            return ("No openings measured near you in the last 3h. That is "
                    "my own feed, not a forecast.")
        near.sort(key=lambda l: float(l.get("km") or 0), reverse=True)
        best = near[0]
        return ("%d opening(s) near you in 3h; longest %s-%s %.0fkm, %s. "
                "My own feed, not a forecast."
                % (len(near), best.get("call") or "?", best.get("gate") or "?",
                   float(best.get("km") or 0),
                   _ago(now - float(best.get("ts") or now))))

    def _other_lookup(self, question: str, sender_base: str,
                      sender_full: str) -> "Optional[str]":
        """Another station's last position, as the map already shows it.

        APRS positions are broadcast to be seen, and aprs.fi has served them
        for years - refusing here protects nobody while the same fact is one
        web page away. What this does not do is the step that turns a
        callsign into a person: no licence lookup, no name, no address, and
        no history beyond the one observation the registry holds. A station
        that has sent NOLOOKUP is left out, and the refusal says so rather
        than pretending the data is missing.
        """
        db = self._station_db
        if db is None:
            return None
        text = question.upper()
        if not any(w in text for w in ("WHERE", "LOCAT", "HEARD", "HOW FAR",
                                       "DISTANCE", "NEREDE", "KONUM",
                                       "UZAKLIK", "NE KADAR UZAK")):
            return None
        found = [b + (s or "") for b, s in _CALL_IN_TEXT.findall(text)
                 if strip_ssid(b).upper() != sender_base]
        if not found:
            # A question about distance that names no station and no grid is
            # about a place, and places are what this has no way to find.
            if any(w in text for w in ("HOW FAR", "DISTANCE", "UZAK")):
                return ("I cannot look up place names. Give me a callsign or "
                        "a grid like EM97 and I will measure from your last "
                        "beacon.")
            return None
        wanted = found[0]
        base = strip_ssid(wanted).upper()
        if base in self._optout:
            return ("%s has asked not to be looked up through this gateway. "
                    "Their beacons are still public on aprs.fi." % base)
        try:
            rec = db.get_one(wanted) or db.get_one(base)
        except Exception as e:
            self.error(f"registry lookup failed: {e}")
            return None
        answer = _station_answer(db, wanted, rec)
        if rec and rec.get("lat") is not None:
            origin = self._sender_origin(sender_full, sender_base)
            if origin:
                km = _haversine_km(origin[0], origin[1],
                                   rec["lat"], rec["lon"])
                answer = answer.replace(". My own feed only",
                                        ", %.0fkm from you. My own feed only"
                                        % km)
        self.log(f"lookup: {sender_base} asked about {wanted}")
        return answer

    def _recent_turns(self, sender_base: str) -> "list[tuple[str, str]]":
        """The sender's last few exchanges, newest last, dropping stale ones."""
        turns = self._history.get(sender_base)
        if not turns:
            return []
        cutoff = _clock() - _HISTORY_TTL_S
        turns = [t for t in turns if t[0] >= cutoff]
        if turns:
            self._history[sender_base] = turns
        else:
            self._history.pop(sender_base, None)
        return [(q, a) for _, q, a in turns[-_HISTORY_TURNS:]]

    def _remember(self, sender_base: str, question: str, answer: str) -> None:
        """Keep one exchange for the next question from the same station."""
        if not sender_base or not question or not answer:
            return
        now = _clock()
        turns = self._history.setdefault(sender_base, [])
        turns.append((now, question, answer))
        del turns[:-_HISTORY_TURNS]
        # A worldwide feed reaches this dict; drop whoever has gone quiet
        # rather than let it grow.
        if len(self._history) > 500:
            cutoff = now - _HISTORY_TTL_S
            for k in [k for k, v in self._history.items()
                      if not v or v[-1][0] < cutoff]:
                del self._history[k]

    def _help_answer(self, question: str, sender_base: str) -> "Optional[str]":
        """What this service can do, said by the code rather than the model.

        Returns None when the question is not about the service, and also when
        the same sender was told within the last _HELP_REPEAT_S — then it
        follows the ordinary path, limiter included. Answering every time
        would hand anyone a way to make a gateway transmit on demand for free.

        A model asked "what can you do" invents an answer, which is how a
        newcomer ends up with a list of things this gateway does not do.
        """
        tr = bool(_HELP_MSG_TR.search(question))
        if not tr and not _HELP_MSG.search(question):
            return None
        now = _clock()
        last = self._help_at.get(sender_base, 0.0)
        if now - last < _HELP_REPEAT_S:
            return None
        self._help_at[sender_base] = now
        if len(self._help_at) > 2000:
            cutoff = now - _HELP_REPEAT_S
            for k in [k for k, v in self._help_at.items() if v < cutoff]:
                del self._help_at[k]
        return _HELP_TEXT_TR if tr else _HELP_TEXT

    def _self_lookup(self, question: str, sender_base: str,
                     sender_full: str = "") -> "Optional[str]":
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
            # "my location" names nobody, but the packet header does. Without
            # this the question fell through to the model, which correctly
            # said it had no position - while the registry held a beacon from
            # four minutes earlier (F-2026-09-10-02).
            if _SELF_IN_TEXT.search(text):
                wanted = sender_full or sender_base
                try:
                    rec = db.get_one(wanted) or db.get_one(sender_base)
                except Exception as e:
                    self.error(f"registry lookup failed: {e}")
                    return None
                self.log(f"self-lookup: {wanted} asked about itself, unnamed")
                return _station_answer(db, wanted, rec)
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
        # A question about somebody else is not refused here any more; it
        # goes on to _other_lookup, which answers what the map already shows
        # and honours a station's own NOLOOKUP.
        return None

    async def _ask_ai(self, question: str, sender: str = "",
                      history: "Optional[list]" = None) -> str:
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
        # The station's last few exchanges, in the shape both providers take.
        # Each turn is one short APRS message and its answer, so this adds a
        # few hundred characters to a call and buys a follow-up that knows
        # what it is following.
        turns = []
        for prev_q, prev_a in (history or []):
            turns.append({"role": "user", "content": prev_q})
            turns.append({"role": "assistant", "content": prev_a})
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
                            "messages": turns + [{"role": "user",
                                                  "content": question}],
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
                    messages=[{"role": "system", "content": system_prompt}]
                    + turns + [{"role": "user", "content": question}],
                    extra_body=extra_body,
                )
                return resp.choices[0].message.content.strip()

        try:
            answer = await loop.run_in_executor(None, _do_ask)
            return _to_ascii(answer)
        except Exception as e:
            self.error(f"AI query failed: {type(e).__name__}: {e}")
            # Swallowed on purpose - the sender gets silence rather than a
            # stack trace - but silence is exactly what hid this for a day.
            # Type name only: a client's message can carry the request URL.
            self.mark_broken(f"AI query failed: {type(e).__name__}")
            return ""

    def _load_msg_counter(self) -> int:
        """Where the previous lifetime stopped, or a point set by the clock."""
        if self._msgid_path is not None:
            try:
                n = int(self._msgid_path.read_text(encoding="ascii").strip())
                if 0 < n <= _MSGID_MAX:
                    return n
            except (OSError, ValueError):
                pass
        return int(_clock() // _MSGID_TICK_S) % _MSGID_MAX

    def _next_msg_id(self) -> str:
        self._msg_counter = self._msg_counter % _MSGID_MAX + 1
        if self._msgid_path is not None:
            try:
                tmp = self._msgid_path.with_name(_MSGID_FILE + ".tmp")
                tmp.write_text(str(self._msg_counter), encoding="ascii")
                os.replace(tmp, self._msgid_path)
            except OSError as e:
                if not self._msgid_warned:
                    self._msgid_warned = True
                    self.warn("message number not saved, a restart falls "
                              f"back to the clock: {e}")
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

        # Another machine. On 2026-09-20 the store-and-forward service QRX
        # sent its own advert here, the model answered it as a person and
        # invented "your message to N1QQA is queued and will go out on the
        # next beacon", and the two services exchanged eleven packets in
        # forty seconds before the rate limiter stopped it. APRS service
        # names are not callsign-shaped - QRX, WXBOT, SMSGTE, EMAIL-2 carry
        # no digit where a callsign must - so this breaks the loop at the
        # cheapest point, before the ack. A licensed station always has a
        # callsign; a tactical name that wants an answer can ask from one.
        if not looks_like_callsign(sender_base):
            self.log(f"ignoring {sender_full}: not a callsign, likely an "
                     f"automatic station")
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
        now_ts = _clock()
        if self._processed:
            for k in [k for k, v in self._processed.items() if v[0] <= now_ts]:
                del self._processed[k]
        dedup_key = f"{sender_full}:{msg_id or raw_msg}"
        # A re-send numbered afresh is the same question. Look it up by its
        # words as well, and if it was asked moments ago, answer it as the
        # repeat it is rather than buying a second answer.
        tkey = _text_key(sender_base, raw_msg)
        if self._text_keys:
            for k in [k for k, v in self._text_keys.items() if v[0] <= now_ts]:
                del self._text_keys[k]
        prior = self._text_keys.get(tkey)
        if (prior is not None and dedup_key not in self._processed
                and prior[1] in self._processed):
            dedup_key = prior[1]
        else:
            self._text_keys[tkey] = (now_ts + _TEXT_DEDUP_S, dedup_key)
        seen = self._processed.get(dedup_key)
        if seen is not None:
            # Asking again almost always means the answer never arrived — an
            # igate did not gate it back, or the path dropped it. Staying
            # silent turns a delivery failure into a permanent one, so the
            # cached answer goes out again. No AI call; the cost is one more
            # transmission on a path that already failed once.
            exp, cached, left = seen
            # How long ago the question first arrived. A copy that lands in
            # the same breath is the sender's own client sending twice -
            # N1QQA's did on 2026-09-20, and every answer went out twice for
            # it. A replay is for somebody who waited and heard nothing, and
            # waiting takes longer than this.
            asked_ago = now_ts - (exp - self._DEDUP_TTL_S)
            if cached and asked_ago < self._REPLAY_MIN_AGE_S:
                self.log(f"duplicate from {sender_full} after {asked_ago:.0f}s"
                         f", not replaying")
                return None
            if cached and left > 0 and self._own_writer:
                self._processed[dedup_key] = (exp, cached, left - 1)
                self.log(f"replaying answer to {sender_full} ({left - 1} left)")
                for i, part in enumerate(_split_message(
                        cached, 1 + int(cfg.get("extra_sms", 0)))):
                    await self._send_reply(my_call, sender_full, part)
                    if i:
                        await asyncio.sleep(5)
                return None
            if not cached:
                # Still waiting on the model for this very message. This is
                # the retry the cache exists to absorb, and answering it twice
                # would cost two calls for one question.
                return None
            # The replays are used up and the sender is still asking. Silence
            # here is what DL5XL-9 met on 2026-09-20 at the third repeat, and
            # it is indistinguishable from a dead gateway. The answer goes out
            # again - still no model call, one question is still one call -
            # but from here on each copy costs a token, so how often someone
            # may ask is the bucket's decision rather than a flat cap.
            allowed, notice = self._allow_rate(sender_base, cfg)
            if not allowed:
                self.mark_working()
                self.warn(f"rate-limited {sender_full} (past replays)")
                if notice:
                    await self._send_reply(my_call, sender_full, notice)
                return None
            self.log(f"resending answer to {sender_full} (replays spent)")
            for i, part in enumerate(_split_message(
                    cached, 1 + int(cfg.get("extra_sms", 0)))):
                await self._send_reply(my_call, sender_full, part)
                if i:
                    await asyncio.sleep(5)
            self.mark_working()
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
            # A wildcard entry is a prefix, and a prefix admits identifiers
            # that are not stations: "TA*" is meant as "Turkish operators" and
            # also matches TACTICAL, ANSRVR-style group addressees and object
            # names. Here that is not merely untidy — it decides who this
            # gateway answers, and every answer is a provider call and a
            # transmission. An exact entry still matches exactly, because
            # naming an identifier is meaning it (F-2026-09-06-02).
            if not any(
                (sender_base.startswith(w[:-1])
                 and looks_like_callsign(sender_base)) if w.endswith("*")
                else sender_base == w
                for w in whitelist
            ):
                self.warn(f"blocked {sender_full} — not in whitelist")
                return None

        # Before the limiter, because it costs neither a model call nor a
        # token. On 2026-09-20 a newcomer spent his burst on four questions
        # and then asked what else it could do; the limiter refused that one
        # and the one he sent after it, so the only question of the day left
        # unanswered was the one with a fixed answer sitting in the code.
        help_text = self._help_answer(question, sender_base)
        if help_text is not None:
            self.log(f"RX from {sender_full}: {question}")
            prev = self._processed.get(dedup_key)
            if prev is not None:
                self._processed[dedup_key] = (prev[0], help_text, prev[2])
            # Folded like a model answer: the Turkish text is written with
            # its own letters and APRS carries ASCII.
            parts = _split_message(_to_ascii(help_text),
                                   1 + int(cfg.get("extra_sms", 0)))
            for i, part in enumerate(parts):
                await self._send_reply(my_call, sender_full, part)
                self.log(f"TX to {sender_full}: {part}")
                if i < len(parts) - 1:
                    await asyncio.sleep(5)
            self.mark_working()
            return None

        allowed, notice = self._allow_rate(sender_base, cfg)
        if not allowed:
            self.mark_working()
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
        answer = _test_answer(question, sender_full, line)
        if answer is None:
            answer = self._optout_command(question, sender_base)
        if answer is None:
            answer = self._misaddressed(question, sender_base, my_call)
        if answer is None:
            answer = self._self_lookup(question, sender_base, sender_full)
        if answer is None:
            answer = self._igate_mine(question, sender_full, sender_base, line)
        if answer is None:
            answer = await self._igate_near(question, sender_full, sender_base)
        if answer is None:
            answer = await self._prop_near(question, sender_full, sender_base)
        if answer is None:
            answer = self._other_lookup(question, sender_base, sender_full)
        if answer is None:
            answer = await self._wx_lookup(question, sender_full, cfg)
        if answer is None:
            # Only now, with the free answers exhausted, does this cost money.
            allowed, notice = self._allow_daily(cfg)
            if not allowed:
                self.mark_working()
                self.warn(f"daily limit reached, refused {sender_full}"
                          + (" (told)" if notice else ""))
                if notice:
                    await self._send_reply(my_call, sender_full, notice)
                return None
            answer = await self._ask_ai(question, sender_full,
                                        self._recent_turns(sender_base))
        if not answer:
            # Asked, and came back empty. Whatever the cause, this station was
            # left waiting, and that is the thing the badge has to be able to
            # say out loud.
            self.mark_broken("asked, but produced no answer")
            return None

        self.log(f"AI response: {answer}")

        # Last thing before it becomes a transmission. The prompt forbids a
        # callsign sign-off; this is what makes that true. Warned rather than
        # marked broken - the module worked, the model misbehaved, and the
        # warning is also how we find out how often it does.
        cleaned = _strip_signature(answer)
        if cleaned != answer:
            self.warn(f"stripped a callsign sign-off: {answer!r} -> {cleaned!r}")
            answer = cleaned
        cleaned = _strip_signal_report(answer)
        if cleaned != answer:
            self.warn(f"stripped an invented signal report: "
                      f"{answer!r} -> {cleaned!r}")
            answer = cleaned
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

        # Kept for the next question from this station, for ten minutes.
        self._remember(sender_base, question, answer)
        self.mark_working()
        return None
