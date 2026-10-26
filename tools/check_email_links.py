#!/usr/bin/env python3
"""Fail if the e-mail bridge mails anyone who has not linked their address
from the radio, mails person-to-person traffic through the operator's own
account, or can be made to send code mails without limit.

Person to person between licensed amateurs (NEXT 24, KEGM Yön. Md.23/1-c,
1-f, 1-g): an address is linked to a callsign by a code mailed to it and sent
back from that callsign's radio. Then anyone may send "CALL text" to the
alias and it is mailed to CALL's address, naming the sender.

What must hold (SMTP and APRS-IS replaced, no network):

  1. "LINK addr" from a radio mails a code to addr through the links
     transport (localhost, no login, links_from_email) and links nothing;
     the APRS reply masks the address - the air is public
  2. "LINK <code>" from another callsign links nothing; from the same base
     callsign it links the address to the radio's full callsign, says so,
     and mails a confirmation; an expired code links nothing
  3. any station's "CALL text" is mailed to CALL's linked address, through
     the links transport, the body naming the sender
  4. a non-operator's "addr text" mails nothing: only linked amateurs are
     reachable
  5. the operator's "addr text" goes through the operator's account, as before
  6. code mails are limited: one live request per callsign, three per
     address a day
  7. UNLINK removes the link; after it nothing is mailed to that callsign
  8. a linked station's own text goes to its own address
  9. off unless the operator opens it (allow_links, default false); without
     it "LINK addr" mails nothing
 10. a sender's person-to-person mails are held to the hourly limit

Usage:  python tools/check_email_links.py
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
import extensions.smtp_ext as sx  # noqa: E402
import extensions.bridge_links as bl  # noqa: E402

MAILS: list = []


class FakeSMTP:
    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.login_user, self.tls = host, int(port), None, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def has_extn(self, name):
        return True

    def starttls(self):
        self.tls = True

    def login(self, user, password):
        self.login_user = user

    def _record(self, from_addr, to, body_text):
        MAILS.append({"host": self.host, "port": self.port, "login": self.login_user,
                      "from": from_addr, "to": list(to), "text": body_text})

    def send_message(self, msg, from_addr=None, to_addrs=None):
        self._record(from_addr, to_addrs, str(msg["Subject"]) + "\n" + msg.get_content())

    def sendmail(self, from_addr, to_addrs, text):
        self._record(from_addr, to_addrs, text)


sx.smtplib.SMTP = FakeSMTP


class Q:
    def __init__(self):
        self.sent = []

    async def put(self, b: bytes) -> None:
        self.sent.append(b.decode("utf-8").strip())


CFG = {"enabled": True, "smtp_server": "smtp.gmail.com:587", "smtp_username": "op@gmail.com",
       "smtp_password": "x", "allowed_senders": ["TA3HX"], "allowed_recipients": ["EMAIL"],
       "allowed_receiver_emails": [], "from_email": "Operator <op@gmail.com>",
       "allow_links": True, "links_smtp_server": "localhost:25",
       "links_from_email": "APRS-Agent <noreply@aprsagent.com>"}


def bridge(links):
    ext = sx.SmtpEmailer(dict(CFG))
    getattr(ext, "set_links", lambda _l: None)(links)
    q = Q()
    ext.set_own_writer(q)
    ext.log = ext.warn = ext.error = lambda m: None
    return ext, q


def radio(ext, sender, text, msgno="1"):
    return asyncio.run(ext.handle(f"{sender}>APK005,TCPIP*,qAC,T2TEST::EMAIL    :{text}{{{msgno}"))


def code_in(mail) -> str:
    for w in mail["text"].replace("\n", " ").split():
        if w.isdigit() and len(w) == 6:
            return w
    return ""


def main() -> int:
    p = []
    links = bl.BridgeLinks(Path(tempfile.mkdtemp()) / "bridge_links.json")
    ext, q = bridge(links)

    # 1
    MAILS.clear()
    radio(ext, "TA1ABC-7", "LINK ta1abc@example.org")
    m = MAILS[-1] if MAILS else {}
    code = code_in(m) if m else ""
    print(f"  1 LINK addr -> mail {m.get('to')} via {m.get('host')} login={m.get('login')} "
          f"from={m.get('from')} code={code!r} | air {q.sent}")
    if not m or m["to"] != ["ta1abc@example.org"] or m["host"] != "localhost" or m["login"] \
            or m["from"] != "noreply@aprsagent.com" or not code:
        p.append(f"1: code mail {m}")
    if links.by_call("email", "TA1ABC"):
        p.append("1: linked before the code came back")
    if any("ta1abc@example.org" in s for s in q.sent) or not any("t***@example.org" in s for s in q.sent):
        p.append(f"1: the reply on air: {q.sent}")

    # 2
    radio(ext, "TA9XYZ-7", f"LINK {code}")
    if links.by_call("email", "TA1ABC"):
        p.append("2: another callsign's radio linked the address")
    MAILS.clear()
    radio(ext, "TA1ABC-7", f"LINK {code}")
    e = links.by_call("email", "TA1ABC")
    print(f"  2 LINK code -> {e} | confirmation to {[x['to'] for x in MAILS]}")
    if not e or e["call"] != "TA1ABC-7" or e["target"] != "ta1abc@example.org" \
            or not MAILS or MAILS[-1]["to"] != ["ta1abc@example.org"]:
        p.append(f"2: link {e}, mails {MAILS}")
    code2 = links.request("email", "TA5QQ", "qq@example.org")
    bl._clock = lambda: time.time() + bl.CODE_TTL_S + 5
    radio(ext, "TA5QQ", f"LINK {code2}")
    bl._clock = time.time
    if links.by_call("email", "TA5QQ"):
        p.append("2: an expired code linked")

    # 3
    MAILS.clear()
    radio(ext, "TA2XYZ-9", "TA1ABC merhaba nasilsin")
    m = MAILS[-1] if MAILS else {}
    print(f"  3 TA2XYZ-9 -> TA1ABC: to {m.get('to')} via {m.get('host')} login={m.get('login')}")
    if not m or m["to"] != ["ta1abc@example.org"] or m["host"] != "localhost" or m["login"] \
            or "merhaba nasilsin" not in m["text"] or "TA2XYZ-9" not in m["text"]:
        p.append(f"3: {m}")

    # 4
    MAILS.clear()
    radio(ext, "TA2XYZ-9", "someone@example.net hello")
    print(f"  4 stranger to an address -> mails {len(MAILS)}")
    if MAILS:
        p.append(f"4: a non-operator mailed an arbitrary address: {MAILS}")

    # 5
    MAILS.clear()
    radio(ext, "TA3HX-7", "friend@example.net hello from the operator")
    m = MAILS[-1] if MAILS else {}
    print(f"  5 operator -> via {m.get('host')} login={m.get('login')}")
    if not m or m["host"] != "smtp.gmail.com" or m["login"] != "op@gmail.com" \
            or m["to"] != ["friend@example.net"]:
        p.append(f"5: {m}")

    # 6
    MAILS.clear()
    radio(ext, "TA4AA", "LINK aa@example.org")
    radio(ext, "TA4AA", "LINK aa2@example.org")
    n_call = len(MAILS)
    for c in ("TA4BB", "TA4CC", "TA4DD", "TA4EE"):
        radio(ext, c, "LINK same@example.org")
    n_addr = sum(1 for x in MAILS if x["to"] == ["same@example.org"])
    print(f"  6 limits -> one callsign twice: {n_call} mail(s); one address x4: {n_addr}")
    if n_call != 1 or n_addr > getattr(sx, "_CODE_ADDR_PER_DAY", 3):
        p.append(f"6: {n_call} per call, {n_addr} per address")

    # 8
    MAILS.clear()
    radio(ext, "TA1ABC-7", "a note to myself")
    m = MAILS[-1] if MAILS else {}
    print(f"  8 own text -> {m.get('to')}")
    if not m or m["to"] != ["ta1abc@example.org"] or "a note to myself" not in m["text"]:
        p.append(f"8: {m}")

    # 10
    MAILS.clear()
    limit = getattr(sx, "_LINKED_PER_HOUR", 20)
    for i in range(limit + 3):
        radio(ext, "TA6RR", f"TA1ABC n{i}", str(100 + i))
    print(f"  10 rate -> {len(MAILS)} mailed of {limit + 3}")
    if len(MAILS) > limit:
        p.append(f"10: {len(MAILS)} past the hourly limit")

    # 7
    radio(ext, "TA1ABC-7", "UNLINK")
    MAILS.clear()
    radio(ext, "TA2XYZ-9", "TA1ABC after unlink")
    print(f"  7 after UNLINK -> link {links.by_call('email', 'TA1ABC')}, mails {len(MAILS)}")
    if links.by_call("email", "TA1ABC") or MAILS:
        p.append(f"7: {MAILS}")

    # 9
    default = config.DEFAULTS["extensions"]["smtp"].get("allow_links")
    src = (Path(__file__).resolve().parent.parent / "web_gui.py").read_text(encoding="utf-8")
    tail = src.split("elif cls is SmtpEmailer:", 1)[1][:400] if "elif cls is SmtpEmailer:" in src else ""
    gated = 'cfg.get("allow_links")' in tail
    off, _ = bridge(None)
    MAILS.clear()
    radio(off, "TA7AA", "LINK aa7@example.org")
    print(f"  9 off by default -> allow_links={default!r}, gated in web_gui={gated}, mails {len(MAILS)}")
    if default is not False or not gated or MAILS:
        p.append(f"9: default {default!r}, gated {gated}, mails {MAILS}")

    if p:
        print("\nFAIL")
        for x in p:
            print("  - " + x)
        return 1
    print("\nall clear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
