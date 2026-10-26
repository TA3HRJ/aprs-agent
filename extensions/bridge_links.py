"""Callsigns linked to a messenger account, proven from the radio.

A bridge may carry a message between two people only if both are licensed
amateurs: KEGM Amatör Telsizcilik Sınav ve Belgelendirme Yönetmeliği
Md.23/1-c forbids communicating with persons who hold no licence (outside
emergencies and training), and 1-f letting others use one's call sign
(F-2026-10-26-01). A link is the bridge's evidence that the person behind a
Telegram chat holds a callsign:

  1. in Telegram they ask for a code for their callsign (/link TA1ABC)
  2. they send "LINK <code>" from that callsign's radio to the bridge alias
  3. the code matches and the sender's base callsign is the one asked for:
     the chat is linked to the callsign the radio sent from (with its SSID)

APRS has no authentication: a station on APRS-IS can claim any callsign, as
for every APRS service. The link is the best evidence this medium offers,
and the help says so.

Codes live in memory for ten minutes; links are kept in a JSON file beside
the config, written atomically. Unlinking deletes the entry.

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Optional

CODE_TTL_S = 600
_CALL_RE = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,4}(-[0-9A-Z]{1,2})?$")
_clock = time.time


def base_call(call: str) -> str:
    return (call or "").strip().upper().split("-")[0]


def looks_like_callsign(s: str) -> bool:
    s = (s or "").strip().upper()
    return bool(_CALL_RE.match(s)) and any(c.isdigit() for c in s) \
        and any(c.isalpha() for c in s.split("-")[0])


class BridgeLinks:
    """kind ("telegram", "email") -> base callsign -> {"call", "target", "since"}"""

    def __init__(self, path: "str | Path"):
        self._path = Path(path)
        self._links: dict = {}
        self._pending: dict = {}        # code -> (kind, base, target, expires)
        self._load()

    # ── persistence ──
    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._links = {k: v for k, v in data.items() if isinstance(v, dict)}
        except FileNotFoundError:
            self._links = {}
        except Exception:
            self._links = {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._links, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)

    # ── the two halves of linking ──
    def request(self, kind: str, call: str, target: str) -> Optional[str]:
        """A code for `target` (a chat id, an address) to claim `call`.
        None when `call` is not a callsign."""
        if not looks_like_callsign(call):
            return None
        now = _clock()
        self._pending = {c: v for c, v in self._pending.items() if v[3] > now}
        # one live code per target: asking again replaces it
        self._pending = {c: v for c, v in self._pending.items()
                         if not (v[0] == kind and v[2] == str(target))}
        code = f"{secrets.randbelow(900000) + 100000}"
        while code in self._pending:
            code = f"{secrets.randbelow(900000) + 100000}"
        self._pending[code] = (kind, base_call(call), str(target), now + CODE_TTL_S)
        return code

    def confirm(self, kind: str, sender_full: str, code: str) -> Optional[dict]:
        """`sender_full` sent `code` from the radio. The link it makes, or None
        when the code is unknown, expired, for another kind or another call."""
        code = (code or "").strip()
        p = self._pending.get(code)
        if not p or p[0] != kind or p[3] <= _clock():
            return None
        if base_call(sender_full) != p[1]:
            return None
        del self._pending[code]
        entry = {"call": sender_full.strip().upper(), "target": p[2], "since": int(_clock())}
        # a target belongs to one callsign, a callsign to one target
        k = self._links.setdefault(kind, {})
        for b in [b for b, v in k.items() if v.get("target") == p[2]]:
            del k[b]
        k[p[1]] = entry
        self._save()
        return entry

    # ── lookups ──
    def by_call(self, kind: str, call: str) -> Optional[dict]:
        return self._links.get(kind, {}).get(base_call(call))

    def by_target(self, kind: str, target: str) -> Optional[dict]:
        for v in self._links.get(kind, {}).values():
            if v.get("target") == str(target):
                return v
        return None

    def unlink_call(self, kind: str, call: str) -> Optional[dict]:
        v = self._links.get(kind, {}).pop(base_call(call), None)
        if v is not None:
            self._save()
        return v

    def unlink_target(self, kind: str, target: str) -> Optional[dict]:
        v = self.by_target(kind, target)
        if v is not None:
            return self.unlink_call(kind, v["call"])
        return None

    def count(self, kind: str) -> int:
        return len(self._links.get(kind, {}))
