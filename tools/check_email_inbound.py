#!/usr/bin/env python3
"""Fail if mail reaching this server's own MTA can go on air without a DMARC
pass from a linked address, or under any callsign but the linked one.

v3.2.199 opens the inbound side of the e-mail bridge person to person
(NEXT 24): the server's Postfix takes mail for CALL@mail_domain into a
Maildir, and the IMAP extension reads it. Mail is the easiest thing on the
internet to forge, and what it carries goes on amateur radio under a
callsign (KEGM Yön. Md.23/1-c, 1-f, 1-g).

What must hold (no network, a temporary Maildir):

  1. dmarc=pass from our MTA, from an address linked to TA3HX-7, to
     ta1abc-7@ the mail domain: one message from TA3HX-7 to TA1ABC-7 with
     the first line of the mail; a reply's quote is not sent
  2. dmarc=fail, no Authentication-Results, or one from another MTA: dropped
  3. our header says fail and a forged pass with our id sits below it: dropped
  4. a pass for another domain than the From address: dropped
  5. a pass from an address linked to nobody: dropped
  6. to noreply@, or to a callsign at another domain: dropped
  7. every mail file is gone from the Maildir afterwards, sent or dropped
  8. a linked address gets 20 messages an hour on air, not 21
  9. a reply that is all quote falls back to the subject; "Re: APRS: CALL"
     alone sends nothing
 10. the e-mail bridge's person-to-person mail carries Reply-To
     <sender>@domain and says a reply goes on air - only with a reply domain
 11. the web GUI gives the IMAP extension the links only under allow_links,
     and the e-mail bridge the reply domain only when the inbound side is on
 12. SERVICES names e-mail in as open to linked addresses
 13. a maildir without auth_serv_id or mail_domain does not start
 14. a mail to the sender's own callsign goes out from the bridge's
     callsign, "mail: " opening the text - an igate does not gate a
     message whose sender it heard on RF, and here sender and addressee are
     the same radio (F-2026-10-27-05); to another call it stays the
     linked call's own
 15. the operator's message to EMAIL that is not "address text" is answered
     with the format and acked, not dropped in silence

Usage:  python tools/check_email_inbound.py
Exit code 1 on failure.
"""
from __future__ import annotations

import asyncio
import copy
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extensions.bridge_links import BridgeLinks  # noqa: E402
from extensions.imap_ext import ImapReceiver  # noqa: E402
from extensions.smtp_ext import SmtpEmailer  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTHSERV = "vmi3446495.contaboserver.net"
DOMAIN = "aprsagent.com"
ADDR = "op@gmail.com"


def mail(frm=ADDR, to="ta1abc-7@aprsagent.com", ar=None, body="Hello from mail\n",
         subject="test", extra=""):
    if ar is None:
        ar = [f"{AUTHSERV}; dmarc=pass (p=none dis=none) header.from=gmail.com"]
    hdr = f"Delivered-To: {to}\n" if to else ""
    hdr += "".join(f"Authentication-Results: {a}\n" for a in ar)
    hdr += extra
    return (f"Return-Path: <{frm}>\n{hdr}From: Op <{frm}>\nTo: {to}\n"
            f"Subject: {subject}\nMIME-Version: 1.0\n"
            f"Content-Type: text/plain; charset=utf-8\n\n{body}").encode()


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


def receiver(tmp: Path, links, **over):
    cfg = {"enabled": True, "from_callsign": "EMAIL-5", "allow_links": True,
           "maildir": str(tmp / "Maildir"), "mail_domain": DOMAIN,
           "auth_serv_id": AUTHSERV}
    cfg.update(over)
    for d in ("new", "cur", "tmp"):
        (tmp / "Maildir" / d).mkdir(parents=True, exist_ok=True)
    try:
        r = ImapReceiver(cfg)
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    r.log = r.warn = r.error = lambda m: None
    getattr(r, "set_links", lambda _l: None)(links)
    q = Q()
    r._queue = q
    return (r, q), ""


def drop(tmp: Path, raw: bytes, n=[0]) -> None:
    n[0] += 1
    (tmp / "Maildir" / "new" / f"{n[0]}.M1P1.host").write_bytes(raw)


async def run_case(tmp, links, raw, **over):
    got, err = receiver(tmp, links, **over)
    if not got:
        return None, err
    r, q = got
    drop(tmp, raw)
    check = getattr(r, "_check_maildir", None)
    if check:
        await check()
    return q.sent, ""


