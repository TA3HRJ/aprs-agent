"""
Station Database
================
In-memory database of all APRS stations heard in the current session.
Combines live APRS data with an optional static Turkey Repeaters JSON file.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from packet_parser import (
    OFFLINE_THRESHOLD,
    STATION_ICON,
    classify_symbol,
    parse_packet,
)


def save_meta(path: str, key: str, value: str) -> None:
    """Store a small persistent counter/setting (e.g. lifelong uptime)."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        con.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))
        con.commit()
    finally:
        con.close()


def load_meta(path: str, key: str, default: str = "") -> str:
    if not Path(path).exists():
        return default
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row and row[0] is not None else default
    except sqlite3.Error:
        return default
    finally:
        con.close()


def silence_history_range(path: str) -> Optional[dict[str, int]]:
    """Return {"min": ts, "max": ts} of stored snapshots, or None if empty."""
    if not Path(path).exists():
        return None
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT MIN(ts), MAX(ts) FROM silence_history").fetchone()
        if not row or row[0] is None:
            return None
        return {"min": int(row[0]), "max": int(row[1])}
    except sqlite3.Error:
        return None
    finally:
        con.close()


def load_silence_history(path: str, ts: int) -> dict[str, Any]:
    """Return the snapshot nearest to (at or before) the requested time.

    Falls back to the earliest snapshot when ts predates all data.
    """
    empty: dict[str, Any] = {"ts": None, "cells": []}
    if not Path(path).exists():
        return empty
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT MAX(ts) FROM silence_history WHERE ts <= ?", (ts,)
        ).fetchone()
        snap_ts = row[0] if row and row[0] is not None else None
        if snap_ts is None:
            row = con.execute(
                "SELECT MIN(ts) FROM silence_history").fetchone()
            snap_ts = row[0] if row and row[0] is not None else None
        if snap_ts is None:
            return empty
        try:
            rows = list(con.execute(
                "SELECT cell, baseline, silent, ratio, alert, cause,"
                " silent_calls, since, ai_note FROM silence_history"
                " WHERE ts = ?", (snap_ts,)))
        except sqlite3.OperationalError:
            # v2.7.15 schema without ai_note
            rows = [r + ("",) for r in con.execute(
                "SELECT cell, baseline, silent, ratio, alert, cause,"
                " silent_calls, since FROM silence_history WHERE ts = ?",
                (snap_ts,))]
        cells = []
        for (cell, baseline, silent, ratio, alert, cause,
             silent_calls, since, ai_note) in rows:
            try:
                calls = json.loads(silent_calls or "[]")
            except Exception:
                calls = []
            cells.append({
                "cell": cell, "baseline": baseline, "silent": silent,
                "ratio": ratio, "alert": bool(alert), "cause": cause,
                "silent_calls": calls, "since": since,
                "ai_note": ai_note or "",
                "bounds": _cell_bounds(cell),
            })
        return {"ts": int(snap_ts), "cells": cells}
    except sqlite3.Error:
        return empty
    finally:
        con.close()


def _cell_bounds(cell4: str) -> Optional[list[list[float]]]:
    """Bounds of a 4-char Maidenhead square: [[south, west], [north, east]].

    A square (e.g. KM69) spans 1° of latitude by 2° of longitude.
    """
    if len(cell4) < 4:
        return None
    try:
        lon = (ord(cell4[0]) - 65) * 20 - 180 + int(cell4[2]) * 2
        lat = (ord(cell4[1]) - 65) * 10 - 90 + int(cell4[3])
    except (ValueError, TypeError):
        return None
    return [[lat, lon], [lat + 1, lon + 2]]


