#!/usr/bin/env python3
"""Fail if a bridge carries an ack or rej on as if it were a message.

A radio acks every numbered message it receives. aprslib parses `:EMAIL
:ack2` as format "message" with response "ack" and no message_text, and
every bridge checked only the format. Live on 2026-10-27 the Anytone's ack
of the EMAIL alias's link-code reply reached the e-mail bridge, which logged
it as a malformed operator message. For a linked amateur the same ack fell
through to "mail to your own address" and sent an empty mail - one for
every reply the alias sent - and on Telegram the ack of each message the bot
put on air went back to the chat as an empty message. What must hold (no
network):

  1. an ack or rej to the e-mail alias, from the operator and from a linked
     amateur, sends no mail, no reply and no ack
  2. the same to the Telegram alias and to its from_callsign sends nothing
     to any chat
  3. the same to the Bluesky, Twitter and WhatsApp aliases posts nothing
  4. a real message still goes through each of them (the guard is not a
     wall)

Usage:  python tools/check_bridge_acks.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.bridge_links as bl  # noqa: E402
import extensions.telegram_ext as tgm  # noqa: E402
from extensions.bluesky_ext import Bluesky  # noqa: E402
from extensions.smtp_ext import SmtpEmailer  # noqa: E402
from extensions.whatsapp_ext import WhatsApp  # noqa: E402

# The module imports without tweepy and the class refuses to start (v3.2.143),
# so the import alone cannot tell; CI has no tweepy
import extensions.twitter_ext as twm  # noqa: E402
Twitter = twm.Twitter if twm.tweepy is not None else None


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def quiet(ext):
    ext.log = ext.warn = ext.error = lambda m: None
    return ext


ACKS = ("ack2", "rej3", "ack17")


async def run() -> list:
    p = []
    tmp = Path(tempfile.mkdtemp(prefix="acks-"))

    # 1 - the e-mail bridge
    links = bl.BridgeLinks(tmp / "links.json")
    links.confirm("email", "TA1ABC-7", links.request("email", "TA1ABC-7", "a@b.com"))
    sm = quiet(SmtpEmailer({"enabled": True, "smtp_server": "x:1", "smtp_username": "u",
                            "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"],
                            "links_from_email": "A <noreply@aprsagent.com>"}))
    sm.set_links(links)
    q = Q()
    sm.set_own_writer(q)
    mails = []

    async def mail_linked(*a, **k):
        mails.append(a)
        return True

    sm._mail_linked = mail_linked
    sm._send_email = lambda *a, **k: mails.append(a) or True
    returned = []
    for frm in ("TA3HX-7", "TA1ABC-7"):
        for a in ACKS:
            r = await sm.handle(f"{frm}>APAT89,WIDE1-1,qAR,YM3KC-8::EMAIL    :{a}")
            if r:
                returned.append(r)
    print(f"  1 e-mail: {len(mails)} mails, {len(q.sent)} replies, {len(returned)} acks")
    if mails or q.sent or returned:
        p.append(f"1: an ack to EMAIL sent {len(mails)} mails, {len(q.sent)} replies, "
                 f"{len(returned)} acks")
    await sm.handle("TA1ABC-7>APAT89,WIDE1-1,qAR,YM3KC-8::EMAIL    :hello me{5")
    if len(mails) != 1:
        p.append(f"4: a linked amateur's real message made {len(mails)} mails, wanted 1")

    # 2 - Telegram
    sent_tg = []
    orig = tgm._tg_api

    def fake_api(token, method, params=None, timeout=None):
        if method == "sendMessage":
            sent_tg.append(params)
        return {"ok": True, "result": []}

    tgm._tg_api = fake_api
    try:
        links2 = bl.BridgeLinks(tmp / "links2.json")
        tg = quiet(tgm.Telegram({"enabled": True, "bot_token": "stub", "chat_id": "42",
                                 "poll_enabled": True, "from_callsign": "TA3HX-6",
                                 "allowed_recepients": ["TGSEND"], "allowed_senders": ["TA3HX"]}))
        tg.set_links(links2)
        code = links2.request("telegram", "TA1ABC", "777")
        links2.confirm("telegram", "TA1ABC-7", code)
        tg._queue = Q()
        returned = []
        for frm in ("TA3HX-7", "TA1ABC-7"):
            for to in ("TGSEND   ", "TA3HX-6  "):
                for a in ACKS:
                    r = await tg.handle(f"{frm}>APAT89,WIDE1-1,qAR,YM3KC-8::{to}:{a}")
                    if r:
                        returned.append(r)
        print(f"  2 Telegram: {len(sent_tg)} chat messages, {len(returned)} acks")
        if sent_tg or returned:
            p.append(f"2: an ack to the Telegram alias sent {len(sent_tg)} chat messages, "
                     f"{len(returned)} acks")
        await tg.handle("TA1ABC-7>APAT89,WIDE1-1,qAR,YM3KC-8::TA3HX-6  :hello me{6")
        if len(sent_tg) != 1:
            p.append(f"4: a linked amateur's real message made {len(sent_tg)} chat messages")
    finally:
        tgm._tg_api = orig

    # 3 - the posting bridges, operator only
    posts = []

    async def post(*a, **k):
        posts.append(a)

    common = {"allowed_senders": ["TA3HX"], "add_hash_tag": False}
    bridges = []
    bs = quiet(Bluesky({**common, "username": "u", "app_password": "x",
                        "allowed_recepients": ["BSKYSEND"]}))
    bs._send_post = post
    bridges.append(("Bluesky", bs, "BSKYSEND "))
    wa = quiet(WhatsApp({**common, "phone_number_id": "1", "access_token": "x",
                         "recipient_phone": "1", "allowed_recepients": ["WASEND"]}))
    wa._send_wa = post
    bridges.append(("WhatsApp", wa, "WASEND   "))
    if Twitter is not None:
        tw = quiet(Twitter({**common, "api_key": "a", "api_secret": "b",
                            "access_token_key": "c", "access_token_secret": "d",
                            "allowed_recepients": ["TWSEND"]}))
        tw._send_tweet = post
        bridges.append(("Twitter", tw, "TWSEND   "))
    else:
        print("  3 Twitter skipped: tweepy not installed")
    for name, ext, to in bridges:
        before = len(posts)
        returned = []
        for a in ACKS:
            r = await ext.handle(f"TA3HX-7>APAT89,WIDE1-1,qAR,YM3KC-8::{to}:{a}")
            if r:
                returned.append(r)
        n = len(posts) - before
        print(f"  3 {name}: {n} posts, {len(returned)} acks")
        if n or returned:
            p.append(f"3: an ack to {name} made {n} posts, {len(returned)} acks")
        await ext.handle(f"TA3HX-7>APAT89,WIDE1-1,qAR,YM3KC-8::{to}:hello{{7")
        if len(posts) != before + n + 1:
            p.append(f"4: a real message to {name} was not posted")
    return p


def main() -> int:
    p = asyncio.run(run())
    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
