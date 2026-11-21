#!/usr/bin/env python3
"""Fail if a message to the AI gateway depends on the full feed alone.

On 2026-11-21 one station's messages to DMWGPT reached aprs.fi and never
reached the server the full feed was connected to. Four questions went
unanswered; every packet of that station was missing for 86 minutes while
the rest arrived normally (F-2026-11-21-01). A second connection on port
14580 now fetches the gateway's messages only (filter g/) from another
server.

What must hold (no network; local servers stand in for APRS-IS):

  1. with the full feed on and the gateway enabled, the second connection
     is started; with either off it is not
  2. it logs in receive-only (passcode -1) with a g/ filter for the gateway
     and its SSIDs only (g/X/X-*, not X*), and sends nothing after the login
  3. it does not settle for the main feed's server while another answers:
     rotate.aprs2.net's cached answer led the first deploy back to it four
     times in a row
  4. a message only the second connection delivers reaches the extensions,
     and what they answer goes out on the main connection
  5. a message both deliver is dispatched once, whichever came first - the
     gateway acks every copy it is handed
  6. other traffic on the main feed is dispatched as before, duplicates too
  7. a message the main feed never delivered is counted when it is forgotten

Usage:  python tools/check_side_feed.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import io
import re
import sys
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import aprs_connection as ac  # noqa: E402
from extensions import Extension, ExtensionRegistry  # noqa: E402

GW = "DMWGPT"
CRLF = b"\r\n"
CONFIG = {"server": "127.0.0.1", "callsign": "N0CALL-5", "full_feed": True,
          "extensions": {"ai_gateway": {"enabled": True, "callsign": GW,
                                        "trigger_aliases": []}}}


def msg(src: str, to: str, text: str, mid: str) -> str:
    return f"{src}>APRS,WIDE1-1,qAR,N0IG:{':' + to.ljust(9)}:{text}{{{mid}"


class Recorder(Extension):
    def __init__(self) -> None:
        self.seen: list[str] = []

    @property
    def name(self) -> str:
        return "recorder"

    async def handle(self, line: str):
        self.seen.append(line)
        if f":{GW.ljust(9)}:" in line or f":{(GW + '-1').ljust(9)}:" in line:
            return (b"DMWGPT>APRS,TCPIP*::"
                    + line.split(">")[0].encode() + b":ack")
        return None


class Store:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def broadcast(self, line: str) -> None:
        self.lines.append(line)


class FakeWriter:
    def __init__(self) -> None:
        self.out: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.out.append(data)

    async def drain(self) -> None:
        return None


async def scenario(p: list) -> None:
    rec = Recorder()
    ExtensionRegistry.clear()
    ExtensionRegistry.register(rec)
    store = Store()

    # the stand-in for the second server
    got: list[bytes] = []
    side_lines: asyncio.Queue = asyncio.Queue()

    async def serve(reader, writer):
        async def take():
            while True:
                b = await reader.read(4096)
                if not b:
                    return
                got.append(b)
        t = asyncio.create_task(take())
        writer.write(b"# aprsc 3.0.1" + CRLF
                     + b"# logresp DMWGPT unverified, server T2SIDE" + CRLF)
        await writer.drain()
        while True:
            line = await side_lines.get()
            if line is None:
                break
            writer.write(line.encode() + CRLF)
            await writer.drain()
        t.cancel()
        writer.close()

    srv = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    ac.SIDE_PORT = port
    ac.CONNECT_STAGGER_S = 0.0
    ac._side_watch = ac._side_watch_from(CONFIG)
    own_queue: asyncio.Queue = asyncio.Queue()
    ac._own_queue_now[0] = own_queue
    ac._main_peer[0] = None
    if hasattr(ac, "_main_server"):
        ac._main_server[0] = "T2MAIN"

    main_reader = asyncio.StreamReader()
    main_writer = FakeWriter()
    side = asyncio.create_task(ac._side_feed(CONFIG, store, ac._side_watch))
    main = asyncio.create_task(ac._receive_loop(main_reader, main_writer,
                                                store, 0))

    async def on_main(line: str) -> None:
        main_reader.feed_data(line.encode() + CRLF)
        await asyncio.sleep(0.05)

    async def on_side(line: str) -> None:
        await side_lines.put(line)
        await asyncio.sleep(0.15)

    await asyncio.sleep(0.3)                  # side connects and logs in
    a = msg("AE5HO", GW, "only on the side", "01")
    b = msg("AE5HO", GW, "side first", "02")
    c = msg("AE5HO", GW + "-1", "main first", "03")
    other = msg("W1AW", "N0CALL", "not for the gateway", "09")
    pos = "W1AW>APRS,qAR,N0IG:!4100.00N/02900.00E-"

    await on_side(a)
    await on_side(b)
    await on_main(b)
    await on_main(c)
    await on_side(c)
    await on_main(other)
    await on_main(other)
    await on_main(pos)
    await on_side(other)                      # the filter would not send it

    def n(line: str) -> int:
        return sum(1 for x in rec.seen if x == line)

    login = got[0].decode(errors="replace") if got else ""
    print(f"  side login: {login.strip()!r}")
    if " pass -1 " not in login:
        p.append("the second connection is not receive-only (pass -1)")
    if not login.rstrip().endswith(f"filter g/{GW}/{GW}-*"):
        p.append(f"the second connection does not filter g/{GW}/{GW}-*")
    if b"".join(got)[len(login.encode()):].strip():
        p.append("the second connection sent something after its login")

    print(f"  dispatched: only-side {n(a)}, side-first {n(b)}, "
          f"main-first {n(c)}, other message {n(other)}, position {n(pos)}")
    if n(a) != 1:
        p.append(f"a message only the second connection had was "
                 f"dispatched {n(a)} times, expected 1")
    if n(b) != 1:
        p.append(f"a message from both, second connection first, was "
                 f"dispatched {n(b)} times, expected 1")
    if n(c) != 1:
        p.append(f"a message from both, main feed first, was dispatched "
                 f"{n(c)} times, expected 1")
    if n(other) != 2 or n(pos) != 1:
        p.append("other main-feed traffic was not dispatched as before")
    if sum(1 for x in store.lines if x == b) != 1:
        p.append("the extension server's clients got a message twice")

    queued = []
    while not own_queue.empty():
        queued.append(own_queue.get_nowait())
    print(f"  answers to side-only lines queued on the main connection: "
          f"{len(queued)}")
    if len(queued) != 2:              # a and b came first on the side feed
        p.append(f"{len(queued)} answers to second-connection lines went to "
                 f"the main connection, expected 2")

    before = ac._side_missed[0]
    with redirect_stderr(io.StringIO()) as err:
        ac._first_copy("X>:PRUNE    :x", "main",
                       asyncio.get_event_loop().time() + ac.SIDE_SEEN_S + 20)
    missed = ac._side_missed[0] - before
    print(f"  forgotten: main feed never delivered {missed}")
    if missed != 1:
        p.append(f"{missed} messages counted as missed by the main feed, "
                 f"expected 1 (only-side)")
    if "never delivered" not in err.getvalue():
        p.append("a message the main feed missed is not reported")

    await side_lines.put(None)
    for t in (side, main):
        t.cancel()
    main_reader.feed_eof()
    await asyncio.gather(side, main, return_exceptions=True)
    srv.close()
    ExtensionRegistry.clear()


async def avoid_main(p: list) -> None:
    """Two servers on one port, the first named like the main feed's."""
    if not hasattr(ac, "_side_order"):
        p.append("the second connection takes whichever address comes first")
        return
    names = {"127.0.0.1": b"T2MAIN", "127.0.0.2": b"T2OTHER"}
    conns: list[str] = []

    def handler(ip):
        async def serve(reader, writer):
            conns.append(ip)
            writer.write(b"# logresp DMWGPT unverified, server "
                         + names[ip] + CRLF)
            await writer.drain()
            await reader.read(4096)
            await asyncio.sleep(5)
            writer.close()
        return serve

    a = await asyncio.start_server(handler("127.0.0.1"), "127.0.0.1", 0)
    port = a.sockets[0].getsockname()[1]
    try:
        b = await asyncio.start_server(handler("127.0.0.2"), "127.0.0.2", port)
    except OSError as e:
        print(f"  (no 127.0.0.2 here: {e}; avoidance by name not exercised)")
        a.close()
        b = None
    if b is not None:
        ac.SIDE_PORT = port
        ac.SIDE_SAME_RETRY_S = 0.05
        ac._main_peer[0] = None            # only the name gives it away
        ac._main_server[0] = "T2MAIN"

        async def resolve(server, port_):
            return ["127.0.0.1", "127.0.0.2"]

        real_resolve, real_order = ac._resolve, ac._side_order
        ac._resolve = resolve
        # unshuffled, so the main feed's server is met first
        ac._side_order = lambda addrs, avoid: sorted(
            addrs, key=lambda x: x in avoid)
        err = io.StringIO()
        with redirect_stderr(err):
            t = asyncio.create_task(ac._side_feed(CONFIG, Store(),
                                                  frozenset({GW})))
            await asyncio.sleep(0.6)
            t.cancel()
            await asyncio.gather(t, return_exceptions=True)
        ac._resolve, ac._side_order = real_resolve, real_order
        a.close()
        b.close()
        settled = [ln for ln in err.getvalue().splitlines()
                   if "receive only" in ln]
        print(f"  connections: {conns}; settled: {settled[-1:]}")
        if not settled or "T2OTHER" not in settled[-1]:
            p.append("the second connection settled for the main feed's "
                     "server while another answered")

    # the ordering itself: shuffled, the main feed's address last
    ac._main_peer[0] = "10.0.0.1"
    three = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    firsts = {ac._side_order(three, set())[0] for _ in range(60)}
    lasts = {ac._side_order(three, set())[-1] for _ in range(20)}
    print(f"  first address over 60 orderings: {sorted(firsts)}; "
          f"last: {sorted(lasts)}")
    if "10.0.0.1" in firsts or lasts != {"10.0.0.1"}:
        p.append("the main feed's address is not tried last")
    if len(firsts) < 2:
        p.append("the other addresses are not shuffled")


def main() -> int:
    p: list[str] = []
    if not hasattr(ac, "_side_feed"):
        print("\nFAIL\n  - there is no second connection for the gateway's "
              "messages")
        return 1

    w = ac._side_watch_from(CONFIG)
    off = dict(CONFIG, extensions={"ai_gateway": {"enabled": False,
                                                  "callsign": GW}})
    print(f"  watched with the gateway on: {sorted(w)}; off: "
          f"{sorted(ac._side_watch_from(off))}")
    if w != {GW} or ac._side_watch_from(off):
        p.append("the watched callsigns do not follow the gateway's config")
    src = (ROOT / "aprs_connection.py").read_text(encoding="utf-8")
    if not re.search(r"_side_watch_from\(config\) if full_feed", src):
        p.append("the second connection is not limited to the full feed")

    with redirect_stderr(io.StringIO()):
        asyncio.run(scenario(p))
    asyncio.run(avoid_main(p))

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
