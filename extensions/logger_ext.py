"""
Logger Extension
================
Logs incoming APRS packets to the console.
Supports filtering by APRS data type character and keywords.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


from typing import Optional

import aprslib

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


class Logger(Extension):
    """Logs APRS packets to the terminal. Runs as a background (spawnable) task."""

    def __init__(self, config: dict):
        self._config = config

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
                self.log(line)
            return None

        # Keyword filter mode: only log if a keyword is found
        keyword_filter = cfg.get("keyword_filter", [])
        if keyword_filter:
            lower_line = line.lower()
            if any(k.lower() in lower_line for k in keyword_filter):
                self.log(line)
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
            self.log(line)

        return None
