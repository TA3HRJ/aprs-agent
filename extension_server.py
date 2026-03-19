"""
Extension Server (TCP)
======================
Provides a local TCP server that external programs can connect to and
receive a live stream of APRS packets.

Protocol:
  Client -> Server:  "ping\n"
  Server -> Client:  "pong {unix_timestamp}\n"
  Server -> Client:  "data {aprs_line}\n"  (for every APRS packet received)

A client that sends no "ping" for 10 seconds is disconnected.

This allows other software on the same computer to subscribe to the
APRS data stream without needing to connect directly to APRS-IS.

Developed by TA3HRJ & TA3PKS
"""

import asyncio
import sys
import time
from typing import Optional


class ConStore:
    """
    Thread-safe store of connected extension server clients.
    Each client has an asyncio.Queue for outbound messages.
    """

    def __init__(self) -> None:
        self._clients: dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def add(self, addr: str, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._clients[addr] = queue

    async def remove(self, addr: str) -> None:
        async with self._lock:
            self._clients.pop(addr, None)

    def broadcast(self, message: str) -> None:
        """Send an APRS line to all connected clients (non-blocking)."""
        for queue in self._clients.values():
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                pass  # Drop the packet if a client is too slow


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    store: ConStore,
) -> None:
    """Handle a single connected extension server client."""
    addr = writer.get_extra_info("peername")
    addr_str = f"{addr[0]}:{addr[1]}" if addr else "unknown"
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    print(f"[extension_server] new connection from {addr_str}", file=sys.stderr)
    await store.add(addr_str, queue)

    try:
        while True:
            # Wait for either: a ping from the client, data to send, or a timeout
            try:
                done, pending = await asyncio.wait(
                    [
                        asyncio.create_task(reader.readline()),
                        asyncio.create_task(queue.get()),
                    ],
                    timeout=10.0,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except Exception:
                break

            if not done:
                # 10-second timeout reached with no activity
                print(
                    f"[extension_server] client {addr_str} timed out",
                    file=sys.stderr,
                )
                for task in pending:
                    task.cancel()
                break

            # Cancel the tasks that did NOT finish
            for task in pending:
                task.cancel()

            for task in done:
                try:
                    result = task.result()
                except Exception:
                    result = None

                if isinstance(result, bytes):
                    # Incoming data from client (ping command)
                    cmd = result.decode("utf-8", errors="replace").strip().lower()
                    if not cmd:
                        print(
                            f"[extension_server] empty line from {addr_str}, disconnecting",
                            file=sys.stderr,
                        )
                        return
                    if cmd == "ping":
                        pong = f"pong {int(time.time())}\n"
                        writer.write(pong.encode("utf-8"))
                        await writer.drain()
                    else:
                        print(
                            f"[extension_server] unknown command from {addr_str}: {cmd!r}",
                            file=sys.stderr,
                        )
                        return

                elif isinstance(result, str):
                    # Outbound APRS data to send to the client
                    try:
                        writer.write(f"data {result}\n".encode("utf-8"))
                        await writer.drain()
                    except Exception:
                        return

    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[extension_server] error for {addr_str}: {e}", file=sys.stderr)
    finally:
        await store.remove(addr_str)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        print(f"[extension_server] {addr_str} disconnected", file=sys.stderr)


def start(config: dict) -> ConStore:
    """
    Start the TCP extension server and return the ConStore.
    The server runs as a background asyncio task.
    """
    host = config["extension_server"]["host"]
    port = config["extension_server"]["port"]
    store = ConStore()

    async def _serve() -> None:
        server = await asyncio.start_server(
            lambda r, w: _handle_client(r, w, store),
            host,
            port,
        )
        print(f"[extension_server] listening on {host}:{port}", file=sys.stderr)
        async with server:
            await server.serve_forever()

    asyncio.create_task(_serve())
    return store
