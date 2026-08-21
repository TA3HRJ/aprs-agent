#!/usr/bin/env python3
"""Fail if the module badge can claim "active" about something that is not.

The AI Gateway raised on every message it received for most of a day. The
badge stayed lit the whole time, because it was computed from configuration
alone — an honest answer to "is this switched on" being read as "is this
working". The only symptom was a log line that stopped appearing, and nobody
watches for an absence.

Five things this holds:

  1. a freshly started extension reports `idle`, not `ok` — configured is not
     working, and claiming otherwise is the whole fault
  2. an extension that raised inside handle() reports `error`, and it is the
     registry that notices, so this covers every extension and not just the
     one that broke last time
  3. a delivered answer reports `ok`
  4. a provider failure reports `error` even though the exception is
     swallowed — silence to the sender is exactly what hid this for a day
  5. a rate-limited refusal reports `ok`. This one is a guard against the
     fix: a badge that cries wolf when a limiter does its job gets ignored,
     and an ignored badge is the state we started in

No network and no provider.

Usage:  python tools/check_health.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions import Extension, ExtensionRegistry  # noqa: E402
from extensions.ai_gateway_ext import AIGateway  # noqa: E402

CFG = {
    "enabled": True,
    "callsign": "DMWGPT",
    "provider": "deepseek",
    "api_keys": {"deepseek": "stub"},
    "extra_sms": 2,
    "rate_burst": 0,
    "rate_refill_s": 0,
}


def line(text: str, sender: str = "TA1ABC-7") -> str:
    return "%s>APDR16,TCPIP*,qAC,T2X::DMWGPT   :%s" % (sender, text)


class Sink:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def gateway() -> AIGateway:
    gw = AIGateway(dict(CFG), "")
    gw._own_writer = Sink()
    return gw


class Exploding(Extension):
    """Stands in for any extension with a fault, not just the one we had."""

    @property
    def name(self) -> str:
        return "exploding"

    async def handle(self, line: str):
        raise RuntimeError("severed constructor tail")


class FakeWriter:
    def write(self, b):
        pass

    async def drain(self):
        pass


async def run() -> int:
    problems: list[str] = []
    results: list[tuple[str, str, str]] = []

    def check(label: str, got: str, want: str) -> None:
        results.append((label, want, got))
        if got != want:
            problems.append("%s: badge would say %r, should say %r"
                            % (label, got, want))

    # 1. never exercised
    check("fresh start", gateway().health["state"], "idle")

    # 2. any extension that raises, caught where they are all caught
    ExtensionRegistry.clear()
    boom = Exploding()
    ExtensionRegistry.register(boom)
    await ExtensionRegistry.broadcast(line("anything"), FakeWriter())
    check("raised in handle()", boom.health["state"], "error")
    ExtensionRegistry.clear()

    # 3. answered
    gw = gateway()

    async def ok(q, s=""):
        return "A dipole is fine for that band."

    gw._ask_ai = ok
    await gw.handle(line("what antenna?"))
    check("answer delivered", gw.health["state"], "ok")

    # 4. provider down. _ask_ai swallows and returns "" — the sender gets
    #    silence, and silence is what the badge has to stop hiding.
    gw = gateway()

    def explode():
        raise OSError("connection refused")

    async def dead(q, s=""):
        try:
            explode()
        except Exception as e:
            gw.error("AI query failed: %s: %s" % (type(e).__name__, e))
            gw.mark_broken("AI query failed: %s" % type(e).__name__)
            return ""

    gw._ask_ai = dead
    await gw.handle(line("what antenna?"))
    check("provider failed", gw.health["state"], "error")

    # 5. a limiter refusing is the module working
    gw = AIGateway(dict(CFG, rate_burst=1, rate_refill_s=3600), "")
    gw._own_writer = Sink()

    async def ok2(q, s=""):
        return "fine"

    gw._ask_ai = ok2
    await gw.handle(line("first question"))
    await gw.handle(line("second question"))
    check("rate limited", gw.health["state"], "ok")

    for label, want, got in results:
        print("  %-20s beklenen %-6s  bulunan %s" % (label, want, got))

    print()
    for p in problems:
        print("FAIL  " + p)
    print("%d problem%s" % (len(problems), "" if len(problems) == 1 else "s"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.get_event_loop().run_until_complete(run()))
