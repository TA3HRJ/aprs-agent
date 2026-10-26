#!/usr/bin/env python3
"""Fail if the Telegram bridge carries a message for anyone who has not
proven a callsign from the radio, or loses a link it was given.

Person to person between licensed amateurs (NEXT 24, KEGM Yön. Md.23/1-c,
1-f): a Telegram chat is linked to a callsign by a code the bot gives and the
radio sends back. Only the operator's configured chat and linked chats put
text on air, each under its own callsign.

What must hold (Telegram API and APRS-IS replaced, no network):

  1. /bagla CALL from any chat answers with a code and puts nothing on air
  2. "LINK <code>" sent from that callsign's radio links the chat to the
     radio's full callsign and says so in Telegram; from another callsign,
     or after ten minutes, it links nothing
  3. a linked chat's "CALL text" goes on air from its own callsign ("own")
     or from the gateway with "CALL: " in the text ("gateway")
  4. an unlinked chat puts nothing on air and is told how to link
  5. a radio's "TGSEND CALL text" reaches CALL's linked chat
  6. the operator's chat and allowed senders work as before
  7. /coz removes the link; after it the chat puts nothing on air
  8. a linked chat is held to its hourly limit
  9. a link survives a restart (read back from the file)
 10. links are off unless the operator opens them (allow_links, default
     false): without them a stranger's /bagla links nothing and puts
     nothing on air

Usage:  python tools/check_bridge_links.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import extensions.telegram_ext as tg  # noqa: E402
import extensions.bridge_links as bl  # noqa: E402

OP_CHAT, AMA_CHAT, STRANGER = "42", "777", "888"
sent_tg: list = []
updates: list = []


def fake_api(token, method, params=None, timeout=None):
    if method == "getUpdates":
        out = list(updates)
        updates.clear()
        return {"ok": True, "result": out}
    if method == "sendMessage":
        sent_tg.append((str(params["chat_id"]), params["text"]))
    return {"ok": True}


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def bridge(links, mode="own"):
    cfg = {"enabled": True, "bot_token": "stub", "chat_id": OP_CHAT, "poll_enabled": True,
           "from_callsign": "TA3HX-6", "allowed_recepients": ["TGSEND"],
           "allowed_senders": ["TA3HX"], "aprs_source": mode}
    ext = tg.Telegram(cfg)
    getattr(ext, "set_links", lambda _l: None)(links)
    q = Q()
    ext._queue = q
    ext.log = ext.warn = lambda m: None
    return ext, q


def tg_msg(ext, chat, text):
    updates.append({"update_id": len(sent_tg) + 1000 + len(updates),
                    "message": {"chat": {"id": int(chat)}, "from": {"first_name": "x"}, "text": text}})
    asyncio.run(ext._check_updates())


def radio(ext, sender, text, msgno="1"):
    line = f"{sender}>APK005,TCPIP*,qAC,T2TEST::TGSEND   :{text}{{{msgno}"
    return asyncio.run(ext.handle(line))


def main() -> int:
    tg._tg_api = fake_api
    p = []
    path = Path(tempfile.mkdtemp()) / "bridge_links.json"
    links = bl.BridgeLinks(path)
    ext, q = bridge(links)

    tg_msg(ext, AMA_CHAT, "/bagla TA1ABC")
    reply = ([t for c, t in sent_tg if c == AMA_CHAT] or [""])[-1]
    code = reply.split("LINK ")[1].split()[0] if "LINK " in reply else ""
    print(f"  1 /bagla -> code {code!r}, on air {q.sent}")
    if not code.isdigit() or q.sent:
        p.append(f"1: {reply!r} {q.sent}")

    radio(ext, "TA9XYZ-7", f"LINK {code}")
    if links.by_call("telegram", "TA1ABC"):
        p.append("2: another callsign's radio linked the chat")
    ack = radio(ext, "TA1ABC-7", f"LINK {code}")
    entry = links.by_call("telegram", "TA1ABC")
    told = ([t for c, t in sent_tg if c == AMA_CHAT] or [""])[-1]
    print(f"  2 LINK from radio -> {entry} | told {told!r} | ack {ack!r}")
    if not entry or entry["call"] != "TA1ABC-7" or entry["target"] != AMA_CHAT or "TA1ABC-7" not in told:
        p.append(f"2: link {entry}, told {told!r}")
    code2 = links.request("telegram", "TA5QQ", "999")
    bl._clock = lambda: time.time() + bl.CODE_TTL_S + 5
    radio(ext, "TA5QQ", f"LINK {code2}")
    bl._clock = time.time
    if links.by_call("telegram", "TA5QQ"):
        p.append("2: an expired code linked")

    q.sent.clear()
    tg_msg(ext, AMA_CHAT, "TA2XYZ-9 merhaba")
    print(f"  3 own     -> {q.sent}")
    if len(q.sent) != 1 or not q.sent[0].startswith("TA1ABC-7>") or ":merhaba{" not in q.sent[0]:
        p.append(f"3 own: {q.sent}")
    ext_gw, q_gw = bridge(links, "gateway")
    tg_msg(ext_gw, AMA_CHAT, "TA2XYZ-9 merhaba")
    print(f"  3 gateway -> {q_gw.sent}")
    if len(q_gw.sent) != 1 or not q_gw.sent[0].startswith("TGSEND>") or ":TA1ABC-7: merhaba{" not in q_gw.sent[0]:
        p.append(f"3 gateway: {q_gw.sent}")

    q.sent.clear()
    n = len(sent_tg)
    tg_msg(ext, STRANGER, "TA2XYZ-9 hi")
    print(f"  4 stranger -> on air {q.sent}, told {[t[:30] for c, t in sent_tg[n:]]}")
    if q.sent or not any(c == STRANGER and "/bagla" in t for c, t in sent_tg[n:]):
        p.append(f"4: stranger on air {q.sent}")

    n = len(sent_tg)
    radio(ext, "TA2XYZ-9", "TA1ABC selam nasilsin")
    got = sent_tg[n:]
    print(f"  5 radio -> linked chat: {got}")
    if not got or got[-1][0] != AMA_CHAT or "TA2XYZ-9: selam nasilsin" not in got[-1][1]:
        p.append(f"5: {got}")

    q.sent.clear()
    n = len(sent_tg)
    tg_msg(ext, OP_CHAT, "TA2XYZ-9 from the operator")
    radio(ext, "TA3HX-7", "a note to myself")
    print(f"  6 operator -> on air {q.sent}, telegram {sent_tg[n:]}")
    if len(q.sent) != 1 or not q.sent[0].startswith("TA3HX-6>") \
            or not any(c == OP_CHAT and "a note to myself" in t for c, t in sent_tg[n:]):
        p.append(f"6: {q.sent} {sent_tg[n:]}")

    links2 = bl.BridgeLinks(path)
    print(f"  9 reloaded -> {links2.by_call('telegram', 'TA1ABC')}")
    if not links2.by_call("telegram", "TA1ABC"):
        p.append("9: link lost on reload")

    q.sent.clear()
    for i in range(getattr(tg, "_LINKED_PER_HOUR", 20) + 3):
        tg_msg(ext, AMA_CHAT, f"TA2XYZ-9 n{i}")
    print(f"  8 rate -> {len(q.sent)} on air of {getattr(tg, '_LINKED_PER_HOUR', 20) + 3}")
    if len(q.sent) > getattr(tg, "_LINKED_PER_HOUR", 20):
        p.append(f"8: {len(q.sent)} sent past the hourly limit")

    tg_msg(ext, AMA_CHAT, "/coz")
    getattr(ext, "_sent_at", {}).clear()
    q.sent.clear()
    tg_msg(ext, AMA_CHAT, "TA2XYZ-9 after unlink")
    print(f"  7 after /coz -> link {links.by_call('telegram', 'TA1ABC')}, on air {q.sent}")
    if links.by_call("telegram", "TA1ABC") or q.sent:
        p.append(f"7: {q.sent}")

    default = config.DEFAULTS["extensions"]["telegram"].get("allow_links")
    gated = 'cfg.get("allow_links")' in (Path(__file__).resolve().parent.parent
                                         / "web_gui.py").read_text(encoding="utf-8")
    off, q_off = bridge(None)
    tg_msg(off, STRANGER, "/bagla TA7AAA")
    tg_msg(off, STRANGER, "TA2XYZ-9 hi")
    print(f" 10 off by default -> allow_links={default!r}, gated in web_gui={gated}, on air {q_off.sent}")
    if default is not False or not gated or q_off.sent:
        p.append(f"10: allow_links default {default!r}, gated {gated}, on air {q_off.sent}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
