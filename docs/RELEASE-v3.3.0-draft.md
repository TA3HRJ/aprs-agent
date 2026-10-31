# Release draft — v3.3.0

Built 2026-10-31 the same way as v3.2.198 (`docs/RELEASE-HOWTO.md`): CPython
3.13.15 32-bit (reinstalled from python.org the same day, same patch level),
`git -c core.autocrlf=false archive` export of the tag (161 of 161 files
identical to their blobs), the tag's own pin file (dnspython 2.9.0, pillow
13.0.0, cryptography 48.0.1). `aprs-agent-v3.3.0.zip`, 60.3 MiB, 248 files,
sha256 `2B9ADF92C0E5426EF54E6BC2660B8859201288B36ABC98FFB2623A1B6C2BE8A2`.
Root files identical to the tag; the web executable serves BUILD 3.3.0 and the
bundled Leaflet with its published SRI hashes (smoke-tested on 127.0.0.1); the
CLI runs (`--help`).

Against v3.2.198: 248 files against 248, none added or removed. Changed by
CRC: `HELP.html`, `README.md`, `aprsconfig.toml.template` (root and both
targets), `static/index.html`, both executables and `base_library.zip`.
`LICENSE` unchanged.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

The code is v3.2.207's; v3.3.0 changes only the version. The minor version
marks person-to-person bridges working both ways, as v3.1.0 marked incident
response: the operator's first Telegram and e-mail round trips from a radio
passed on 2026-10-31.

Suggested release name:

> **v3.3.0 — person-to-person bridges, tested on air**

Asset, to match every previous release: `aprs-agent-v3.3.0.zip`

---

## Body

v3.3.0 closes the 3.2 line. Nine releases since v3.2.198; the code is
v3.2.207's.

### Person to person, tested on air

The Telegram and e-mail bridges introduced in v3.2.198 now work both ways
between licensed amateurs, and both were tested end to end from a radio
before this release:

- **Telegram:** `/link CALL` in the bot, `LINK <code>` from the radio; the
  chat's messages go on air under the radio's own callsign, and `CALL text`
  from any radio to the Telegram alias reaches that chat. `UNLINK` from the
  radio or `/unlink` in the chat removes it.
- **E-mail in** (new): a server running its own mail transfer agent can take
  mail for `CALL@your-domain` into a Maildir. A message goes on air only when
  it passes DMARC for its sender's domain and comes from an address linked to
  a callsign; anything else is dropped. Mail sent person to person carries a
  Reply-To at that domain, so replying to it answers on air. Off until
  `imap.allow_links`; see `aprsconfig.toml.template`.
- Mail to one's own callsign goes out from the bridge's callsign as
  "mail: text": an igate does not gate a message whose sender it heard on RF.
- A radio's ack or rej is no longer carried on by any bridge (e-mail,
  Telegram, Bluesky, Twitter, WhatsApp) as an empty mail, post or chat
  message.
- An operator's message to the e-mail alias that is not "address text" is
  answered with the expected format instead of being dropped.

### Seeing what the bridges do

- Each bridge counts what it carries and what it refuses, by reason, per day
  for 60 days; `/api/counters` reports 30 days.
- The admin panel's Messages tab has a "Bridge events" source: per-day
  counts and the last 50 refusals, with addresses and chat ids masked. Not
  served by the public app.
- With `imap.mta_log` set, the mail server's own refusals are counted by
  reason too.
- DMWGPT tells a station when the model gave no answer, at most once in ten
  minutes.

### Reliability

- **The APRS-IS connect has a deadline (30 s)** and tries the next of the
  server name's addresses after 5 s rather than after the last one fails.
  A connect to an unresponsive address could hang for minutes with nothing
  logged.
- **Stations that fall silent while their area is already alerting** now
  reach the "still off the air" list; only those silent when the alert
  opened used to.
- An error reading the station registry no longer empties the "still off
  the air" list.

### Security and correctness

- The web panel's same-origin guard refuses `Origin: null` (what a sandboxed
  frame sends) like any foreign origin. This matters most on a local install,
  where the panel has no login. **Update if you run the web panel on Windows
  or in Docker.**
- dnspython 2.9.0 (GHSA-45c3-73f7-pv4m).
- A propagation link on a young gate is judged against the bar an
  established gate uses, max(3 × mean, mean + 4 sigma), not 3 × mean.
- A monitor e-mail with an `smtp_server` that has no port is refused with a
  clear message.
- One unreadable quake watch no longer stops the others being restored.

### The 3.2 line, in short

From v3.2.0 (2026-08-11) to v3.2.207, with Windows releases along the way:
exportable evidence and a timeline you can aim at (v3.2.0); security
releases (v3.2.3, v3.2.111); silence alerts built on what was measured and
on what the detector can and cannot hear (v3.2.25, v3.2.97, v3.2.165); the
callsign change TA3HRJ → TA3HX (v3.2.116); an AI gateway that holds a
conversation (v3.2.119) and answers STATUS and SERVICES from the server's own
data (v3.2.198); fourteen days of history and a faster, full-screen map
(v3.2.130, v3.2.165); quake rings (v3.2.179); compressed log rotation
(v3.2.180); and the bridges above.

Everything else is as in v3.2.198.
