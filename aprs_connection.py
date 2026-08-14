"""
APRS-IS Connection
==================
Manages the TCP connection to an APRS-IS server.

Features:
  - Automatic login with callsign and calculated passcode
  - Configurable packet filter (allowed callsigns)
  - Broadcasts every received line to all registered extensions
  - Accepts packets from extensions/beacons to send back to APRS-IS
  - Automatic reconnection on disconnect or error

APRS-IS Protocol basics:
  - Connect via TCP to port 14580 (filtered) or 10152 (full)
  - Send login line: "user CALLSIGN pass PASSCODE vers SOFTWARE filter b/CALLSIGNS"
  - Server sends lines, one APRS packet per line
  - Lines starting with '#' are server comments/status messages

Developed by TA3HRJ & TA3PKS
"""
from __future__ import annotations


import asyncio
import sys
from typing import Any

from config import VERSION, calculate_passcode
from extension_server import ConStore
from extensions import ExtensionRegistry

# Software version string reported to APRS-IS server (kept in sync via config.VERSION)
SOFTWARE_VERSION = f"APRS-AGENT {VERSION}"

# How long the receive loop will wait for ANY line before treating the link as
# dead. An APRS-IS server sends a "# aprsc ..." comment every ~20 s even when
# no traffic matches the filter, so silence this long is not a quiet feed — it
# is a connection that stopped delivering without closing.
#
# Measured 2026-08-14 (F-34): the feed stopped for 729 s and the process said
# nothing at all, because readline() had no deadline and a half-dead TCP socket
# never returns. Twelve minutes of that crossed the 600 s deaf guard in
# silence_cells(), which then reported "nothing is silent anywhere" — 28 cells
# cleared, 5 stations wrongly announced back on the air. The feed is the one
# input everything else depends on and it was the only one with no liveness
# check on it.
READ_TIMEOUT_S = 120.0


async def start_server(config: dict[str, Any], ext_con_store: ConStore) -> None:
    """
    Main APRS-IS connection loop. Connects, runs, and reconnects automatically.
    This function never returns - it loops forever.
    """
    server = config["server"]
    callsign = config["callsign"].upper()
    passcode = calculate_passcode(callsign)
    full_feed = config.get("full_feed", False)
    rate_limit_pps = max(0, int(config.get("rate_limit_pps", 50)))

    if full_feed:
        port = 10152
        login_line = (
            f"user {callsign} pass {passcode} vers {SOFTWARE_VERSION}\r\n"
        )
        print(
            "[full-feed] Full worldwide APRS-IS feed — port 10152, no filter.",
            file=sys.stderr,
        )
    else:
        port = config["port"]
        # Separate exact callsigns (b/ filter) from prefix wildcards (p/ filter)
        exact = []
        prefix = []
        for cs in config["allowed_callsigns"]:
            cs = cs.strip().upper()
            if cs.endswith("*"):
                prefix.append(cs.rstrip("*"))
            else:
                exact.append(cs)

        filters = []
        if exact:
            filters.append("b/" + "/".join(exact))
        if prefix:
            filters.append("p/" + "/".join(prefix))
        filter_cmd = " ".join(filters) if filters else f"b/{callsign}"

        login_line = (
            f"user {callsign} pass {passcode} vers {SOFTWARE_VERSION} "
            f"filter {filter_cmd}\r\n"
        )

    while True:
        print(f"Connecting to {server}:{port} ...", file=sys.stderr)

        try:
            reader, writer = await asyncio.open_connection(server, port)
            print(f"Connected. Logging in as {callsign} ...", file=sys.stderr)

            # Send login
            writer.write(login_line.encode("utf-8"))
            await writer.drain()

            # Queue for extensions (e.g. Fixed Beacon) to send packets
            own_queue: asyncio.Queue = asyncio.Queue()
            ExtensionRegistry.set_own_writers(own_queue)
            ext_con_store.set_upstream(own_queue)

            # Run the receive loop and the send loop concurrently
            await _run_session(reader, writer, own_queue, ext_con_store, rate_limit_pps)

        except ConnectionRefusedError:
            print(
                f"Connection refused by {server}:{port}. Retrying in 5s ...",
                file=sys.stderr,
            )
        except OSError as e:
            print(
                f"Network error: {e}. Reconnecting in 5s ...",
                file=sys.stderr,
            )
        except Exception as e:
            print(
                f"Unexpected error: {e}. Reconnecting in 5s ...",
                file=sys.stderr,
            )

        print("Disconnected from APRS-IS server. Reconnecting in 5s ...", file=sys.stderr)
        await asyncio.sleep(5)


