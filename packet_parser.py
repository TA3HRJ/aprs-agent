"""
Packet Parser
=============
Rule-based extraction of structured data from raw APRS-IS packet strings.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import re
import time
from typing import Any, Optional

# ---------------------------------------------------------------------------
# APRS symbol type classification
# Maps (table, symbol) → station type label
# ---------------------------------------------------------------------------
_SYMBOL_TYPE: dict[tuple[str, str], str] = {
    ("/", "#"): "digi",
    ("/", "&"): "gateway",
    ("/", "'"): "aircraft",
    ("/", "-"): "house",
    ("/", "."): "x-mark",
    ("/", "/"): "mobile",
    ("/", ";"): "tent",
    ("/", "<"): "motorcycle",
    ("/", ">"): "car",
    ("/", "?"): "server",
    ("/", "@"): "hurricane",
    ("/", "A"): "aid",
    ("/", "E"): "echolink",
    ("/", "I"): "igate",
    ("/", "O"): "balloon",
    ("/", "R"): "recreation",
    ("/", "S"): "space",
    ("/", "W"): "water",
    ("/", "_"): "weather",
    ("/", "a"): "ambulance",
    ("/", "b"): "bike",
    ("/", "c"): "incident",
    ("/", "e"): "eyeball",
    ("/", "f"): "fire",
    ("/", "g"): "glider",
    ("/", "h"): "hotel",
    ("/", "i"): "igate",
    ("/", "j"): "jeep",
    ("/", "k"): "truck",
    ("/", "n"): "triangle",
    ("/", "p"): "dog",
    ("/", "r"): "repeater",
    ("/", "s"): "ship",
    ("/", "t"): "truck",
    ("/", "u"): "bus",
    ("/", "v"): "van",
    ("/", "w"): "water",
    ("/", "y"): "yacht",
    ("\\", "#"): "digi",
    ("\\", "&"): "gateway",
    ("\\", "E"): "echolink",
    ("\\", "I"): "igate",
    ("\\", "a"): "ambulance",
    ("\\", "r"): "repeater",
    ("\\", "u"): "bus",
}

# Icons shown in UI for each station type
STATION_ICON: dict[str, str] = {
    "repeater":  "🔁",
    "weather":   "🌤",
    "digi":      "📡",
    "igate":     "🛰",
    "gateway":   "🛰",
    "echolink":  "🔗",
    "mobile":    "🚗",
    "aircraft":  "✈",
    "balloon":   "🎈",
    "house":     "🏠",
    "ship":      "🚢",
    "bike":      "🚲",
    "car":       "🚗",
    "truck":     "🚚",
    "bus":       "🚌",
    "unknown":   "❓",
}

# Offline threshold in seconds per station type
OFFLINE_THRESHOLD: dict[str, int] = {
    "repeater": 24 * 3600,
    "digi":      2 * 3600,
    "igate":     2 * 3600,
    "gateway":   2 * 3600,
    "weather":   6 * 3600,
    "echolink":  6 * 3600,
    "mobile":       1800,
    "aircraft":      600,
    "balloon":      1800,
    "unknown":   4 * 3600,
}

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------
_RE_CALLSIGN = re.compile(r'^([A-Z0-9]{3,9}(?:-[A-Z0-9]{1,2})?)')

# Object packet: ;NAME     *DDHHMMzDDMM.mmN/DDDMM.mmEsymbol...
_RE_OBJECT = re.compile(r'^;([A-Z0-9 -]{9})\*')

# Position: uncompressed  !DDMM.mmN/DDDMM.mmE and compressed forms
_RE_POS_UNCOMP = re.compile(
    r'[!/@=`]'
    r'(\d{2})(\d{2}\.\d{2})([NS])'
    r'([\\/])'
    r'(\d{3})(\d{2}\.\d{2})([EW])'
    r'(.)'   # symbol
)

# Frequency patterns (MHz)
_RE_FREQ = re.compile(r'\b(1[2-4]\d\.\d{3,5}|4[23]\d\.\d{3,5})\b')

# CTCSS / DCS tone patterns
_RE_TONE = re.compile(
    r'(?i)(?:T(?:one)?|CTCSS)[:\s=]?\s*(\d+\.?\d*)\s*(?:Hz)?'
    r'|(?<!\d)(\d+\.?\d*)\s*Hz(?!\w)'
    r'|\bT(\d{3})\b'          # APRSdos Tnnn format
    r'|\bt(\d{3})\b'          # lowercase
    r'|\b(67\.0|71\.9|74\.4|77\.0|79\.7|82\.5|85\.4|88\.5|91\.5|94\.8|97\.4'
    r'|100\.0|103\.5|107\.2|110\.9|114\.8|118\.8|123\.0|127\.3|131\.8|136\.5'
    r'|141\.3|146\.2|151\.4|156\.7|162\.2|167\.9|173\.8|179\.9|186\.2|192\.8'
    r'|203\.5|210\.7|218\.1|225\.7|233\.6|241\.8|250\.3)\b'
)

# EchoLink node number or callsign reference
_RE_ECHOLINK = re.compile(r'(?i)echo\s*link[:\s]?\s*(\S+)|EL[:\s]?\s*(\S+)')

# URL
_RE_URL = re.compile(r'https?://[^\s<>"\']+')

# Offset / shift: +0.600 or -1.600 or +600 (kHz)
_RE_OFFSET = re.compile(r'([+-])(\d+\.?\d*)\s*(?:MHz|mhz|khz|KHz)?')

# Weather: temperature (Fahrenheit from APRS), humidity, pressure
_RE_WX_T = re.compile(r't(-?\d{3})')   # temperature in F (tXXX)
_RE_WX_H = re.compile(r'h(\d{2})')     # humidity (hXX, 00=100%)
_RE_WX_B = re.compile(r'b(\d{5})')     # barometric pressure (bXXXXX in tenths of mb)
_RE_WX_W = re.compile(r'g(\d{3})')     # wind gust (gXXX in mph)


def _latlon_to_locator(lat: float, lon: float) -> str:
    """Return 6-character Maidenhead grid locator for given decimal degrees."""
    lon += 180.0
    lat += 90.0
    a = int(lon / 20);  lon -= a * 20
    b = int(lat / 10);  lat -= b * 10
    c = int(lon / 2);   lon -= c * 2
    d = int(lat);       lat -= d
    e = int(lon * 12)
    f = int(lat * 24)
    return (
        chr(65 + a) + chr(65 + b) +
        str(c) + str(d) +
        chr(97 + e) + chr(97 + f)
    )


def _ddmm_to_decimal(deg_str: str, mm_str: str, hemisphere: str) -> float:
    deg = int(deg_str)
    minutes = float(mm_str)
    decimal = deg + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return round(decimal, 5)


def classify_symbol(table: str, symbol: str) -> str:
    """Return station type string for an APRS symbol table+code pair."""
    return _SYMBOL_TYPE.get((table, symbol), "unknown")


def parse_packet(raw_line: str) -> dict[str, Any]:
    """
    Parse a single raw APRS-IS line and return a dict of extracted fields.

    Fields always present:
      callsign, base_call, raw, ts

    Optional fields (only if found):
      lat, lon, symbol_table, symbol, station_type,
      freq_mhz, tone_hz, offset_mhz, echolink, url,
      wx_temp_c, wx_humidity, wx_pressure_mb, wx_wind_gust_ms,
      comment
    """
    result: dict[str, Any] = {
        "raw": raw_line,
        "ts":  int(time.time()),
    }

    # Extract source callsign (before the first '>')
    m = _RE_CALLSIGN.match(raw_line)
    if not m:
        result["callsign"] = ""
        result["base_call"] = ""
        return result

    callsign = m.group(1)
    result["callsign"] = callsign
    result["base_call"] = callsign.split("-")[0]

    # Everything after the last ':' is the information field
    colon_idx = raw_line.rfind(":")
    info = raw_line[colon_idx + 1:] if colon_idx != -1 else ""

    # Object packet: sender is the framing station; the named object is the
    # real station we care about.  Override callsign with the object name.
    om = _RE_OBJECT.match(info)
    if om:
        obj_name = om.group(1).rstrip()
        if obj_name:
            result["callsign"] = obj_name
            result["base_call"] = obj_name.split("-")[0]
            result["object_sender"] = callsign

    # --- Position ---
    pm = _RE_POS_UNCOMP.search(raw_line)
    if pm:
        lat = _ddmm_to_decimal(pm.group(1), pm.group(2), pm.group(3))
        lon = _ddmm_to_decimal(pm.group(5), pm.group(6), pm.group(7))
        tbl = pm.group(4)
        sym = pm.group(8)
        result["lat"] = lat
        result["lon"] = lon
        result["locator"] = _latlon_to_locator(lat, lon)
        result["symbol_table"] = tbl
        result["symbol"] = sym
        result["station_type"] = classify_symbol(tbl, sym)

    # Weather type override (_) even without uncompressed position
    if "_" in raw_line[:raw_line.find(":") + 20 if ":" in raw_line else 50]:
        result.setdefault("station_type", "weather")
        # Parse wx fields from info
        twx = _RE_WX_T.search(info)
        hwx = _RE_WX_H.search(info)
        bwx = _RE_WX_B.search(info)
        gwx = _RE_WX_W.search(info)
        if twx:
            f = int(twx.group(1))
            result["wx_temp_c"] = round((f - 32) * 5 / 9, 1)
        if hwx:
            h = int(hwx.group(1))
            result["wx_humidity"] = 100 if h == 0 else h
        if bwx:
            result["wx_pressure_mb"] = int(bwx.group(1)) / 10.0
        if gwx:
            result["wx_wind_gust_ms"] = round(int(gwx.group(1)) * 0.44704, 1)

    # --- Frequency ---
    fm = _RE_FREQ.search(info)
    if fm:
        result["freq_mhz"] = float(fm.group(1))

    # --- Tone ---
    for tm in _RE_TONE.finditer(info):
        for g in tm.groups():
            if g:
                try:
                    result["tone_hz"] = float(g)
                except ValueError:
                    pass
                break

    # --- Offset ---
    if "freq_mhz" in result:
        om = _RE_OFFSET.search(info)
        if om:
            sign = 1 if om.group(1) == "+" else -1
            val  = float(om.group(2))
            if val > 10:         # given in kHz
                val /= 1000.0
            result["offset_mhz"] = sign * val

    # --- EchoLink ---
    em = _RE_ECHOLINK.search(info)
    if em:
        result["echolink"] = (em.group(1) or em.group(2) or "").strip()

    # --- URL ---
    um = _RE_URL.search(info)
    if um:
        result["url"] = um.group(0)

    # --- Comment (trimmed info field) ---
    comment = info.strip()
    if comment:
        result["comment"] = comment[:120]

    return result
