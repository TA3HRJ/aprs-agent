"""
Logger Extension
================
Logs incoming APRS packets to the console.
Supports filtering by APRS data type character and keywords.

Developed by TA3HX & TA3PKS
"""
from __future__ import annotations


import gzip
import logging
import logging.handlers
import os
import shutil
import sys
import threading
from typing import Optional


from . import Extension


def get_data_type_identifier(line: str) -> str:
    """
    Extract the APRS data type identifier character from a raw APRS line.

    In APRS, the data field starts immediately after the first ':' that
    separates the header (FROM>TO,PATH) from the payload.
    The first character of the payload is the data type identifier.

    Examples:
        !  = position without timestamp
        /  = position with timestamp
        :  = message
        ;  = object
        @  = position with timestamp + messaging
    """
    if line.startswith("#"):
        return "#"
    try:
        colon_idx = line.index(":")
        if colon_idx + 1 < len(line):
            return line[colon_idx + 1]
    except ValueError:
        pass
    return ""


def _gzip_rotator(source: str, dest: str) -> None:
    """Rotate, then compress the rotated file off the event loop.

    AUDIT-2026-10-08 O4. The handler rotates inside a logging call on the
    event loop; compressing 200 MB there would stall everything for seconds.
    The rename is instant, and a thread does the rest. A full-feed log
    compresses about 2.6:1 (200 MB -> 76 MB, measured 2026-10-08), so a week
    of feed fits in about 2 GB.
    """
    plain = dest + ".rotating"           # never the name of an older file
    os.replace(source, plain)

    def _compress() -> None:
        try:
            with open(plain, "rb") as fi, gzip.open(dest + ".part", "wb",
                                                    compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            os.replace(dest + ".part", dest)
            os.remove(plain)
        except Exception as e:
            print(f"[logger] compressing {plain} failed, left as is: {e}",
                  file=sys.__stderr__)

    threading.Thread(target=_compress, name="logzip", daemon=True).start()


class Logger(Extension):
    """Logs APRS packets to the terminal. Runs as a background (spawnable) task."""

    def __init__(self, config: dict):
        self._config = config
        self._file: Optional[logging.Logger] = None
        path = str(config.get("log_file", "") or "").strip()
        if path:
            try:
                d = os.path.dirname(os.path.abspath(path))
                if d:
                    os.makedirs(d, exist_ok=True)
                # Rotates on its own terms instead of competing with every
                # other service for room in the system journal.
                h = logging.handlers.RotatingFileHandler(
                    path, maxBytes=int(float(config.get("log_max_mb", 50)) * 1024 * 1024),
                    backupCount=int(config.get("log_backups", 3)),
                    encoding="utf-8",
                )
                h.setFormatter(logging.Formatter(
                    "%(asctime)s %(message)s", "%Y-%m-%dT%H:%M:%S"))
                if config.get("log_compress"):
                    h.namer = lambda name: name + ".gz"
                    h.rotator = _gzip_rotator
                lg = logging.getLogger("aprs.packetfeed")
                lg.setLevel(logging.INFO)
                lg.propagate = False        # never climb back into stderr
                lg.handlers = [h]
                self._file = lg
            except Exception as e:
                self.error(f"packet log file unusable ({path}): {e}")

    def _record(self, line: str) -> None:
        """One packet. Live Log always, file if configured, journald never."""
        self.feed(line)
        if self._file is not None:
            try:
                self._file.info(line)
            except Exception:
                pass        # a full disk must not stop the agent

    @property
    def name(self) -> str:
        return "logger"

    @property
    def is_spawnable(self) -> bool:
        return True

    async def handle(self, line: str) -> Optional[bytes]:
        cfg = self._config

        # Handle APRS-IS server comment lines (start with '#')
        if line.startswith("#"):
            if cfg.get("log_comments", True):
                self._record(line)
            return None

        # Keyword filter mode: only log if a keyword is found
        keyword_filter = cfg.get("keyword_filter", [])
        if keyword_filter:
            lower_line = line.lower()
            if any(k.lower() in lower_line for k in keyword_filter):
                self._record(line)
            return None

        # Type filter mode: log based on APRS data type identifier
        data_type = get_data_type_identifier(line)
        filter_types = cfg.get("filter_by_message_type", [])
        exclude_types = cfg.get("exclude_by_message_type", [])

        # If filter list is empty, log everything
        if not filter_types or data_type in filter_types:
            if data_type in exclude_types:
                # Warn if the same char is in both lists
                if filter_types:
                    self.warn(
                        f"data type '{data_type}' is in both filter and exclude lists"
                    )
                return None
            self._record(line)

        return None