async def _run_session(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    own_queue: asyncio.Queue,
    ext_con_store: ConStore,
    rate_limit_pps: int = 0,
) -> None:
    """
    Handle one active APRS-IS session until disconnect.

    Runs two concurrent loops:
      1. Receive loop: reads lines from APRS-IS and broadcasts to extensions
      2. Send loop: reads from own_queue and sends to APRS-IS
    """
    receive_task = asyncio.create_task(_receive_loop(reader, writer, ext_con_store, rate_limit_pps))
    send_task = asyncio.create_task(_send_loop(writer, own_queue))

    # Wait for either task to finish (either one means we should reconnect)
    done, pending = await asyncio.wait(
        [receive_task, send_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    # Cancel the remaining task
    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


async def _receive_loop(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    ext_con_store: ConStore,
    rate_limit_pps: int = 0,
) -> None:
    """Read lines from APRS-IS and dispatch to extensions and extension server clients."""
    # Token bucket rate limiter — only limits extension dispatch, not TCP receive
    loop = asyncio.get_event_loop()
    tokens: float = float(rate_limit_pps) if rate_limit_pps > 0 else 0.0
    last_refill: float = loop.time()
    _throttled = 0

    while True:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=READ_TIMEOUT_S)
        # Must come before the generic handler: on 3.11+ asyncio.TimeoutError is
        # the builtin TimeoutError, on 3.8-3.10 it is the concurrent.futures one,
        # and both are Exceptions — caught below they would print an empty
        # message and hide exactly the case this was written for.
        except asyncio.TimeoutError:
            print(
                f"[aprs-is] no data for {READ_TIMEOUT_S:.0f}s — link is dead, "
                f"reconnecting ...",
                file=sys.stderr,
            )
            return
        except Exception as e:
            print(f"Read error from APRS-IS: {e}", file=sys.stderr)
            return

        if not raw:
            print("APRS-IS server closed the connection.", file=sys.stderr)
            return

        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")

        if not line:
            continue

        # Rate limiter: refill tokens based on elapsed time, then consume one
        if rate_limit_pps > 0:
            now = loop.time()
            tokens = min(float(rate_limit_pps), tokens + (now - last_refill) * rate_limit_pps)
            last_refill = now
            if tokens >= 1.0:
                tokens -= 1.0
                dispatch = True
            else:
                dispatch = False
                _throttled += 1
                if _throttled % 1000 == 0:
                    print(
                        f"[rate-limit] {_throttled} packets throttled so far "
                        f"(limit: {rate_limit_pps} pkt/s)",
                        file=sys.stderr,
                    )
        else:
            dispatch = True

        if dispatch:
            # Broadcast to all extensions (may write ACK packets back to APRS-IS)
            success = await ExtensionRegistry.broadcast(line, writer)
            if not success:
                print("Write to APRS-IS failed, reconnecting ...", file=sys.stderr)
                return

        # Always forward to extension server clients regardless of rate limit
        ext_con_store.broadcast(line)


async def _send_loop(
    writer: asyncio.StreamWriter,
    own_queue: asyncio.Queue,
) -> None:
    """
    Read outbound packets from the queue (put there by extensions like Fixed Beacon)
    and send them to APRS-IS.
    """
    while True:
        try:
            data: bytes = await own_queue.get()
        except asyncio.CancelledError:
            return

        if not data:
            continue

        if not data.endswith(b"\r\n"):
            data = data.rstrip(b"\r\n") + b"\r\n"

        decoded = data.decode("utf-8", errors="replace").strip()
        print(f"--> {decoded}", file=sys.stderr)

        try:
            writer.write(data)
            await writer.drain()
        except Exception as e:
            print(f"Failed to send packet to APRS-IS: {e}", file=sys.stderr)
            return
