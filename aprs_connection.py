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


async def start_server(config: dict[str, Any], ext_con_store: ConStore) -> None:
    """
    Main APRS-IS connection loop. Connects, runs, and reconnects automatically.
    This function never returns - it loops forever.
    """
    server = config["server"]
    port = config["port"]
    callsign = config["callsign"].upper()
    passcode = calculate_passcode(callsign)
    filter_str = "/".join(config["allowed_callsigns"])

    # Build the APRS-IS login line
    login_line = (
        f"user {callsign} pass {passcode} vers {SOFTWARE_VERSION} "
        f"filter b/{filter_str}\n"
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

            # Run the receive loop and the send loop concurrently
            await _run_session(reader, writer, own_queue, ext_con_store)

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
) -> None:
    """
    Handle one active APRS-IS session until disconnect.

    Runs two concurrent loops:
      1. Receive loop: reads lines from APRS-IS and broadcasts to extensions
      2. Send loop: reads from own_queue and sends to APRS-IS
    """
    receive_task = asyncio.create_task(_receive_loop(reader, writer, ext_con_store))
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
) -> None:
    """Read lines from APRS-IS and dispatch to extensions and extension server clients."""
    while True:
        try:
            raw = await reader.readline()
        except Exception as e:
            print(f"Read error from APRS-IS: {e}", file=sys.stderr)
            return

        if not raw:
            print("APRS-IS server closed the connection.", file=sys.stderr)
            return

        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")

        if not line:
            continue

        # Broadcast to all extensions (may write ACK packets back to APRS-IS)
        success = await ExtensionRegistry.broadcast(line, writer)
        if not success:
            print("Write to APRS-IS failed, reconnecting ...", file=sys.stderr)
            return

        # Broadcast to extension server (external TCP clients)
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

        if not data.endswith(b"\n"):
            data += b"\n"

        decoded = data.decode("utf-8", errors="replace").strip()
        print(f"--> {decoded}", file=sys.stderr)

        try:
            writer.write(data)
            await writer.drain()
        except Exception as e:
            print(f"Failed to send packet to APRS-IS: {e}", file=sys.stderr)
            return