class StationRecord:
    """All known data about a single station (callsign + SSID)."""

    __slots__ = (
        "callsign", "base_call",
        "station_type", "icon",
        "symbol", "symbol_table", "symbol_overlay",
        "city", "district", "location", "country", "ta_region",
        "lat", "lon", "locator",
        "freq_mhz", "tone_hz", "offset_mhz",
        "band", "mode", "db_status",
        "echolink", "url", "comment",
        "wx_temp_c", "wx_humidity", "wx_pressure_mb", "wx_wind_gust_ms",
        "db_record",       # raw dict from Turkey Repeaters DB (or None)
        "first_seen",
        "last_seen",
        "packet_count",
        "packets_today",
        "last_packet",
        "prev_online",     # last known online state (for transition detection)
        "ai_org",          # AI-extracted organization/club name
        "ai_description",  # AI-extracted station description
        "ai_analyzed",     # True once AI analysis has been attempted
        "ema_interval_s",  # smoothed beacon interval (silence detection baseline)
        "last_gate",       # igate that last gated this station to APRS-IS
        "hour_counts",     # packets heard per local hour-of-day (diurnal profile)
        "self_beacon",     # True = this agent's own Fixed Beacon (see below)
    )

    def __init__(self, callsign: str) -> None:
        self.callsign    = callsign
        self.base_call   = callsign.split("-")[0]
        self.station_type: str = "unknown"
        self.icon: str = STATION_ICON["unknown"]
        self.symbol: str = ""          # APRS symbol code (e.g. '#')
        self.symbol_table: str = ""    # '/', '\\' or overlay char (e.g. 'L')
        self.symbol_overlay: str = ""  # overlay char to draw on top, if any
        self.city: str = ""
        self.district: str = ""
        self.location: str = ""   # site name, e.g. "Rüzgarlı Tepe"
        self.country: str = ""
        self.ta_region: str = ""
        self.lat: Optional[float] = None
        self.lon: Optional[float] = None
        self.locator: str = ""
        self.freq_mhz: Optional[float] = None
        self.tone_hz: Optional[float] = None
        self.offset_mhz: Optional[float] = None
        self.band: str = ""
        self.mode: str = ""
        self.db_status: Optional[bool] = None   # True = active per DB
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
        self.prev_online: Optional[bool] = None  # sentinel: not yet checked
        self.ai_org: str = ""
        self.ai_description: str = ""
        self.ai_analyzed: bool = False
        self.ema_interval_s: Optional[float] = None
        self.last_gate: str = ""
        self.hour_counts: list[int] = [0] * 24
        # The agent's own Fixed Beacon is self-generated: it keeps beaconing no
        # matter what happens at its claimed location (the agent may even run on
        # a VPS in another country). It must show on the map but must NEVER act
        # as a silence sensor — otherwise it would be a phantom "still active"
        # vote that masks a genuine outage in its cell.
        self.self_beacon: bool = False

    def update_from_parsed(self, parsed: dict[str, Any]) -> None:
        """Merge fields extracted from a new APRS packet into this record."""
        ts = parsed.get("ts", int(time.time()))
        # Beacon cadence: smoothed interval between packets. Ignore gaps under
        # 30 s (digipeated duplicates of one beacon) and over 24 h (stale).
        dt = ts - self.last_seen
        if self.packet_count > 0 and 30 <= dt <= 86400:
            if self.ema_interval_s is None:
                self.ema_interval_s = float(dt)
            else:
                self.ema_interval_s = 0.3 * dt + 0.7 * self.ema_interval_s
        self.hour_counts[time.localtime(ts).tm_hour] += 1
        if parsed.get("gate"):
            self.last_gate = parsed["gate"]
        self.last_seen    = ts
        self.packet_count += 1
        self.last_packet  = parsed.get("raw", "")[:200]

        if "station_type" in parsed and parsed["station_type"] != "unknown":
            self.station_type = parsed["station_type"]
            self.icon = STATION_ICON.get(self.station_type, "❓")

        # APRS symbol for sprite rendering (only overwrite when a packet has one)
        if parsed.get("symbol"):
            self.symbol = parsed["symbol"]
            self.symbol_table = parsed.get("symbol_table", "/")
            self.symbol_overlay = parsed.get("symbol_overlay", "")

        # Prefer DB coordinates; only overwrite if we don't have them yet.
        # locator is initialised to "" (not None) — treat both as unset.
        for field in ("lat", "lon", "locator"):
            if field in parsed and getattr(self, field) in (None, ""):
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
        # Location fields — DB is authoritative
        self.city     = db.get("city") or self.city
        self.district = db.get("district") or self.district
        self.location = db.get("location") or self.location
        self.ta_region = db.get("ta_region") or self.ta_region
        self.locator  = db.get("locator") or self.locator
        # Coordinates — DB is authoritative
        if db.get("lat") is not None:
            self.lat = db["lat"]
        if db.get("lon") is not None:
            self.lon = db["lon"]
        # Frequency — DB is authoritative
        if db.get("frequency") is not None:
            self.freq_mhz = float(db["frequency"])
        if db.get("offset") is not None:
            self.offset_mhz = float(db["offset"])
        if db.get("tone") is not None:
            try:
                self.tone_hz = float(str(db["tone"]).replace("D", ""))
            except ValueError:
                pass
        self.band = db.get("band") or self.band
        self.mode = db.get("mode") or self.mode
        self.db_status = db.get("status")   # True/False/None
        # All records in Turkey Repeaters DB are repeaters
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
            "symbol":        self.symbol,
            "symbol_table":  self.symbol_table,
            "symbol_overlay": self.symbol_overlay,
            "city":        self.city,
            "district":    self.district,
            "location":    self.location,
            "country":     self.country,
            "ta_region":   self.ta_region,
            "lat":         self.lat,
            "lon":         self.lon,
            "locator":     self.locator,
            "freq_mhz":    self.freq_mhz,
            "tone_hz":     self.tone_hz,
            "offset_mhz":  self.offset_mhz,
            "band":        self.band,
            "mode":        self.mode,
            "db_status":   self.db_status,
            "echolink":    self.echolink,
            "url":         self.url,
            "comment":     self.comment,
            "wx_temp_c":         self.wx_temp_c,
            "wx_humidity":       self.wx_humidity,
            "wx_pressure_mb":    self.wx_pressure_mb,
            "wx_wind_gust_ms":   self.wx_wind_gust_ms,
            "ai_org":         self.ai_org,
            "ai_description": self.ai_description,
            "ai_analyzed":    self.ai_analyzed,
            "ema_interval_s": self.ema_interval_s,
            "last_gate":      self.last_gate,
            "self_beacon":    self.self_beacon,
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
        # Maidenhead fields (first two chars, e.g. "KM") that silence detection
        # is scoped to. A prefix station filter such as p/TA also matches
        # callsigns abroad, and clusters of those produced alerts for regions
        # the operator does not care about. Empty = worldwide.
        self.silence_grids: list[str] = []

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
            raw_call = rec.get("callsign")
            if not raw_call:
                continue
            call = str(raw_call).strip().upper()
            base = call.split("-")[0]
            self._repeater_index.setdefault(base, []).append(rec)
        # Enrich stations already in memory (e.g. loaded from SQLite before
        # the repeater DB was available).
        for st in self._stations.values():
            if st.db_record is None:
                entries = self._repeater_index.get(st.base_call)
                if entries:
                    st.update_from_db(entries[0])
        return len(records)

    # ------------------------------------------------------------------
    def ingest(self, raw_line: str, own: bool = False) -> Optional[StationRecord]:
        """Parse a raw APRS-IS line and update the station record.

        own=True marks the record as this agent's own Fixed Beacon, so it
        appears on the map but is excluded from silence detection.
        """
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
        if own:
            rec.self_beacon = True
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

    def check_transitions(
        self,
        watch_filter: "set[str]" = None,
    ) -> "list[tuple[StationRecord, str]]":
        """
        Detect online↔offline transitions for DB-matched repeaters.

        Returns list of (record, event) where event is "offline" or "online".
        On the very first call, prev_online is initialised with no alerts.
        Only stations with a DB record are checked.
        watch_filter: if non-empty, only check those base callsigns.
        """
        results = []
        for rec in self._stations.values():
            if rec.db_record is None:
                continue
            if watch_filter and rec.base_call not in watch_filter:
                continue
            current = rec.online  # True / False / None
            if current is None:
                continue          # DB-only, never heard live — skip
            if rec.prev_online is None:
                # First evaluation: just store, no alert
                rec.prev_online = current
                continue
            if current != rec.prev_online:
                event = "online" if current else "offline"
                results.append((rec, event))
                rec.prev_online = current
        return results

    def get_unanalyzed(self, max_n: int = 20) -> "list[StationRecord]":
        """
        Return up to max_n stations that have a comment but no AI analysis yet.
        Prioritises DB-matched stations, then others.
        """
        candidates = [
            r for r in self._stations.values()
            if not r.ai_analyzed and r.comment.strip()
        ]
        # DB-matched first
        candidates.sort(key=lambda r: (not r.db_record, -r.packet_count))
        return candidates[:max_n]

    def reset(self) -> None:
        self._stations.clear()

    # ------------------------------------------------------------------
    # SQLite persistence — survives agent/GUI restarts so the beacon-cadence
    # baseline (silence detection) builds up over days, not sessions.

    _SQL_COLS = (
        "callsign", "first_seen", "last_seen", "packet_count",
        "lat", "lon", "locator", "symbol", "symbol_table", "symbol_overlay",
        "station_type", "icon", "city", "district", "freq_mhz", "tone_hz",
        "comment", "ai_org", "ai_description", "ai_analyzed",
        "ema_interval_s", "last_gate", "hour_counts",
    )

    def save_sqlite(self, path: str) -> int:
        """Persist all station records. Returns number of rows written."""
        con = sqlite3.connect(path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS stations ("
                "callsign TEXT PRIMARY KEY, first_seen REAL, last_seen REAL,"
                "packet_count INTEGER, lat REAL, lon REAL, locator TEXT,"
                "symbol TEXT, symbol_table TEXT, symbol_overlay TEXT,"
                "station_type TEXT, icon TEXT, city TEXT, district TEXT,"
                "freq_mhz REAL, tone_hz REAL, comment TEXT,"
                "ai_org TEXT, ai_description TEXT, ai_analyzed INTEGER,"
                "ema_interval_s REAL, last_gate TEXT, hour_counts TEXT)"
            )
            rows = [
                (r.callsign, r.first_seen, r.last_seen, r.packet_count,
                 r.lat, r.lon, r.locator, r.symbol, r.symbol_table,
                 r.symbol_overlay, r.station_type, r.icon, r.city, r.district,
                 r.freq_mhz, r.tone_hz, r.comment, r.ai_org, r.ai_description,
                 int(r.ai_analyzed), r.ema_interval_s, r.last_gate,
                 json.dumps(r.hour_counts))
                for r in self._stations.values()
            ]
            con.executemany(
                "INSERT OR REPLACE INTO stations VALUES ("
                + ",".join("?" * len(self._SQL_COLS)) + ")", rows)
            con.commit()
            return len(rows)
        finally:
            con.close()

    def load_sqlite(self, path: str) -> int:
        """Load persisted records (skips callsigns already in memory)."""
        if not Path(path).exists():
            return 0
        con = sqlite3.connect(path)
        try:
            cur = con.execute(
                "SELECT " + ",".join(self._SQL_COLS) + " FROM stations")
            n = 0
            for row in cur:
                d = dict(zip(self._SQL_COLS, row))
                cs = d["callsign"]
                if not cs or cs in self._stations:
                    continue
                r = StationRecord(cs)
                r.first_seen   = d["first_seen"] or time.time()
                r.last_seen    = d["last_seen"] or r.first_seen
                r.packet_count = d["packet_count"] or 0
                r.lat, r.lon   = d["lat"], d["lon"]
                r.locator      = d["locator"] or ""
                r.symbol       = d["symbol"] or ""
                r.symbol_table = d["symbol_table"] or ""
                r.symbol_overlay = d["symbol_overlay"] or ""
                r.station_type = d["station_type"] or "unknown"
                r.icon         = d["icon"] or STATION_ICON["unknown"]
                r.city         = d["city"] or ""
                r.district     = d["district"] or ""
                r.freq_mhz     = d["freq_mhz"]
                r.tone_hz      = d["tone_hz"]
                r.comment      = d["comment"] or ""
                r.ai_org       = d["ai_org"] or ""
                r.ai_description = d["ai_description"] or ""
                r.ai_analyzed  = bool(d["ai_analyzed"])
                r.ema_interval_s = d["ema_interval_s"]
                r.last_gate    = d["last_gate"] or ""
                try:
                    hc = json.loads(d["hour_counts"] or "[]")
                    if isinstance(hc, list) and len(hc) == 24:
                        r.hour_counts = hc
                except Exception:
                    pass
                self._stations[cs] = r
                n += 1
            return n
        except sqlite3.Error:
            return 0
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Silence history — timeline scrubbing support. Snapshots of the computed
    # cell state are appended periodically so past events can be replayed.

    _HISTORY_RETENTION_S = 14 * 24 * 3600

    def record_silence_history(
        self, path: str, ai_notes: Optional[dict[str, str]] = None,
        episode_starts: Optional[dict[str, float]] = None,
    ) -> int:
        """Append the current silence-cell state as a timestamped snapshot.

        Only cells with at least one silent station are stored; AI assessments
        (cell → note) are stored alongside so the timeline can replay them.
        Rows older than the retention window are pruned. Returns rows written.
        """
        cells = [c for c in self.silence_cells() if c["silent"] >= 1]
        ai_notes = ai_notes or {}
        episode_starts = episode_starts or {}
        for c in cells:
            # Anchor "since" to the current alert episode's start, not the
            # longest-silent individual station — a cell that recovered and
            # re-alerted should show the new episode, not a stale one.
            start = episode_starts.get(c["cell"])
            if c["alert"] and start:
                c["since"] = int(start)
        now = int(time.time())
        con = sqlite3.connect(path)
        try:
            con.execute(
                "CREATE TABLE IF NOT EXISTS silence_history ("
                "ts INTEGER, cell TEXT, baseline INTEGER, silent INTEGER,"
                "ratio REAL, alert INTEGER, cause TEXT, silent_calls TEXT,"
                "since INTEGER, ai_note TEXT, PRIMARY KEY (ts, cell))"
            )
            # Migrate v2.7.15 tables that predate the ai_note column
            try:
                con.execute(
                    "ALTER TABLE silence_history ADD COLUMN ai_note TEXT")
            except sqlite3.OperationalError:
                pass
            con.executemany(
                "INSERT OR REPLACE INTO silence_history VALUES (?,?,?,?,?,?,?,?,?,?)",
                [(now, c["cell"], c["baseline"], c["silent"], c["ratio"],
                  int(c["alert"]), c["cause"], json.dumps(c["silent_calls"]),
                  c["since"], ai_notes.get(c["cell"], "")) for c in cells])
            con.execute("DELETE FROM silence_history WHERE ts < ?",
                        (now - self._HISTORY_RETENTION_S,))
            con.commit()
            return len(cells)
        finally:
            con.close()

    # ------------------------------------------------------------------
    # Silence clustering — Phase 3 of the silence-map roadmap.

    def silence_cells(
        self,
        min_history: int = 5,
        baseline_window_s: int = 24 * 3600,
        min_silent: int = 3,
        min_ratio: float = 0.5,
    ) -> list[dict[str, Any]]:
        """Group recently-silent stations into Maidenhead squares (4-char).

        A station is "recently silent" when the gap since its last packet
        exceeds 3× its own smoothed beacon interval (min 15 minutes) while it
        was active inside the baseline window. Cells where enough of the
        normally-active stations fell silent become alert candidates; if all
        silent stations were gated by one igate that is itself silent, the
        cause is reported as an igate failure instead of a regional outage.
        """
        now = time.time()

        def gate_active(gate: str) -> Optional[bool]:
            g = self._stations.get(gate)
            if g is None or g.packet_count == 0:
                return None                      # gate not tracked
            return (now - g.last_seen) < 1800    # heard in last 30 min

        cells: dict[str, dict[str, Any]] = {}
        for r in self._stations.values():
            if r.self_beacon:
                continue    # self-generated — never a silence sensor
            if r.packet_count < min_history or not r.locator:
                continue
            if r.lat is None or r.lon is None:
                continue
            if (now - r.last_seen) > baseline_window_s:
                continue                          # long dead — not baseline
            if r.ema_interval_s is None:
                continue                          # no cadence baseline yet
            cell = r.locator[:4].upper()
            if self.silence_grids and cell[:2] not in self.silence_grids:
                continue        # outside the region this station monitors
            c = cells.setdefault(cell, {
                "cell": cell, "baseline": 0, "silent": 0,
                "silent_calls": [], "gate_of": {}, "first_silent": None,
            })
            c["baseline"] += 1
            threshold = max(3.0 * r.ema_interval_s, 900.0)
            gap = now - r.last_seen
            if gap > threshold:
                c["silent"] += 1
                c["silent_calls"].append(r.callsign)
                if r.last_gate:
                    c["gate_of"][r.callsign] = r.last_gate
                # When this station crossed its silence threshold
                went = r.last_seen + threshold
                if c["first_silent"] is None or went < c["first_silent"]:
                    c["first_silent"] = went

        out = []
        for c in cells.values():
            ratio = c["silent"] / c["baseline"] if c["baseline"] else 0.0
            alert = c["silent"] >= min_silent and ratio >= min_ratio
            cause = "outage"
            if alert:
                # Gates used by the silent stations — excluding silent
                # stations that are themselves someone's gate (an igate that
                # died takes its own beacon down with it).
                raw_gates = set(c["gate_of"].values())
                eff_gates = {g for call, g in c["gate_of"].items()
                             if call not in raw_gates}
                if len(eff_gates) == 1:
                    only_gate = next(iter(eff_gates))
                    if gate_active(only_gate) is False:
                        cause = "igate"
            b = _cell_bounds(c["cell"])
            out.append({
                "cell": c["cell"],
                "baseline": c["baseline"],
                "silent": c["silent"],
                "ratio": round(ratio, 2),
                "alert": alert,
                "cause": cause if alert else "",
                "silent_calls": sorted(c["silent_calls"])[:20],
                "since": int(c["first_silent"]) if c["first_silent"] else None,
                "bounds": b,
            })
        out.sort(key=lambda x: (-int(x["alert"]), -x["ratio"]))
        return out
