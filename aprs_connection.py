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

Developed by TA3HX, TA3PKS & TA3EKM
"""
from __future__ import annotations


import asyncio
import random
import socket
import sys
from typing import Any

from config import VERSION, calculate_passcode, strip_ssid
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

# The connect had no deadline either. rotate.aprs2.net answers with eleven
# addresses and asyncio tries them one after another, so a dead first one
# cost the kernel's whole TCP connect timeout, about two minutes, before the
# next was tried. Twice a deploy's health check gave up first and rolled a
# good release back (F-2026-10-31-06). Now the next address starts after
# CONNECT_STAGGER_S whether or not the last has failed, and the whole attempt
# ends at CONNECT_TIMEOUT_S, when the name is looked up again.
CONNECT_TIMEOUT_S = 30.0
CONNECT_STAGGER_S = 5.0


# -- The message side feed -------------------------------------------------
# The full feed is one TCP connection to one server. On 2026-11-21 a
# station's four questions to the AI gateway reached aprs.fi and never
# reached the server this agent was connected to. Every packet of that one
# station was missing for 86 minutes while the rest arrived normally
# (F-2026-11-21-01).
#
# So beside the full feed a second, small connection asks another server on
# port 14580 for messages addressed to the gateway only (filter g/), receive
# only (passcode -1). Whichever copy of a message arrives first is
# dispatched; the other is dropped here. That matters: the gateway acks
# every copy it is handed, so a message from both feeds would be acked twice.
SIDE_PORT = 14580
SIDE_SEEN_S = 120.0      # how long a message is remembered across the feeds
SIDE_SAME_RETRY_S = 5.0  # after landing on the main feed's server

_side_watch: frozenset = frozenset()   # SSID-free addressees watched
_seen: dict = {}         # key -> [first seen, "main"|"side", main confirmed]
_seen_pruned = [0.0]
_own_queue_now: list = [None]          # the main session's outbound queue
_main_peer: list = [None]              # the main feed's server address
_main_server: list = [None]            # and its name, from "# logresp"
_side_missed = [0]       # messages only the side feed delivered


def _both_streams(line: str) -> None:
    """Live Log and journal both (see _warn_login_collision)."""
    print(line, file=sys.stderr)
    if sys.stderr is not sys.__stderr__:
        print(line, file=sys.__stderr__)


def _side_watch_from(config: dict) -> frozenset:
    """SSID-free callsigns whose messages the side feed fetches."""
    gw = (config.get("extensions") or {}).get("ai_gateway") or {}
    if not gw.get("enabled", True):
        return frozenset()
    calls = [gw.get("callsign", "")] + list(gw.get("trigger_aliases") or [])
    return frozenset(strip_ssid(c.strip().upper()) for c in calls
                     if c and c.strip())


def _watched_msg_key(line: str, watch: frozenset):
    """'SRC>:ADDRESSEE:text{id' for a message to a watched call, else None.

    The path is left out on purpose: the same packet comes through two
    servers, and it is the same message whichever way it came."""
    if not watch or line.startswith("#"):
        return None
    head, sep, payload = line.partition(":")
    if not sep or len(payload) < 11 or payload[0] != ":" or payload[10] != ":":
        return None
    if strip_ssid(payload[1:10].strip().upper()) not in watch:
        return None
    return head.split(">", 1)[0].upper() + ">" + payload


def _first_copy(key: str, origin: str, now: float) -> bool:
    """True for the first copy of a message within SIDE_SEEN_S, recording it.

    A message the side feed delivered and the main feed never did is
    reported when it is forgotten: that count is what the side feed is for."""
    if now - _seen_pruned[0] > 10.0:
        _seen_pruned[0] = now
        for k, v in list(_seen.items()):
            if now - v[0] > SIDE_SEEN_S:
                del _seen[k]
                if v[1] == "side" and not v[2]:
                    _side_missed[0] += 1
                    _both_streams(
                        f"[side-feed] the main feed never delivered "
                        f"{k[:80]!r} ({_side_missed[0]} so far)")
    hit = _seen.get(key)
    if hit is None or now - hit[0] > SIDE_SEEN_S:
        _seen[key] = [now, origin, origin == "main"]
        return True
    if origin == "main":
        hit[2] = True
    return False


def _logresp_server(line: str):
    """'T2IRELAND' from '# logresp X unverified, server T2IRELAND'."""
    if line.startswith("# logresp") and " server " in line:
        return line.rsplit(" server ", 1)[1].split()[0] or None
    return None


def _side_filter(watch: frozenset) -> str:
    """g/X/X-* for each watched call: the call and its SSIDs, nothing else.
    X* would also take every addressee that merely begins with X."""
    return "/".join(f"{c}/{c}-*" for c in sorted(watch))


def _side_order(addrs: list, avoid: set) -> list:
    """Shuffled, the main feed's server and those found to be it last.

    rotate.aprs2.net's answer comes back in the same order for as long as
    the resolver caches it, so the first address is usually the one the
    main feed took: on 2026-11-21 the first deploy met it four times in a
    row and settled for it."""
    addrs = list(dict.fromkeys(addrs))
    random.shuffle(addrs)
    return sorted(addrs, key=lambda a: a == _main_peer[0] or a in avoid)


async def _resolve(server: str, port: int) -> list:
    infos = await asyncio.get_event_loop().getaddrinfo(
        server, port, type=socket.SOCK_STREAM)
    return [i[4][0] for i in infos]


class _ToMainFeed:
    """Writer for the side feed's dispatch: anything an extension answers
    goes out on the main connection. The side connection never sends."""

    def write(self, data: bytes) -> None:
        q = _own_queue_now[0]
        if q is not None:
            q.put_nowait(data)

    async def drain(self) -> None:
        return None


async def _side_feed(config: dict[str, Any], ext_con_store: ConStore,
                     watch: frozenset) -> None:
    """Receive-only connection for messages to the gateway. Never returns."""
    server = config["server"]
    gw = (config.get("extensions") or {}).get("ai_gateway") or {}
    login = (gw.get("callsign") or sorted(watch)[0]).upper()
    flt = _side_filter(watch)
    login_line = (f"user {login} pass -1 vers {SOFTWARE_VERSION} "
                  f"filter g/{flt}\r\n")
    loop = asyncio.get_event_loop()
    avoid: set = set()        # addresses that turned out to be the main's
    await asyncio.sleep(CONNECT_STAGGER_S)    # let the main feed pick first
    while True:
        writer = None
        pause = 30
        try:
            addrs = _side_order(await _resolve(server, SIDE_PORT), avoid)
            for addr in addrs:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(addr, SIDE_PORT),
                        timeout=CONNECT_TIMEOUT_S / 3)
                    break
                except (OSError, asyncio.TimeoutError):
                    continue
            if writer is None:
                raise ConnectionError(f"no address of {server} answered")
            writer.write(login_line.encode("utf-8"))
            await writer.drain()
            while True:
                raw = await asyncio.wait_for(reader.readline(),
                                             timeout=READ_TIMEOUT_S)
                if not raw:
                    raise ConnectionResetError("server closed the connection")
                line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                if line.startswith("#"):
                    name = _logresp_server(line)
                    if name is None:
                        continue
                    # The same server by another address (IPv4 beside IPv6)
                    # shows only here. Settle for it when nothing else is left.
                    if name == _main_server[0] and len(avoid) < len(addrs) - 1:
                        avoid.add(addr)
                        pause = SIDE_SAME_RETRY_S
                        raise ConnectionAbortedError(
                            f"{name} is the main feed's server")
                    _both_streams(f"[side-feed] {name} {addr}:{SIDE_PORT} "
                                  f"g/{flt}, receive only")
                    continue
                key = _watched_msg_key(line, watch)
                if key is None or not _first_copy(key, "side", loop.time()):
                    continue
                await ExtensionRegistry.broadcast(line, _ToMainFeed())
                ext_con_store.broadcast(line)
        except Exception as e:                # CancelledError is not one
            _both_streams(f"[side-feed] {type(e).__name__}: {e}. "
                          f"Retrying in {pause}s ...")
        finally:
            if writer is not None:
                writer.close()
        await asyncio.sleep(pause)


def _warn_login_collision(callsign: str) -> None:
    """Say which callsign we log in as, and warn when it carries no SSID.

    APRS-IS does not deliver a packet to a connection whose login matches the
    callsign in the packet's q-construct. Anything this station injects is
    stamped with its own login and therefore never comes back — which is
    correct and is what the Fixed Beacon's own ingest path relies on.

    The trap is a *second* device of the operator's logging in under the same
    callsign. Its traffic is stamped with that callsign too, so this agent
    never sees it, silently and with no error anywhere. Measured on
    2026-09-09: an operator's own SharkRF openSPOT4 injecting as
    `qAS,TA3HRJ` was invisible for the whole 5 h 15 min of retained feed —
    zero packets — while every other station of the same base callsign
    arrived normally. One SSID on the login and the next beacon arrived 51
    seconds later (F-2026-09-10-01).

    A bare base callsign is the value a hotspot, an igate or a phone app will
    pick by default, so it is the one most likely to collide. An SSID makes
    the collision unlikely rather than merely improbable, and costs nothing:
    the passcode is computed from the base callsign either way.
    """
    lines = [f"[aprs-is] login callsign: {callsign}"]
    if strip_ssid(callsign) == callsign:
        lines.append(
            f"[aprs-is] WARNING: logging in as {callsign} with no SSID. Any "
            f"other device of yours logging in as {callsign} — a hotspot, an "
            f"igate, a phone app — becomes invisible to this agent, with no "
            f"error reported. Consider {callsign}-5 or another SSID."
        )
    for line in lines:
        # Both streams on purpose. While the agent runs, sys.stderr is the
        # browser's Live Log; sys.__stderr__ is what journald captures. This
        # exists to make the login readable months later from `journalctl`,
        # so the second write is the one that matters — v3.2.108 shipped with
        # only the first and the line never reached the journal at all.
        print(line, file=sys.stderr)
        if sys.stderr is not sys.__stderr__:
            print(line, file=sys.__stderr__)


async def start_server(config: dict[str, Any], ext_con_store: ConStore) -> None:
    """
    Main APRS-IS connection loop. Connects, runs, and reconnects automatically.
    This function never returns - it loops forever.
    """
    server = config["server"]
    callsign = config["callsign"].upper()
    passcode = calculate_passcode(callsign)
    _warn_login_collision(callsign)
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

    global _side_watch
    _side_watch = _side_watch_from(config) if full_feed else frozenset()
    # Lives as long as this call: cancelled with it (an agent restart).
    side_task = (asyncio.create_task(
        _side_feed(config, ext_con_store, _side_watch))
        if _side_watch else None)
    try:
        await _main_feed(server, port, callsign, login_line, ext_con_store,
                         rate_limit_pps)
    finally:
        if side_task is not None:
            side_task.cancel()


async def _main_feed(server: str, port: int, callsign: str, login_line: str,
                     ext_con_store: ConStore, rate_limit_pps: int) -> None:
    """The full (or filtered) feed: connect, run, reconnect, forever."""

    while True:
        print(f"Connecting to {server}:{port} ...", file=sys.stderr)

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(server, port,
                                        happy_eyeballs_delay=CONNECT_STAGGER_S),
                timeout=CONNECT_TIMEOUT_S)
            print(f"Connected. Logging in as {callsign} ...", file=sys.stderr)
            _main_peer[0] = (writer.get_extra_info("peername") or (None,))[0]

            # Send login
            writer.write(login_line.encode("utf-8"))
            await writer.drain()

            # Queue for extensions (e.g. Fixed Beacon) to send packets
            own_queue: asyncio.Queue = asyncio.Queue()
            _own_queue_now[0] = own_queue
            ExtensionRegistry.set_own_writers(own_queue)
            ext_con_store.set_upstream(own_queue)

            # Run the receive loop and the send loop concurrently
            await _run_session(reader, writer, own_queue, ext_con_store, rate_limit_pps)

        except asyncio.TimeoutError:
            # Before OSError: from 3.11 this is TimeoutError, an OSError, and
            # would print as "Network error: ." Both streams, so the journal
            # can tell this from a hang somewhere else.
            line = (f"[aprs-is] no answer from {server}:{port} in "
                    f"{CONNECT_TIMEOUT_S:.0f}s. Retrying in 5s ...")
            print(line, file=sys.stderr)
            if sys.stderr is not sys.__stderr__:
                print(line, file=sys.__stderr__)
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

        if line[0] == "#" and _side_watch:
            name = _logresp_server(line)
            if name:
                _main_server[0] = name

        # A message to the gateway the side feed has already dispatched.
        if dispatch and _side_watch:
            key = _watched_msg_key(line, _side_watch)
            if key is not None and not _first_copy(key, "main", loop.time()):
                continue

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