def msgs(sent):
    return [s for s in sent if "::" in s]


async def run() -> list:
    p = []
    tmp = Path(tempfile.mkdtemp(prefix="inbound-"))
    links = BridgeLinks(tmp / "bridge_links.json")
    code = links.request("email", "TA3HX-7", ADDR)
    links.confirm("email", "TA3HX-7", code)

    # 1
    sent, err = await run_case(tmp, links, mail(body="Hello from mail\n\nOn Mon, X wrote:\n> old\n"))
    m = msgs(sent or [])
    print(f"  1 linked pass -> {m or err!r}")
    if len(m) != 1 or not re.match(r"^TA3HX-7>APRAGT,TCPIP\*::TA1ABC-7 :Hello from mail\{\d+$", m[0]):
        p.append(f"1: a linked, authenticated mail did not go on air as TA3HX-7: {m or err!r}")

    # 2-6: each must send nothing
    cases = [
        ("2 dmarc=fail", mail(ar=[f"{AUTHSERV}; dmarc=fail header.from=gmail.com"])),
        ("2 no A-R", mail(ar=[])),
        ("2 other MTA", mail(ar=["mx.evil.example; dmarc=pass header.from=gmail.com"])),
        ("3 forged below", mail(ar=[f"{AUTHSERV}; dmarc=fail header.from=gmail.com",
                                   f"{AUTHSERV}; dmarc=pass header.from=gmail.com"])),
        ("4 other domain", mail(ar=[f"{AUTHSERV}; dmarc=pass header.from=evil.example"])),
        ("5 unlinked", mail(frm="stranger@gmail.com")),
        ("6 noreply@", mail(to="noreply@aprsagent.com")),
        ("6 other domain", mail(to="ta1abc-7@example.org")),
    ]
    for label, raw in cases:
        sent, err = await run_case(tmp, links, raw)
        m = msgs(sent or [])
        print(f"  {label:16} -> {m!r}")
        if m:
            p.append(f"{label}: went on air: {m!r}")

    # 7
    left = [f.name for d in ("new", "cur") for f in (tmp / "Maildir" / d).iterdir()]
    print(f"  7 left in the Maildir: {len(left)}")
    if left:
        p.append(f"7: {len(left)} mail file(s) kept")

    # 8
    got, err = receiver(tmp, links)
    if got:
        r, q = got
        for i in range(21):
            drop(tmp, mail(body=f"msg {i}\n"))
        await getattr(r, "_check_maildir", lambda: asyncio.sleep(0))()
        n = len(msgs(q.sent))
        print(f"  8 21 mails in an hour -> {n} on air")
        if n != 20:
            p.append(f"8: {n} of 21 went on air, wanted 20")
    else:
        p.append(f"8: {err}")

    # 9
    sent, _ = await run_case(tmp, links, mail(body="> quoted only\n", subject="Re: APRS: TA1ABC-7 ok then"))
    m = msgs(sent or [])
    print(f"  9 quote, subject   -> {m!r}")
    if len(m) != 1 or ":ok then{" not in m[0]:
        p.append(f"9: subject fallback: {m!r}")
    sent, _ = await run_case(tmp, links, mail(body="> quoted only\n", subject="Re: APRS: TA1ABC-7"))
    print(f"  9 nothing to send  -> {msgs(sent or [])!r}")
    if msgs(sent or []):
        p.append("9: a reply with no text of its own went on air")

    # 10
    for dom in ("aprsagent.com", ""):
        sm = SmtpEmailer({"enabled": True, "smtp_server": "x:1", "smtp_username": "u",
                          "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"],
                          "links_from_email": "APRS-Agent <noreply@aprsagent.com>"})
        sm.log = sm.warn = sm.error = lambda m: None
        sm.set_links(links)
        getattr(sm, "set_reply_domain", lambda d: None)(dom)
        sm.set_own_writer(Q())
        calls = []

        def fake(to_addr, subject, body, reply_to=""):
            calls.append((to_addr, body, reply_to))
            return True

        sm._send_links_mail = fake
        await sm.handle("TA1ABC-7>APDR16,TCPIP*,qAC,T2X::EMAIL    :TA3HX-7 hi there{9")
        to_addr, body, reply_to = calls[-1] if calls else ("", "", "")
        print(f" 10 domain {dom or '-':13} -> Reply-To {reply_to!r}")
        if dom:
            if reply_to != "ta1abc-7@aprsagent.com" or "Reply to this mail" not in body:
                p.append(f"10: with a reply domain: Reply-To {reply_to!r}")
        elif reply_to or "takes no mail" not in body:
            p.append(f"10: without one: Reply-To {reply_to!r}")

    # 11
    src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
    im = src.split("elif cls is ImapReceiver:", 1)
    ok_im = len(im) == 2 and 'cfg.get("allow_links")' in im[1][:400] and "set_links" in im[1][:400]
    sm_part = src.split("elif cls is SmtpEmailer:", 1)[-1][:900]
    ok_sm = "set_reply_domain" in sm_part and 'im.get("allow_links")' in sm_part \
        and 'im.get("maildir")' in sm_part
    print(f" 11 web GUI: imap links gated {ok_im}, reply domain gated {ok_sm}")
    if not ok_im:
        p.append("11: the IMAP extension does not get the links under allow_links")
    if not ok_sm:
        p.append("11: the e-mail bridge's reply domain is not tied to the inbound side")

    # 12
    from extensions.ai_gateway_ext import _services_text
    bridges = {"imap": {"enabled": True, "allow_links": True, "maildir": "/x"},
               "smtp": {"enabled": True, "allowed_recipients": ["EMAIL"],
                        "allowed_senders": ["TA3HX"], "allow_links": True}}
    tr = _services_text(copy.deepcopy(bridges), "TA1ABC", True)
    print(f" 12 SERVIS -> {tr!r}")
    if "e-posta alma (bagli)" not in tr.split("Yalniz")[0].split("Kapal")[0]:
        p.append(f"12: e-mail in is not named as open to linked addresses: {tr!r}")
    # the live server's shape still fits the gateway's three parts, whole
    from extensions.ai_gateway_ext import _split_message
    live = dict(copy.deepcopy(bridges),
                telegram={"enabled": True, "allowed_recepients": ["TGSEND"],
                          "allowed_senders": ["TA3HX"], "allow_links": True},
                bluesky={"enabled": True, "allowed_recepients": ["BSKYSEND"],
                         "allowed_senders": ["TA3HX"]},
                twitter={"enabled": False}, whatsapp={"enabled": False})
    for lang in (True, False):
        parts = _split_message(_services_text(live, "TA1ABC", lang, "APRSAgent_bot"), 3)
        print(f" 12 live shape, {'TR' if lang else 'EN'}: {len(parts)} parts, ends {parts[-1][-12:]!r}")
        if not parts[-1].endswith("WhatsApp."):
            p.append(f"12: the live answer is cut: {parts[-1]!r}")

    # 13
    for over in ({"auth_serv_id": ""}, {"mail_domain": ""}):
        got, err = receiver(tmp, links, **over)
        print(f" 13 maildir without {list(over)[0]} -> {'refused' if not got else 'started'}")
        if got:
            p.append(f"13: started without {list(over)[0]}")

    # 14
    sent, err = await run_case(tmp, links, mail(to="ta3hx-7@aprsagent.com", body="note to self\n"))
    m = msgs(sent or [])
    print(f" 14 to own call -> {m or err!r}")
    if len(m) != 1 or not re.match(r"^EMAIL-5>APRAGT,TCPIP\*::TA3HX-7  :mail: note to self\{\d+$", m[0]):
        p.append(f"14: a mail to the sender's own call did not go out from EMAIL-5: {m or err!r}")

    # 15
    sm = SmtpEmailer({"enabled": True, "smtp_server": "x:1", "smtp_username": "u",
                      "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"]})
    sm.log = sm.warn = sm.error = lambda m: None
    sm.set_links(links)
    q15 = Q()
    sm.set_own_writer(q15)
    sm._send_email = lambda *a, **k: True
    for text, n in (("TEST", 1), ("op@gmail.com", 2)):
        r = await sm.handle(f"TA3HX-7>APAT89,WIDE1-1,qAR,TA3HX-10::EMAIL    :{text}{{{n}")
        print(f" 15 operator {text!r} -> reply {q15.sent[-1:]} ack {r!r}")
        if not r or not q15.sent or "Format" not in q15.sent[-1]:
            p.append(f"15: the operator's {text!r} was not answered and acked")
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
