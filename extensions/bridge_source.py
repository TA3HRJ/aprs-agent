"""Which callsign a bridged message goes on air from.

A message that arrives from Telegram, WhatsApp or e-mail and is sent to an
APRS station has to name its originator: KEGM Amatör Telsizcilik Sınav ve
Belgelendirme Yönetmeliği Md.23/1-f forbids letting others use one's call
sign, and 1-g communicating without identifying oneself (F-2026-10-26-01).
Two ways to do that, chosen per bridge with `aprs_source`:

  "own"      the packet's source is the originator's own callsign; the text
             goes as written. A reply from the radio comes back to that call.
  "gateway"  the packet's source is the bridge's `gateway_callsign` (e.g.
             TGSEND) and the text opens with the originator: "TA3HX-6: hi".
             A reply goes to the gateway, which knows where to pass it on.

A bridge that knows no callsign for the originator (e-mail, until callsigns
are linked to addresses) can only use "gateway".

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations

from typing import Optional

SOURCE_MODES = ("own", "gateway")
DEFAULT_MODE = "own"
_MAX_TEXT = 64          # what the bridges already cut a message to


def source_mode(cfg: dict) -> str:
    """The bridge's configured mode; anything unknown reads as the default."""
    mode = str(cfg.get("aprs_source", DEFAULT_MODE) or DEFAULT_MODE).strip().lower()
    return mode if mode in SOURCE_MODES else DEFAULT_MODE


def gateway_callsign(cfg: dict) -> str:
    """`gateway_callsign`, else the bridge's first trigger alias, else
    `from_callsign` - so an existing config keeps working unchanged."""
    for c in ([cfg.get("gateway_callsign", "")]
              + list(cfg.get("allowed_recepients", []) or [])
              + [cfg.get("from_callsign", "")]):
        c = str(c or "").strip().upper()
        if c and c != "N0CALL":
            return c
    return ""


def aprs_origin(cfg: dict, originator: Optional[str], text: str,
                limit: Optional[int] = _MAX_TEXT) -> "tuple[str, str, str]":
    """(source callsign, message text, mode used) for one bridged message.

    `originator` is the sender's callsign when the bridge knows it, else a
    label (an e-mail address) or None. "own" without a callsign falls back
    to "gateway", and the third item says so. `limit=None` leaves the text
    whole, for a bridge that splits it into parts itself."""
    mode = source_mode(cfg)
    orig = (originator or "").strip()
    is_call = bool(orig) and "@" not in orig and " " not in orig
    if mode == "own" and is_call:
        return orig.upper(), _cut(text, limit), "own"
    prefix = f"{orig.upper() if is_call else orig}: " if orig else ""
    return gateway_callsign(cfg), _cut(prefix + text, limit), "gateway"


def _cut(text: str, limit: Optional[int]) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[:limit - 3] + "..."
