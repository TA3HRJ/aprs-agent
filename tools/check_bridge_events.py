#!/usr/bin/env python3
"""Fail if the bridges' person-to-person traffic, and above all what they
refuse, is not counted per day where the operator can see it.

v3.2.199 opened port 25: anyone on the internet can now hand this server
mail, and the bot and the EMAIL alias were already open to anyone. Abuse
until now showed only as journal lines nobody counts. What must hold (no
network):

  1. inbound mail: refused for no DMARC pass, an unlinked address, a
     recipient that is not a callsign, over the hourly limit - each counted
     under its own name; mail put on air counted as mail_in
  2. the e-mail bridge: code mails sent and refused (bad address, asked
     again, over the limits), unknown codes, links made, mails out and the
     hourly limit, each counted
  3. Telegram: chats that are neither the operator's nor linked, codes
     given and refused, unknown codes from the radio, links made, linked
     messages on air and the hourly limit, each counted
  4. the manager keeps the counts per UTC day for 60 days in meta
     bridge_events, survives a restart, and sums the last 30 days
  5. /api/counters carries bridge_events, and the web GUI hands the counter
     to all three bridges
  6. counting never carries who: no address, chat id or callsign in a name
  7. what the MTA refused at the door (`mta_log`, its reject lines) is
     counted by reason: unknown recipient, relay, dropped connection ...;
     the first read does not count the past, a half-written line waits,
     and a rotated log is read from its start

Usage:  python tools/check_bridge_events.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import tempfile
import time
import types
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import extensions.bridge_links as bl  # noqa: E402
import extensions.telegram_ext as tgm  # noqa: E402
from extensions.imap_ext import ImapReceiver  # noqa: E402
from extensions.smtp_ext import SmtpEmailer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTHSERV = "mx.test"
ADDR = "op@gmail.com"


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def quiet(ext):
    ext.log = ext.warn = ext.error = lambda m: None
    return ext


def recorder(ext):
    got = Counter()
    getattr(ext, "set_event_recorder", lambda fn: None)(lambda e: got.update([e]))
    return got


def mail(frm=ADDR, to="ta1abc-7@aprsagent.com", dmarc="pass", body="hello\n"):
    ar = f"Authentication-Results: {AUTHSERV}; dmarc={dmarc} header.from={frm.split('@')[1]}\n"
    return (f"Delivered-To: {to}\n{ar}From: <{frm}>\nTo: {to}\nSubject: x\n"
            f"Content-Type: text/plain\n\n{body}").encode()


async def run() -> list:
    p = []
    tmp = Path(tempfile.mkdtemp(prefix="events-"))
    links = bl.BridgeLinks(tmp / "bridge_links.json")
    links.confirm("email", "TA3HX-7", links.request("email", "TA3HX-7", ADDR))

    # 1 - inbound mail
    md = tmp / "Maildir"
    for d in ("new", "cur", "tmp"):
        (md / d).mkdir(parents=True, exist_ok=True)
    try:
        im = quiet(ImapReceiver({"enabled": True, "from_callsign": "EMAIL-5", "allow_links": True,
                                 "maildir": str(md), "mail_domain": "aprsagent.com",
                                 "auth_serv_id": AUTHSERV}))
    except Exception as e:
        im = None
        p.append(f"1: no maildir receiver: {e}")
    if im is not None:
        im.set_links(links)
        im._queue = Q()
        got = recorder(im)
        raws = [mail(dmarc="fail"), mail(frm="x@gmail.com"), mail(to="noreply@aprsagent.com")]
        raws += [mail(body=f"m{i}\n") for i in range(21)]
        for i, raw in enumerate(raws):
            (md / "new" / f"{i}.M1.host").write_bytes(raw)
        await im._check_maildir()
        print(f"  1 inbound -> {dict(got)}")
        want = {"mail_in_unauthenticated": 1, "mail_in_unlinked": 1,
                "mail_in_bad_recipient": 1, "mail_in_rate": 1, "mail_in": 20}
        for k, v in want.items():
            if got.get(k) != v:
                p.append(f"1: {k} = {got.get(k)}, wanted {v}")

    # 2 - the e-mail bridge
    sm = quiet(SmtpEmailer({"enabled": True, "smtp_server": "x:1", "smtp_username": "u",
                            "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"],
                            "links_from_email": "A <noreply@aprsagent.com>"}))
    links2 = bl.BridgeLinks(tmp / "links2.json")
    sm.set_links(links2)
    sm.set_own_writer(Q())
    sm._send_links_mail = lambda *a, **k: True
    got = recorder(sm)
    n = [0]

    async def radio(frm, text):
        n[0] += 1
        await sm.handle(f"{frm}>APDR16,TCPIP*,qAC,T2X::EMAIL    :{text}{{{n[0]}")

    await radio("TA1ABC-7", "LINK a@b")
    await radio("TA1ABC-7", "LINK a@b.com")
    await radio("TA1ABC-7", "LINK a@b.com")
    for i in range(4):
        await radio(f"TA{i}XX", "LINK same@b.com")
    await radio("TA1ABC-7", "LINK 000000")
    code = links2.request("email", "TA5QQ", "q@b.com")
    await radio("TA5QQ", f"LINK {code}")
    for i in range(21):
        await radio("TA2ZZ-1", f"TA5QQ hi {i}")
    print(f"  2 e-mail  -> {dict(got)}")
    want = {"mail_code_refused": 2, "mail_code": 4, "mail_code_limit": 1,
            "mail_bad_code": 1, "mail_linked": 1, "mail_out": 20, "mail_out_rate": 1}
    for k, v in want.items():
        if got.get(k) != v:
            p.append(f"2: {k} = {got.get(k)}, wanted {v}")

    # 3 - Telegram
    updates: list = []

    def fake_api(token, method, params=None, timeout=None):
        if method == "getUpdates":
            out = list(updates)
            updates.clear()
            return {"ok": True, "result": out}
        return {"ok": True}

    orig = tgm._tg_api
    tgm._tg_api = fake_api
    try:
        links3 = bl.BridgeLinks(tmp / "links3.json")
        tg = quiet(tgm.Telegram({"enabled": True, "bot_token": "stub", "chat_id": "42",
                                 "poll_enabled": True, "from_callsign": "TA3HX-6",
                                 "allowed_recepients": ["TGSEND"], "allowed_senders": ["TA3HX"]}))
        tg.set_links(links3)
        tg._queue = Q()
        got = recorder(tg)

        async def chat(cid, text):
            updates.append({"update_id": len(updates) + int(time.time() * 1000) % 10 ** 9,
                            "message": {"chat": {"id": int(cid)}, "from": {"first_name": "x"},
                                        "text": text}})
            await tg._check_updates()

        async def tg_radio(frm, text):
            n[0] += 1
            await tg.handle(f"{frm}>APDR16,TCPIP*,qAC,T2X::TGSEND   :{text}{{{n[0]}")

        await chat(888, "hello")
        await chat(777, "/bagla nonsense")
        await chat(777, "/bagla TA1ABC")
        code = links3._pending and next(iter(links3._pending))
        await tg_radio("TA1ABC-7", "LINK 000000")
        await tg_radio("TA1ABC-7", f"LINK {code}")
        for i in range(21):
            await chat(777, f"TA2XYZ-9 hi {i}")
    finally:
        tgm._tg_api = orig
    print(f"  3 Telegram -> {dict(got)}")
    want = {"tg_ignored": 1, "tg_code_refused": 1, "tg_code": 1, "tg_bad_code": 1,
            "tg_linked": 1, "tg_on_air": 20, "tg_rate": 1}
    for k, v in want.items():
        if got.get(k) != v:
            p.append(f"3: {k} = {got.get(k)}, wanted {v}")

    # 4 - the manager
    import station_db
    import web_gui
    db_path = str(tmp / "aprs_stations.db")
    mgr = types.SimpleNamespace(_bridge_events={}, _sta_db_path=db_path,
                                _bridge_saved_at=0.0, _bridge_save_due=False)
    rec = getattr(web_gui.AgentManager, "_record_bridge_event", None)
    summ = getattr(web_gui.AgentManager, "_bridge_summary", None)
    if rec and summ:
        mgr._save_bridge_events = lambda: web_gui.AgentManager._save_bridge_events(mgr)
        for e in ("mail_in_unlinked", "mail_in_unlinked", "tg_ignored"):
            rec(mgr, e)
        old = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 40 * 86400))
        mgr._bridge_events[old] = {"tg_ignored": 99}
        web_gui.AgentManager._save_bridge_events(mgr)
        s = summ(mgr, 30)
        stored = json.loads(station_db.load_meta(db_path, "bridge_events", "{}"))
        print(f"  4 summary {s} | stored days {sorted(stored)}")
        if s.get("events") != {"mail_in_unlinked": 2, "tg_ignored": 1}:
            p.append(f"4: summary {s}")
        today = time.strftime("%Y-%m-%d", time.gmtime())
        if stored.get(today) != {"mail_in_unlinked": 2, "tg_ignored": 1}:
            p.append(f"4: stored {stored}")
        mgr._bridge_events = {f"2026-01-{d:02d}": {"x": 1} for d in range(1, 31)}
        mgr._bridge_events.update({f"2026-02-{d:02d}": {"x": 1} for d in range(1, 29)})
        mgr._bridge_events.update({f"2026-03-{d:02d}": {"x": 1} for d in range(1, 11)})
        rec(mgr, "x")
        if len(mgr._bridge_events) > 60:
            p.append(f"4: {len(mgr._bridge_events)} days kept, wanted 60")
    else:
        p.append("4: the manager has no bridge event counts")

    # 5 - wiring
    src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    hooked = src.count("ext.set_event_recorder(self._record_bridge_event)")
    api = '"bridge_events": mgr._bridge_summary(30)' in src
    print(f"  5 recorder handed to {hooked} bridges, /api/counters: {api}")
    if hooked != 3:
        p.append(f"5: the recorder reaches {hooked} bridges, wanted 3")
    if not api:
        p.append("5: /api/counters has no bridge_events")

    # 6 - names only
    names = set()
    for part in (ROOT / "extensions").glob("*.py"):
        names |= set(re.findall(r'(?:self\.count|_events\.append)\(\s*f?"([^"]*)"',
                                part.read_text(encoding="utf-8")))
    bad = [x for x in names if "{" in x or "@" in x]
    print(f"  6 event names {sorted(names)}")
    if bad or not names:
        p.append(f"6: event names carry data: {bad or 'none found'}")

    # 7 - the MTA's rejects
    log = tmp / "mta.log"
    old_line = ("Oct 27 07:00:00 h postfix/smtpd[1]: NOQUEUE: reject: RCPT from x[1.2.3.4]: "
                "550 5.1.1 <a@aprsagent.com>: Recipient address rejected: User unknown\n")
    log.write_text(old_line * 5, encoding="utf-8")
    md2 = tmp / "Maildir2"
    for d in ("new", "cur", "tmp"):
        (md2 / d).mkdir(parents=True, exist_ok=True)
    try:
        r = quiet(ImapReceiver({"enabled": True, "from_callsign": "EMAIL-5", "allow_links": True,
                                "maildir": str(md2), "mail_domain": "aprsagent.com",
                                "auth_serv_id": AUTHSERV, "mta_log": str(log)}))
    except Exception as e:
        r = None
        p.append(f"7: {e}")
    if r is not None:
        r._queue = Q()
        got = recorder(r)
        await r._check_maildir()                      # first look: the past is not counted
        first = dict(got)
        with open(log, "a", encoding="utf-8") as f:
            f.write(old_line)
            f.write("Oct 27 07:01:00 h postfix/smtpd[2]: NOQUEUE: reject: RCPT from y[5.6.7.8]: "
                    "454 4.7.1 <t@x.com>: Relay access denied\n")
            f.write("Oct 27 07:02:00 h postfix/smtpd[3]: lost connection after CONNECT from z[9.9.9.9]\n")
            f.write("Oct 27 07:03:00 h postfix/smtpd[4]: NOQUEUE: reject: RCPT from w[1.1.1.1]: 554 5.7.1 half")
        await r._check_maildir()
        second = dict(got)
        with open(log, "a", encoding="utf-8") as f:
            f.write(" written: Client host rejected\n")
        await r._check_maildir()
        third = dict(got)
        log.unlink()                                  # rotated: a new, shorter file
        log.write_text(old_line, encoding="utf-8")
        await r._check_maildir()
        fourth = dict(got)
        print(f"  7 MTA log: first {first} | then {second} | half line done {third} | rotated {fourth}")
        if first:
            p.append(f"7: the first read counted the past: {first}")
        want = {"mta_reject_unknown_recipient": 1, "mta_reject_relay": 1, "mta_dropped_connection": 1}
        if second != want:
            p.append(f"7: {second}, wanted {want}")
        if third.get("mta_reject_client") != 1:
            p.append(f"7: a line finished later was not counted: {third}")
        if fourth.get("mta_reject_unknown_recipient") != 2:
            p.append(f"7: a rotated log was not read from its start: {fourth}")
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
