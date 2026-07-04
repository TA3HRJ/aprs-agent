"""
Station Database
================
In-memory database of all APRS stations heard in the current session.
Combines live APRS data with an optional static Turkey Repeaters JSON file.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from packet_parser import (
    OFFLINE_THRESHOLD,
    STATION_ICON,
    classify_symbol,
    parse_packet,
)


class StationRecord:
    """All known data about a single station (callsign + SSID)."""

    __slots__ = (
        "callsign", "base_call",
        "station_type", "icon",
        "city", "district", "country",
        "lat", "lon",
        "freq_mhz", "tone_hz", "offset_mhz",
        "echolink", "url", "comment",
        "wx_temp_c", "wx_humidity", "wx_pressure_mb", "wx_wind_gust_ms",
        "db_record",       # raw dict from Turkey Repeaters DB (or None)
        "first_seen",
        "last_seen",
        "packet_count",
        "packets_today",
        "last_packet",
    )

    def __init__(self, callsign: str) -> None:
        self.callsign    = callsign
        self.base_call   = callsign.split("-")[0]
        self.station_type: str = "unknown"
        self.icon: str = STATION_ICON["unknown"]
        self.city: str = ""
        self.district: str = ""
        self.country: str = ""
        self.lat: Optional[float] = None
        self.lon: Optional[float] = None
        self.freq_mhz: Optional[float] = None
        self.tone_hz: Optional[float] = None
        self.offset_mhz: Optional[float] = None
        self.echolink: str = ""
        self.url: str = ""
        self.comment: str = ""
        self.wx_temp_c: Optional[float] = None
        self.wx_humidity: Optional[int] = None
        self.wx_pressure_mb: Optional[float] = None
        self.wx_wind_gust_ms: Optional[float] = None
        self.db_record: Optional[dict] = None
        now = time.time()
        self.first_seen   = now
        self.last_seen    = now
        self.packet_count = 0
        self.packets_today = 0
        self.last_packet: str = ""

    def update_from_parsed(self, parsed: dict[str, Any]) -> None:
        """Merge fields extracted from a new APRS packet into this record."""
        self.last_seen    = parsed.get("ts", int(time.time()))
        self.packet_count += 1
        self.last_packet  = parsed.get("raw", "")[:200]

        if "station_type" in parsed and parsed["station_type"] != "unknown":
            self.station_type = parsed["station_type"]
            self.icon = STATION_ICON.get(self.station_type, "❓")

        # Prefer DB coordinates; only overwrite if we don't have them yet
        for field in ("lat", "lon"):
            if field in parsed and getattr(self, field) is None:
                setattr(self, field, parsed[field])

        # Prefer DB freq/tone; fill in from APRS if missing
        for field in ("freq_mhz", "tone_hz", "offset_mhz"):
            if field in parsed and getattr(self, field) is None:
                setattr(self, field, parsed[field])

        for field in ("echolink", "url", "comment"):
            if parsed.get(field) and not getattr(self, field):
                setattr(self, field, parsed[field])

        for wx in ("wx_temp_c", "wx_humidity", "wx_pressure_mb", "wx_wind_gust_ms"):
            if wx in parsed:
                setattr(self, wx, parsed[wx])

    def update_from_db(self, db: dict[str, Any]) -> None:
        """Overlay structured data from Turkey Repeaters DB."""
        self.db_record = db
        if not self.city:
            self.city = db.get("city", "")
        if not self.district:
            self.district = db.get("district", "")
        if not self.country:
            self.country = db.get("country", "")
        # DB coordinates are authoritative
        if db.get("lat") is not None:
            self.lat = db["lat"]
        if db.get("lon") is not None:
            self.lon = db["lon"]
        # DB freq/tone are authoritative
        if db.get("frequency") is not None:
            self.freq_mhz = float(db["frequency"])
        if db.get("tone") is not None:
            try:
                self.tone_hz = float(str(db["tone"]).replace("D", ""))
            except ValueError:
                pass
        # Infer station type from DB mode/band if still unknown
        if self.station_type == "unknown":
            mode = str(db.get("mode", "")).upper()
            if mode in ("FM", "DMR", "D-STAR", "C4FM", "TETRA", "P25"):
                self.station_type = "repeater"
                self.icon = STATION_ICON["repeater"]

    @property
    def online(self) -> Optional[bool]:
        """None if never seen live; True/False based on last_seen age."""
        if self.packet_count == 0:
            return None   # DB-only record
        threshold = OFFLINE_THRESHOLD.get(self.station_type, 4 * 3600)
        return (time.time() - self.last_seen) < threshold

    @property
    def last_seen_ago_s(self) -> Optional[int]:
        if self.packet_count == 0:
            return None
        return int(time.time() - self.last_seen)

    def to_dict(self) -> dict[str, Any]:
        ago = self.last_seen_ago_s
        online = self.online
        return {
            "callsign":    self.callsign,
            "base_call":   self.base_call,
            "type":        self.station_type,
            "icon":        self.icon,
            "city":        self.city,
            "district":    self.district,
            "country":     self.country,
            "lat":         self.lat,
            "lon":         self.lon,
            "freq_mhz":    self.freq_mhz,
            "tone_hz":     self.tone_hz,
            "offset_mhz":  self.offset_mhz,
            "echolink":    self.echolink,
            "url":         self.url,
            "comment":     self.comment,
            "wx_temp_c":         self.wx_temp_c,
            "wx_humidity":       self.wx_humidity,
            "wx_pressure_mb":    self.wx_pressure_mb,
            "wx_wind_gust_ms":   self.wx_wind_gust_ms,
            "has_db":      self.db_record is not None,
            "online":      online,
            "first_seen":  int(self.first_seen),
            "last_seen":   int(self.last_seen),
            "last_seen_ago_s": ago,
            "packet_count": self.packet_count,
            "last_packet": self.last_packet,
        }


class StationDB:
    """
    In-memory station registry.

    Usage:
        db = StationDB()
        db.load_repeater_db("path/to/repeaters.json")  # optional
        db.ingest(raw_aprs_line)
        stations = db.get_all()                        # list of dicts
    """

    def __init__(self) -> None:
        self._stations: dict[str, StationRecord] = {}
        # base_call → list of DB records for fast lookup
        self._repeater_index: dict[str, list[dict]] = {}

    # ------------------------------------------------------------------
    def load_repeater_db(self, path: str) -> int:
        """Load Turkey Repeaters JSON. Returns number of records loaded."""
        p = Path(path)
        if not p.exists():
            return 0
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return 0
        records = data if isinstance(data, list) else data.get("repeaters", [])
        for rec in records:
            call = rec.get("callsign", "").strip().upper()
            if not call:
                continue
            base = call.split("-")[0]
            self._repeater_index.setdefault(base, []).append(rec)
        return len(records)

    # ------------------------------------------------------------------
    def ingest(self, raw_line: str) -> Optional[StationRecord]:
        """Parse a raw APRS-IS line and update the station record."""
        parsed = parse_packet(raw_line)
        callsign = parsed.get("callsign", "")
        if not callsign:
            return None

        if callsign not in self._stations:
            rec = StationRecord(callsign)
            self._stations[callsign] = rec
            # Try to match against repeater DB
            base = parsed.get("base_call", callsign.split("-")[0])
            db_entries = self._repeater_index.get(base, [])
            if db_entries:
                rec.update_from_db(db_entries[0])
        else:
            rec = self._stations[callsign]

        rec.update_from_parsed(parsed)
        return rec

    # ------------------------------------------------------------------
    def get_all(self) -> list[dict[str, Any]]:
        """Return all stations as a list of dicts, sorted by last_seen desc."""
        rows = [r.to_dict() for r in self._stations.values()]
        rows.sort(key=lambda r: r["last_seen"] or 0, reverse=True)
        return rows

    def get_one(self, callsign: str) -> Optional[dict[str, Any]]:
        rec = self._stations.get(callsign)
        return rec.to_dict() if rec else None

    def count(self) -> int:
        return len(self._stations)

    def reset(self) -> None:
        self._stations.clear()
