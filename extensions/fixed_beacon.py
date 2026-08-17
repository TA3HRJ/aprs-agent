"""
Fixed Beacon Extension
======================
Periodically sends a fixed position beacon to the APRS-IS network.

This tells other amateur radio operators and APRS applications where
your station is located, even if you have no radio connected.

The beacon format follows the APRS protocol standard for position reports.

Configuration fields in aprsconfig.toml:
  ssid              = Your callsign + SSID, e.g. "N0CALL-10"
  lat               = Latitude in APRS format: DDMM.MMN, e.g. "4100.00N"
  lon               = Longitude in APRS format: DDDMM.MME, e.g. "02900.00E"
  symbol_table      = '/' for primary table, '\\' for alternate table
  symbol            = Symbol character, e.g. '-' (house), '>' (car)
  comment           = Short text shown on APRS maps
  beacon_interval_mins = How often to send, in minutes

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


import asyncio
from typing import Optional

from . import Extension


class FixedBeacon(Extension):
    """
    Sends a fixed APRS position beacon on a configurable interval.

    Uses an asyncio Queue (own_writer) to send packets to APRS-IS
    without waiting for an incoming packet.
    """

    def __init__(self, config: dict):
        self._config = config
        self._queue: Optional[asyncio.Queue] = None
        self._task_started = False
        self._validate()
        self.log(
            f"Fixed beacon initialized | ssid={config['ssid']} "
            f"| pos={config['lat']},{config['lon']} "
            f"| interval={config['beacon_interval_mins']} min"
        )

    def _validate(self) -> None:
        cfg = self._config
        if len(cfg.get("ssid", "")) > 9:
            raise ValueError("Fixed beacon: ssid cannot be longer than 9 characters")
        lat = cfg.get("lat", "")
        lon = cfg.get("lon", "")
        if len(lat) > 8:
            raise ValueError("Fixed beacon: lat cannot be longer than 8 characters")
        if len(lon) > 9:
            raise ValueError("Fixed beacon: lon cannot be longer than 9 characters")
        if not lat.endswith(("N", "S")):
            raise ValueError("Fixed beacon: lat must end with 'N' or 'S'")
        if not lon.endswith(("E", "W")):
            raise ValueError("Fixed beacon: lon must end with 'E' or 'W'")

    @property
    def name(self) -> str:
        return "fixed_beacon"

    def set_own_writer(self, queue: asyncio.Queue) -> None:
        """Receive the outbound queue and start the beacon loop."""
        self._queue = queue
        if not self._task_started:
            asyncio.create_task(self._beacon_loop())
            self._task_started = True

    async def handle(self, line: str) -> Optional[bytes]:
        # Fixed beacon does not react to incoming packets
        return None

    async def _beacon_loop(self) -> None:
        """Send a beacon, then wait, then repeat forever."""
        cfg = self._config
        interval_seconds = cfg.get("beacon_interval_mins", 15) * 60

        while True:
            await self._send_beacon()
            await self._send_status()
            await asyncio.sleep(interval_seconds)

    async def _send_status(self) -> None:
        """Send this station's APRS status packet, if one is configured.

        A position report carries a comment; a status is a separate packet
        with a separate text, and aprs.fi shows both at once. Keeping them
        apart means the comment can say what the station is while the status
        says who runs it, instead of one field carrying both badly.

        The 62-character cap is the conventional limit for status text.
        """
        if self._queue is None:
            return
        text = (self._config.get("status_text") or "").strip()
        if not text:
            return
        ssid = self._config.get("ssid", "N0CALL-10").upper()
        packet = f"{ssid}>AP4GNT,TCPIP*:>{text[:62]}\r\n"
        await self._queue.put(packet.encode("utf-8"))
        self.log(f"status sent: {packet.strip()}")

    async def _send_beacon(self) -> None:
        """Build and enqueue one APRS position beacon packet."""
        if self._queue is None:
            return

        cfg = self._config
        ssid = cfg.get("ssid", "N0CALL-10").upper()
        lat = cfg.get("lat", "0000.00N")
        lon = cfg.get("lon", "00000.00E")
        symbol_table = cfg.get("symbol_table", "/")
        symbol = cfg.get("symbol", "-")
        comment = cfg.get("comment", "APRS-Agent")

        # APRS position beacon format:
        # SSID>AP4GNT,TCPIP*,qAC,APRSAGENT:!LATTSTLONS COMMENT
        packet = (
            f"{ssid}>AP4GNT,TCPIP*:"
            f"!{lat}{symbol_table}{lon}{symbol}{comment}\r\n"
        )

        try:
            await self._queue.put(packet.encode("utf-8"))
            self.log(f"beacon sent: {packet.strip()}")
        except Exception as e:
            self.error(f"failed to enqueue beacon: {e}")
