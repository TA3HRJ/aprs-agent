#!/usr/bin/env python3
"""Fail if the SMTP extension can start unconfigured without saying so, or if
the display name in `from_email` can decide whether mail is sent at all.

Found on the live VPS 2026-09-24. The extension had been enabled since July
with `smtp_server = "smtp.example.com:587"`, the template's value. It started,
logged "SMTP initialized", was reported active by /api/info, and could not
have sent a single message. Nothing anywhere said so.

Correcting the server exposed the second fault. `from_email` held

    Erhan Ozkan, TA3HRJ <ta3hrj@gmail.com>

and the same string was handed to `sendmail()` as the envelope sender. The
unquoted comma makes it two mailboxes, so smtplib sent

    MAIL FROM:<Erhan Ozkan, TA3HRJ <ta3hrj@gmail.com>>

which no server accepts, and the From header parsed as two senders. A cosmetic
field decided whether any mail could leave.

What must hold:

  sender
    1. the envelope sender is a bare address even when from_email is the
       broken string above, and the From header is exactly one mailbox
    2. a well-formed from_email keeps its display name and gives its address
       as the envelope sender
    3. web_gui's monitor notification builds its sender the same way, not
       from the raw string

  startup
    4. an extension configured with the template's placeholder values says
       so as an error and reports its health as error
    5. a real configuration draws no such line and stays healthy

Usage:  python tools/check_smtp_sender.py
Exit code 1 on failure.
"""
from __future__ import annotations

import sys
from email.utils import getaddresses
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import extensions  # noqa: E402
import extensions.smtp_ext as sm  # noqa: E402

FAIL = 0


def fail(label: str, why: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  FAIL  {label}: {why}")


def ok(label: str) -> None:
    print(f"  ok    {label}")


LINES: list[str] = []
extensions.Extension._emit = staticmethod(LINES.append)

BASE = {"enabled": True, "smtp_server": "smtp.gmail.com:587",
        "smtp_username": "op@gmail.com", "smtp_password": "x",
        "allowed_senders": ["N0CALL"], "allowed_recipients": ["EMAIL"],
        "allowed_receiver_emails": []}


class _FakeSMTP:
    sent: list = []

    def __init__(self, host, port, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def sendmail(self, frm, to, body):
        _FakeSMTP.sent.append((frm, to, body))


def send(from_email: str):
    """Send one message through the real code path; return (envelope, From)."""
    _FakeSMTP.sent.clear()
    real = sm.smtplib.SMTP
    sm.smtplib.SMTP = _FakeSMTP
    try:
        ext = sm.SmtpEmailer(dict(BASE, from_email=from_email))
        ext._send_email("dest@example.net", "hello", "N0CALL",
                        dict(BASE, from_email=from_email))
    finally:
        sm.smtplib.SMTP = real
    if not _FakeSMTP.sent:
        return None, None
    frm, _to, body = _FakeSMTP.sent[0]
    header = next((ln[6:] for ln in body.splitlines()
                   if ln.startswith("From: ")), "")
    return frm, header


# ── 1 ──
env, header = send("Erhan Ozkan, TA3HRJ <ta3hrj@gmail.com>")
mailboxes = getaddresses([header]) if header else []
if env is None:
    fail("1 broken name", "nothing was sent")
elif "<" in env or "," in env or "@" not in env:
    fail("1 broken name", f"envelope sender {env!r} is not an address")
elif len(mailboxes) != 1:
    fail("1 broken name", f"From header {header!r} is {len(mailboxes)} "
                          f"mailboxes")
else:
    ok(f"1 broken name: envelope {env}, From one mailbox ({header})")

# ── 2 ──
env, header = send('"Erhan Ozkan, TA3HX" <ta3hrj@gmail.com>')
mailboxes = getaddresses([header]) if header else []
if env != "ta3hrj@gmail.com":
    fail("2 good name", f"envelope sender {env!r}")
elif mailboxes != [("Erhan Ozkan, TA3HX", "ta3hrj@gmail.com")]:
    fail("2 good name", f"From header {header!r} parses as {mailboxes}")
else:
    ok("2 good name kept, envelope is its address")

# ── 3 ──
src = (ROOT / "web_gui.py").read_text(encoding="utf-8")
branch = src[src.find('elif channel == "smtp":'):]
branch = branch[:branch.find("await loop.run_in_executor(None, _send)")]
if not branch:
    fail("3 monitor", "could not find the smtp notification branch")
elif "sender_addresses" not in branch:
    fail("3 monitor", "the notification branch builds its sender from the "
                      "raw from_email string")
else:
    ok("3 monitor notification uses sender_addresses")

# ── 4 ──
del LINES[:]
ext = sm.SmtpEmailer(dict(BASE, smtp_server="smtp.example.com:587",
                          smtp_username="your@email.com",
                          from_email="APRS-Agent <aprs@example.com>"))
said = [ln for ln in LINES if "template" in ln.lower()]
state = ext.health["state"]
if not said:
    fail("4 placeholder", f"nothing said about the template values: {LINES}")
elif state != "error":
    fail("4 placeholder", f"health is {state!r}")
else:
    ok(f"4 placeholder values reported, health {state}")

# ── 5 ──
del LINES[:]
ext = sm.SmtpEmailer(dict(BASE, from_email='"Op" <op@gmail.com>'))
said = [ln for ln in LINES if "template" in ln.lower()]
if said or ext.health["state"] == "error":
    fail("5 real config", f"flagged: {said}, health {ext.health['state']}")
else:
    ok("5 real configuration is not flagged")


print()
print("FAIL" if FAIL else "PASS", f"— {FAIL} problem(s)")
sys.exit(1 if FAIL else 0)
