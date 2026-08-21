"""
APRS-Agent Extension System
===========================
Base class and registry for all extensions.

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


import asyncio
import sys
import time
from abc import ABC, abstractmethod
from typing import Optional


class Extension(ABC):
    """
    Abstract base class for all APRS-Agent extensions.

    Each extension receives every APRS line from the server and can
    optionally return data to be sent back to the APRS-IS server.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The display name of this extension."""
        pass

    @abstractmethod
    async def handle(self, line: str) -> Optional[bytes]:
        """
        Called for every line received from the APRS-IS server.

        Returns:
            bytes to send back to APRS-IS server, or None.
        """
        pass

    @property
    def is_spawnable(self) -> bool:
        """
        If True, handle() is run in a background task (fire-and-forget).
        Use this for extensions that never write back to the APRS server,
        such as the Logger and Twitter extensions.
        """
        return False

    def set_station_db(self, db) -> None:
        """Hand the extension the live station registry, if it wants one.

        Default is to ignore it. Only the AI gateway uses this, and only to
        answer a sender about their own callsign — the data is already public
        and already in this process, and refusing to read it just sent people
        to aprs.fi for a fact we were sitting on.
        """
        return None

    def set_own_writer(self, queue: asyncio.Queue) -> None:
        """
        Called once at startup to give the extension a queue for sending
        packets to APRS-IS without waiting for an incoming packet first.
        Used by the Fixed Beacon extension.
        """
        pass

    # ── Did it work? ──────────────────────────────────────────────────
    # Class attributes, so an extension needs no constructor to have a
    # sane starting state; marking creates instance attributes.
    #
    # Kept deliberately small. The badge that reads this does not need to
    # become a monitor - it needs to stop saying "active" about a module
    # that has been raising on every message since breakfast.
    _health = "idle"          # idle | ok | error
    _health_note = ""         # operator-facing reason; never leaves /api/info
    _health_at = 0.0          # when the state last changed

    def mark_working(self) -> None:
        """The last thing asked of this extension was carried out.

        A refusal counts: a rate limiter turning somebody away is the module
        doing its job, and reporting that as a fault would train the operator
        to ignore the badge.
        """
        self._health = "ok"
        self._health_note = ""
        self._health_at = time.time()

    def mark_broken(self, why: str) -> None:
        """The last thing asked of this extension failed.

        Truncated, because the reason is written by whatever threw - an HTTP
        client's message can carry a URL, and this ends up in an API response.
        """
        self._health = "error"
        self._health_note = str(why)[:160]
        self._health_at = time.time()

    @property
    def health(self) -> dict:
        return {"state": self._health, "note": self._health_note,
                "at": self._health_at}

    def log(self, msg: str) -> None:
        self._emit(f"\033[32m[{self.name}]\033[0m {msg}")

    def error(self, msg: str) -> None:
        self._emit(f"\033[31m[{self.name}]\033[0m {msg}")

    def warn(self, msg: str) -> None:
        self._emit(f"\033[33m[{self.name}]\033[0m {msg}")

    @staticmethod
    def _emit(line: str) -> None:
        # The Web GUI redirects sys.stderr to a queue feeding the browser's
        # Live Log for the whole time the agent runs, so a plain print() here
        # never reaches the real process stderr that journald captures.
        # Every extension logs through this method (init lines, RX/TX,
        # errors), so without this a server-side operator has no way to
        # confirm from journalctl whether e.g. AI Gateway actually
        # initialized after a config change — same gap already fixed for
        # the silence/prop watch loops in AgentManager._log_both.
        print(line, file=sys.stderr)
        if sys.stderr is not sys.__stderr__:
            print(line, file=sys.__stderr__)


class ExtensionRegistry:
    """
    Global registry that holds all active extensions and broadcasts
    incoming APRS lines to them.
    """

    _extensions: list[Extension] = []

    @classmethod
    def register(cls, ext: Extension) -> None:
        """Add an extension to the registry."""
        ext.log("extension is being activated")
        cls._extensions.append(ext)

    @classmethod
    async def broadcast(cls, line: str, writer: asyncio.StreamWriter) -> bool:
        """
        Send an APRS line to all registered extensions.

        Spawnable extensions run in background tasks.
        Non-spawnable extensions may return data to write back to APRS-IS.

        Returns:
            False if writing to APRS-IS server failed (caller should reconnect).
        """
        for ext in cls._extensions:
            if ext.is_spawnable:
                asyncio.create_task(ext.handle(line))
            else:
                try:
                    result = await ext.handle(line)
                except Exception as e:
                    ext.error(f"unhandled exception in handle(): {e}")
                    # The one place every extension's failure passes through.
                    # v3.2.52 raised here on every message for most of a day
                    # and the interface reported the module active throughout.
                    ext.mark_broken(f"{type(e).__name__}: {e}")
                    result = None

                if result:
                    if not result.endswith(b"\n"):
                        result += b"\n"
                    print(
                        f"[{ext.name}] writing to APRS server:\n"
                        f"{result.decode('utf-8', errors='replace').strip()}\n-----",
                        file=sys.stderr,
                    )
                    try:
                        writer.write(result)
                        await writer.drain()
                    except Exception as e:
                        print(
                            f"Failed to write to APRS server: {e}", file=sys.stderr
                        )
                        return False
        return True

    @classmethod
    def set_own_writers(cls, queue: asyncio.Queue) -> None:
        """
        Pass the outbound queue to all extensions that need to send
        data to APRS-IS independently (e.g. Fixed Beacon).
        """
        for ext in cls._extensions:
            ext.set_own_writer(queue)

    @classmethod
    def clear(cls) -> None:
        """Reset registry (used when reconnecting)."""
        cls._extensions = []
