"""
Station Database
================
In-memory database of all APRS stations heard in the current session.
Combines live APRS data with an optional static Turkey Repeaters JSON file.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations

import json
import math
import sqlite3
import time
from collections import deque
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


def cell_silence_history(path: str, cell: str,
                         limit: int = 12) -> dict[str, Any]:
    """Past alerting snapshots for one cell, summarised.

    Without this, an exported evidence bundle is a single frame: it can say
    "one of seven stations is quiet" but not whether that station is the last
    one still down after the other six came back. That is the first question
    an operator asks, and a reader with no way to answer it will guess — so
    the answer is served here instead.

    Note the history is deliberately sparse: only cells with at least one
    silent station are snapshotted, so a gap means "nothing was silent", not
    "not recorded".
    """
    out: dict[str, Any] = {"snapshots": 0, "alerting_snapshots": 0,
                           "peak": None, "recent": [], "per_station": {}}
    if not Path(path).exists():
        return out
    con = sqlite3.connect(path)
    try:
        row = con.execute(
            "SELECT COUNT(*), COALESCE(SUM(alert),0), MIN(ts), MAX(ts) "
            "FROM silence_history WHERE cell = ?", (cell,)).fetchone()
        if not row or not row[0]:
            return out
        out["snapshots"] = int(row[0])
        out["alerting_snapshots"] = int(row[1])
        out["first_ts"], out["last_ts"] = int(row[2]), int(row[3])

        peak = con.execute(
            "SELECT ts, silent, baseline, ratio FROM silence_history "
            "WHERE cell = ? ORDER BY silent DESC, ts DESC LIMIT 1",
            (cell,)).fetchone()
        if peak:
            out["peak"] = {"ts": int(peak[0]), "silent": peak[1],
                           "baseline": peak[2], "ratio": peak[3]}

        for ts_, silent, baseline, ratio, alert, calls in con.execute(
                "SELECT ts, silent, baseline, ratio, alert, silent_calls "
                "FROM silence_history WHERE cell = ? "
                "ORDER BY ts DESC LIMIT ?", (cell, limit)):
            try:
                parsed = json.loads(calls or "[]")
            except Exception:
                parsed = []
            out["recent"].append({
                "ts": int(ts_), "silent": silent, "baseline": baseline,
                "ratio": ratio, "alert": bool(alert), "silent_calls": parsed,
            })

        # How often each station was named silent across the whole history —
        # this separates "never came back" from "goes quiet regularly".
        counts: dict[str, int] = {}
        for (calls,) in con.execute(
                "SELECT silent_calls FROM silence_history WHERE cell = ?",
                (cell,)):
            try:
                for c in json.loads(calls or "[]"):
                    counts[c] = counts.get(c, 0) + 1
            except Exception:
                continue
        out["per_station"] = counts
        return out
    except sqlite3.Error:
        return out
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


def record_prop_event(path: str, event: dict[str, Any]) -> None:
    """Append one propagation-opening event (event-driven, not periodic:
    openings are rare, a row per event keeps the table tiny). Prunes rows
    older than the same retention window the silence history uses."""
    con = sqlite3.connect(path)
    try:
        con.execute(
            "CREATE TABLE IF NOT EXISTS prop_history ("
            "ts INTEGER, region TEXT, note TEXT, links TEXT)")
        con.execute(
            "INSERT INTO prop_history VALUES (?,?,?,?)",
            (int(event["ts"]), event["region"], event.get("note", ""),
             json.dumps(event["links"])))
        con.execute("DELETE FROM prop_history WHERE ts < ?",
                    (int(time.time()) - StationDB._HISTORY_RETENTION_S,))
        con.commit()
    finally:
        con.close()


def find_prop_event(path: str, call: str, gate: str, ts: int,
                    window_s: int = 3600) -> Optional[dict[str, Any]]:
    """The stored opening event that contains this link, if any.

    A single link is the smallest thing on the map, but the finding is the
    opening: two or more distinct senders in one field. Handing over the link
    without the event it belongs to invites the reader to treat one packet as
    the whole story.
    """
    if not Path(path).exists():
        return None
    con = sqlite3.connect(path)
    try:
        for ev_ts, region, note, raw in con.execute(
                "SELECT ts, region, note, links FROM prop_history "
                "WHERE ts BETWEEN ? AND ?", (ts - window_s, ts + window_s)):
            try:
                links = json.loads(raw or "[]")
            except Exception:
                continue
            if not any(l.get("call") == call and l.get("gate") == gate
                       for l in links):
                continue
            senders = sorted({str(l.get("call", "")).split("-")[0]
                              for l in links})
            return {
                "ts": int(ev_ts), "region": region, "note": note or "",
                "links": links, "link_count": len(links),
                "distinct_senders": senders,
                "max_km": max((l.get("km", 0) for l in links), default=0),
            }
        return None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def load_prop_history(path: str, ts: int,
                      window_s: int = 1800) -> list[dict[str, Any]]:
    """Links of every propagation event within ±window_s of ts (for the map
    timeline: scrubbing near an opening replays its links)."""
    if not Path(path).exists():
        return []
    con = sqlite3.connect(path)
    try:
        links: list[dict[str, Any]] = []
        for (note, raw) in con.execute(
                "SELECT note, links FROM prop_history"
                " WHERE ts BETWEEN ? AND ?", (ts - window_s, ts + window_s)):
            try:
                event_links = json.loads(raw or "[]")
                if note:
                    # The note is stored once per event (region+time), not
                    # per link -- copy it onto each link dict so the map
                    # popup can show it same as the live view does.
                    for l in event_links:
                        l["note"] = note
                links.extend(event_links)
            except Exception:
                pass
        return links
    except sqlite3.Error:
        return []
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
        "is_object",       # True = APRS Object packet (event advisory, not infra)
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
        # Object packets (;NAME*…) describe events, not infrastructure:
        # fire/incident advisories from emergency services, hamfest markers…
        # They expire by design when the event closes, so they must never be
        # silence sensors (a cell of expired advisories is not an outage).
        # Persisted to SQLite — the flag must survive the hourly-update
        # restarts, or every deploy would re-arm this false-positive class.
        self.is_object: bool = False

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
        if parsed.get("object_sender"):
            self.is_object = True
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
            "is_object":      self.is_object,
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

    # ── RF propagation constants (phase 1 defaults; calibrated against the
    #    live worldwide feed — see the v2.10.0 calibration notes) ──
    # A link shorter than this is never anomalous, whatever the baseline:
    # normal VHF/UHF terrestrial range plus a wide margin.
    PROP_MIN_KM = 300.0
    # Links longer than this are treated as data errors (GPS garbage,
    # misconfigured coordinates) — even extreme sporadic-E stays below it.
    PROP_MAX_KM = 5000.0
    # Senders above this altitude (balloons) see 500+ km by line of sight —
    # geometry, not propagation.
    PROP_MAX_ALT_M = 3000
    # Gate baselines firm up after this many measured links.
    PROP_MIN_SAMPLES = 20
    # EMA smoothing for per-gate distance statistics.
    _PROP_ALPHA = 0.05

    # Station types that move under their own power (or a person's) — a
    # weak silence sensor. It falling quiet usually means it drove/walked
    # out of coverage, not that its area lost power; a real regional outage
    # is still caught by the area's stationary repeaters/igates/houses.
    _MOBILE_TYPES = frozenset({
        "mobile", "car", "jeep", "truck", "bus", "van", "motorcycle",
        "ambulance", "police", "railway", "aircraft", "helo", "balloon",
        "glider", "rocket", "ship", "yacht", "canoe", "bike",
        "walker", "girl", "phone", "mic-e",
    })
    # Histogram bucket upper bounds (km) for threshold calibration.
    _PROP_BUCKETS = (25, 50, 100, 150, 200, 300, 500, 800, 1200, 2000, 5000)

    def __init__(self) -> None:
        self._stations: dict[str, StationRecord] = {}
        # base_call → list of DB records for fast lookup
        self._repeater_index: dict[str, list[dict]] = {}
        # Maidenhead fields (first two chars, e.g. "KM") that silence detection
        # is scoped to. A prefix station filter such as p/TA also matches
        # callsigns abroad, and clusters of those produced alerts for regions
        # the operator does not care about. Empty = worldwide.
        self.silence_grids: list[str] = []
        # What the current APRS-IS feed can hear (allowed_callsigns patterns;
        # empty = full feed). Stations outside this scope are invisible to the
        # feed, so their "silence" says nothing — after narrowing the filter,
        # the registry's foreign stations must not raise outage alerts.
        self.feed_filter: list[str] = []
        # Wall-clock of the last ingested packet: if the agent itself has
        # heard nothing for a while (APRS-IS down), it is deaf and cannot
        # judge anyone's silence.
        self.last_ingest_ts: float = 0.0
        # Shared get_slim() cache: the sort + per-station dict build is the
        # expensive part (O(n log n) over the whole registry) and identical
        # for every viewer regardless of their bbox/limit — with many
        # concurrent visitors polling every 5s, redoing it per request was
        # the actual cost, not the JSON encoding. Recomputed at most once
        # per _SLIM_CACHE_TTL; per-request bbox/limit filtering stays cheap
        # list-comprehension work on top of the shared result.
        self._slim_cache: Optional[list[dict[str, Any]]] = None
        self._slim_cache_ts: float = 0.0
        # How long the last _slim_all() rebuild took; drives the adaptive
        # cache window so the rebuild can never cost more than it saves.
        self._slim_build_s: float = 0.0
        # ── RF propagation link engine (phase 1) ──
        # Per-gate running stats of realised RF link distances (km):
        # gate → [count, ema_mean, ema_var]. In-memory only; baselines
        # re-learn within hours of a restart, like the beacon cadences.
        self._gate_stats: dict[str, list[float]] = {}
        # Recent anomalous links for /api/prop and (later) the map layer
        self._prop_links: deque = deque(maxlen=500)
        # Calibration: global distance histogram + counters, so thresholds
        # can be tuned from live-feed evidence instead of guesses.
        self._prop_total = 0
        self._prop_anomalous = 0
        self._prop_hist = [0] * len(self._PROP_BUCKETS)

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
        self.last_ingest_ts = time.time()
        if own:
            rec.self_beacon = True
        if not own:
            self._ingest_prop_link(parsed, rec)
        return rec

    def _matches_feed(self, callsign: str) -> bool:
        """Can the current feed hear this station at all?"""
        if not self.feed_filter:
            return True
        base = callsign.split("-")[0]
        for pat in self.feed_filter:
            if pat == "*":
                return True
            if pat.endswith("*"):
                if callsign.startswith(pat[:-1]):
                    return True
            elif callsign == pat or base == pat:
                return True
        return False

    # ── RF propagation link engine ────────────────────────────────────
    @staticmethod
    def _haversine_km(lat1: float, lon1: float,
                      lat2: float, lon2: float) -> float:
        rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
        dlat = rlat2 - rlat1
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2
             + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
        return 6371.0 * 2 * math.asin(math.sqrt(a))

    def _ingest_prop_link(self, parsed: dict[str, Any],
                          rec: StationRecord) -> None:
        """Measure the realised RF link of a direct, RF-gated position packet.

        Every qAR/qAO packet that reached its igate without digi hops is one
        radio path whose length we know exactly: sender's (fresh, in-packet)
        position to the gate's known position. Per-gate baselines separate
        "this gate always hears far" (a mountain-top LoRa igate) from "the
        band just opened" (tropo / sporadic-E).
        """
        if not parsed.get("rf_direct"):
            return
        if "object_sender" in parsed:      # object's position, not sender's
            return
        if rec.self_beacon:
            return
        lat, lon = parsed.get("lat"), parsed.get("lon")
        if lat is None or lon is None:     # need the position from THIS packet
            return
        if abs(lat) < 0.5 and abs(lon) < 0.5:
            # "Null Island": an uninitialised GPS beacons 0°N 0°E, which is
            # 4300-4900 km from European gates — just under the 5000 km data
            # error cap. Live feed showed these as dramatic fake purple
            # lines. There is no land (and no APRS) within half a degree of
            # (0,0) — open Gulf of Guinea.
            return
        if parsed.get("altitude_m", 0) > self.PROP_MAX_ALT_M:
            return                          # balloon — line of sight, not propagation
        gate = parsed.get("gate", "")
        if not gate or gate == rec.callsign or gate == rec.base_call:
            return                          # gate heard itself
        if gate.split("-")[0] == rec.base_call:
            # Sender and gate share a base callsign: one owner's tracker
            # "heard" by their own igate hundreds of km away almost always
            # means one of their devices has stale/misconfigured
            # coordinates, not propagation. A real opening will be
            # evidenced by other stations anyway.
            return
        g = self._stations.get(gate)
        if g is None or g.lat is None or g.lon is None:
            return                          # gate position unknown (yet)
        if abs(g.lat) < 0.5 and abs(g.lon) < 0.5:
            return                          # gate itself parked on Null Island
        if g.is_object or g.self_beacon:
            return

        dist = self._haversine_km(lat, lon, g.lat, g.lon)
        if dist > self.PROP_MAX_KM:
            return                          # GPS garbage / misconfigured coords

        # Calibration histogram + totals
        self._prop_total += 1
        for i, ub in enumerate(self._PROP_BUCKETS):
            if dist <= ub:
                self._prop_hist[i] += 1
                break

        # Per-gate EMA baseline (mean + variance). The anomaly decision uses
        # the PRE-update baseline: folding the outlier in first would inflate
        # σ and let the outlier mask itself. The link still updates the
        # baseline afterwards, so a permanently misconfigured "DX" station
        # gradually becomes that gate's normal and stops alerting.
        st = self._gate_stats.get(gate)
        if st is None:
            st = self._gate_stats[gate] = [0.0, dist, 0.0]
        count, mean, var = st
        a = self._PROP_ALPHA
        st[0] = count + 1
        st[1] = (1 - a) * mean + a * dist
        st[2] = (1 - a) * var + a * (dist - mean) ** 2

        # Anomaly: beyond the absolute floor AND well beyond this gate's own
        # normal — or the gate is too new to have a normal, in which case the
        # absolute floor alone decides (phase 3's ≥2-independent-pairs rule
        # is the defence against a single bogus sender).
        if dist < self.PROP_MIN_KM:
            return
        if count >= self.PROP_MIN_SAMPLES:
            sigma = math.sqrt(max(var, 0.0))
            if dist < max(3 * mean, mean + 4 * sigma):
                return
        self._prop_anomalous += 1
        self._prop_links.append({
            "ts": parsed.get("ts", int(time.time())),
            "call": rec.callsign, "gate": gate,
            "km": round(dist, 1),
            "s_lat": round(lat, 4), "s_lon": round(lon, 4),
            "g_lat": round(g.lat, 4), "g_lon": round(g.lon, 4),
        })

    def gate_baseline(self, gate: str) -> dict[str, Any]:
        """What this gate normally hears — the number the anomaly was judged
        against. A link is only interesting relative to its own gate: 400 km
        is routine for a mountain-top igate and remarkable for a rooftop one,
        and without the baseline a reader cannot tell which they are holding.
        """
        st = self._gate_stats.get(gate)
        if st is None:
            # Baselines live in memory only, so a restart empties them. That
            # is not the same as "this gate is new", and a reader told only
            # "samples: 0" would reasonably conclude the wrong one — most of
            # all on a historical link, where the gate may be long gone.
            return {"gate": gate, "samples": 0, "established": False,
                    "note": "no baseline in this process — gate statistics "
                            "are in-memory and reset on restart, so this "
                            "means 'not measured since the agent last "
                            "started', not 'a new gate'"}
        count, mean, var = st
        sigma = math.sqrt(max(var, 0.0))
        established = count >= self.PROP_MIN_SAMPLES
        return {
            "gate": gate,
            "samples": int(count),
            "established": established,
            "mean_km": round(mean, 1),
            "sigma_km": round(sigma, 1),
            # The threshold this link had to beat. Absolute floor only while
            # the gate is still new, since a handful of samples is not a normal.
            "threshold_km": (round(max(3 * mean, mean + 4 * sigma), 1)
                             if established else self.PROP_MIN_KM),
        }

    def prop_detection_params(self) -> dict[str, Any]:
        """The rule that selected an anomalous link, for an outside reader."""
        return {
            "min_km": self.PROP_MIN_KM,
            "max_km": self.PROP_MAX_KM,
            "max_altitude_m": self.PROP_MAX_ALT_M,
            "gate_min_samples": self.PROP_MIN_SAMPLES,
            "rule": ("distance > min_km AND (the gate has fewer than "
                     "gate_min_samples measured links, or distance exceeds "
                     "max(3*mean, mean + 4*sigma) of that gate's own "
                     "smoothed distance baseline)"),
            "opening_rule": ("2 or more DISTINCT senders in the same "
                             "Maidenhead field within 30 minutes; one long "
                             "link alone is never an opening, because a "
                             "single misconfigured GPS can fake any distance"),
            "excluded": ("internet-origin and digipeated packets, objects, "
                         "balloons above max_altitude_m, and links beyond "
                         "max_km (GPS garbage)"),
        }

    def prop_summary(self, max_links: int = 200) -> dict[str, Any]:
        """Current propagation picture: recent anomalous links + calibration
        stats (global distance histogram, per-gate baseline count)."""
        links = list(self._prop_links)[-max_links:]
        return {
            "links": links,
            "total_links": self._prop_total,
            "anomalous": self._prop_anomalous,
            "gates": len(self._gate_stats),
            "hist": [{"lt": ub, "n": n} for ub, n
                     in zip(self._PROP_BUCKETS, self._prop_hist)],
        }

    # ------------------------------------------------------------------
    def get_all(self) -> list[dict[str, Any]]:
        """Return all stations as a list of dicts, sorted by last_seen desc."""
        rows = [r.to_dict() for r in self._stations.values()]
        rows.sort(key=lambda r: r["last_seen"] or 0, reverse=True)
        return rows

    # Fields the stations table, map markers and popups actually consume.
    # Everything else (comment, last_packet, wx, DB enrichment details…) is
    # served per-station by /api/stations/{callsign} when a row is opened —
    # on a full worldwide feed the complete dump grew past 40 MB per poll.
    _SLIM_FIELDS = (
        "callsign", "type", "icon", "symbol", "symbol_table",
        "symbol_overlay", "city", "district", "locator", "lat", "lon",
        "freq_mhz", "ai_org", "online", "last_seen", "last_seen_ago_s",
        "self_beacon",
    )

    _SLIM_CACHE_TTL = 2.0

    def _slim_all(self) -> list[dict[str, Any]]:
        """The shared, cached base for get_slim(): every station, slim
        fields only, most recently heard first.

        The cache window ADAPTS to how long the rebuild actually takes. A
        fixed 2 s window livelocked a worldwide feed once the registry grew
        past ~70k stations: the rebuild itself took longer than the window,
        so every request found the cache already stale and rebuilt again,
        and the event loop never got a turn — packets kept flowing but the
        whole HTTP API stopped answering. Holding the result for a multiple
        of the build cost keeps that from recurring at any registry size,
        instead of needing this constant re-tuned as the feed grows.
        """
        now = time.time()
        window = max(self._SLIM_CACHE_TTL, self._slim_build_s * 4.0)
        if (self._slim_cache is not None
                and now - self._slim_cache_ts < window):
            return self._slim_cache
        t0 = time.time()
        recs = sorted(list(self._stations.values()),
                      key=lambda r: r.last_seen or 0, reverse=True)
        out = []
        for r in recs:
            d = r.to_dict()
            out.append({k: d[k] for k in self._SLIM_FIELDS})
        self._slim_cache = out
        self._slim_cache_ts = time.time()
        self._slim_build_s = self._slim_cache_ts - t0
        return out

    def get_slim(
        self, limit: int = 0,
        bbox: "Optional[tuple[float, float, float, float]]" = None,
    ) -> tuple[list[dict[str, Any]], int]:
        """List view of the registry: only the fields the station table and
        the map need, most recently heard first, optionally capped at
        `limit` rows. `bbox` = (south, west, north, east) keeps only
        stations inside that box (applied before the cap, so a zoomed map
        view gets every station of the area even when the global list is
        capped). Returns (rows, total_matching_count)."""
        rows = self._slim_all()
        if bbox is not None:
            s, w, n, e = bbox
            rows = [r for r in rows
                    if r["lat"] is not None and r["lon"] is not None
                    and s <= r["lat"] <= n and w <= r["lon"] <= e]
        total = len(rows)
        if limit > 0:
            rows = rows[:limit]
        return rows, total

    def slim_cache_token(self) -> str:
        """Cheap version stamp for the current get_slim() base — changes
        exactly when _slim_all() would recompute. Used for ETag: identical
        bbox/limit requests within the same cache window return the same
        bytes, so a client holding a matching ETag can be told 304 instead
        of re-encoding/re-sending the payload."""
        return str(int(self._slim_cache_ts * 1000))

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
        "ema_interval_s", "last_gate", "hour_counts", "is_object",
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
                "ema_interval_s REAL, last_gate TEXT, hour_counts TEXT,"
                "is_object INTEGER)"
            )
            # Migrate pre-v2.9.3 tables that lack the is_object column
            try:
                con.execute(
                    "ALTER TABLE stations ADD COLUMN is_object INTEGER")
            except sqlite3.OperationalError:
                pass
            rows = [
                (r.callsign, r.first_seen, r.last_seen, r.packet_count,
                 r.lat, r.lon, r.locator, r.symbol, r.symbol_table,
                 r.symbol_overlay, r.station_type, r.icon, r.city, r.district,
                 r.freq_mhz, r.tone_hz, r.comment, r.ai_org, r.ai_description,
                 int(r.ai_analyzed), r.ema_interval_s, r.last_gate,
                 json.dumps(r.hour_counts), int(r.is_object))
                # list() snapshot: this runs in an executor thread while the
                # event loop keeps ingesting — iterating the live dict raised
                # "dictionary changed size during iteration" ~20% of flushes
                # on the 90 pkt/s worldwide feed. list(dict.values()) is a
                # single C-level call, atomic under the GIL.
                for r in list(self._stations.values())
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
            # load runs BEFORE the first save at startup — migrate here too,
            # or the SELECT below fails on a pre-v2.9.3 database and the
            # whole persisted registry is silently lost.
            try:
                con.execute(
                    "ALTER TABLE stations ADD COLUMN is_object INTEGER")
            except sqlite3.OperationalError:
                pass
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
                r.is_object    = bool(d.get("is_object") or 0)
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
        # Only alert cells: the timeline replay paints alert cells only, and
        # worldwide the "any silent station" criterion produced 1000+ rows
        # per 10-minute snapshot (~140k/day) for cells nobody would see.
        cells = [c for c in self.silence_cells() if c["alert"]]
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

        # Deaf guard: if WE have heard nothing for 10 minutes, the problem is
        # our own feed (APRS-IS down, reconnecting) — everyone would look
        # silent, and none of it would be true. No judgement while deaf.
        if self.last_ingest_ts and (now - self.last_ingest_ts) > 600:
            return []

        def gate_active(gate: str) -> Optional[bool]:
            g = self._stations.get(gate)
            if g is None or g.packet_count == 0:
                return None                      # gate not tracked
            return (now - g.last_seen) < 1800    # heard in last 30 min

        cells: dict[str, dict[str, Any]] = {}
        # list() snapshot — also called from executor threads (history
        # snapshots) while the event loop mutates the dict.
        for r in list(self._stations.values()):
            if r.self_beacon:
                continue    # self-generated — never a silence sensor
            if r.is_object:
                continue    # event advisory object — expires by design
            if r.station_type in self._MOBILE_TYPES:
                continue    # moves under its own power — weak silence sensor
            if not self._matches_feed(r.callsign):
                continue    # feed can't hear it — its silence says nothing
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

    def silence_state(self, callsigns) -> dict[str, dict[str, Any]]:
        """Current silence detail for a named set of stations.

        silence_cells() already works out every station's silence threshold
        and the moment it crossed it, then discards all of it when the
        per-station data is aggregated into a cell — so the one question an
        operator actually has during an incident ("which of these never came
        back, and since when?") could not be answered from anywhere in the
        app. This exposes it on demand for specific callsigns, rather than
        widening the /api/silence payload with per-station detail for every
        cell in a worldwide feed.
        """
        now = time.time()
        out: dict[str, dict[str, Any]] = {}
        for call in callsigns:
            r = self._stations.get(call)
            if r is None:
                continue
            threshold = (max(3.0 * r.ema_interval_s, 900.0)
                         if r.ema_interval_s else 900.0)
            out[call] = {
                "call": call,
                "silent": (now - r.last_seen) > threshold,
                # When it crossed its own threshold, not when it was last
                # heard: that is the point it became noteworthy.
                "since": int(r.last_seen + threshold),
                "last_seen": int(r.last_seen),
                "type": r.station_type,
                "lat": r.lat,
                "lon": r.lon,
                "locator": r.locator,
            }
        return out
