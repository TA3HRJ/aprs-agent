# Release draft — v3.2.165

The body for the GitHub release. Built 2026-10-08 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). All 124 exported files
matched their blobs in the tag. The artefact is `aprs-agent-v3.2.165.zip`,
59.8 MiB, 248 files, sha256
`9C833A9226C4FC7A7ADEEFF40478A08150F210458B5B8367DDFB46612DE4F965`.
Every shipped file that is in the repository (22) matched the tag byte for
byte, and both executables carry `config.VERSION` 3.2.165.

Against v3.2.130: 248 files in both, none added or removed. 18 differ by CRC:
`HELP.html` (+5,191 bytes, the rules card, three copies), `README.md`
(-3,997, the audit's trim), `static/index.html` (+23,014),
`aprsconfig.toml.template` (+373, `log_compress`, three copies), the multidict
extension (6.7.1 -> 6.9.1, both targets), both executables, and the files
that change on every rebuild at identical size (`base_library.zip`, two
`RECORD`s, both targets). cryptography stays at 48.0.1, the 32-bit ceiling.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.165 — a map that fills the screen, alerts that know when they cannot hear**

Asset, to match every previous release: `aprs-agent-v3.2.165.zip`

---

## Body

Thirty-five releases since v3.2.130. The download catches up with the live
demo again.

### The map

- **Search** by callsign the way aprs.fi does (`TA3HX*` for every SSID, `?`
  for one character) across the whole registry, or by Maidenhead locator
  (`KM`, `KM38`, `KM38nk`), which frames the square and opens its silence
  cell. Every row of the alert list leads to its cell; Messages callsigns
  lead to the station.
- **The world view fills the map.** Zoomed all the way out it used to leave
  dark bands around a small world; the least zoom now follows the size of the
  map.
- **On a phone** the map starts at about a quarter of the screen instead of
  half way down: the caption and the amber status bar are one line until
  tapped, and the stats bar is one row.
- The map follows its own size, so folding the settings column no longer
  leaves a strip without tiles.

### Silence alerts

- An alert must hold for **10 minutes** before it is announced, and an
  episode survives a dip shorter than an hour: about a third fewer alerts,
  most of them flickers.
- Alerts state **when** their stations stopped - the spread, the opening,
  stations that came back - and that stations on UPS, battery or solar stop
  later than the rest after one power cut. The AI note weighs a power cut and
  independent drop-outs equally, and says "unknown" unless the facts agree.
- Stations injected over the internet under another station's login are no
  longer counted as radio witnesses.
- **Time the agent did not listen is never anyone's silence.** If the
  program starts without a network, or the feed breaks, nothing is judged
  while it cannot hear; when the feed returns, stations not heard since are
  judged only after one beacon interval of listening, and the amber bar says
  how many are waiting.
- The still-off-the-air list shows the last 7 days by default, links to the
  map, and can be grouped by square.
- HELP now explains how an alert and an opening are decided, in Turkish and
  English.

### Propagation

- The distance floor is **250 km** (was 300). On the same hours of feed it
  finds about 70 % more openings.
- A link from a station whose position jumped faster than anything moves, or
  from a balloon, is **suspect**: drawn grey and dotted, never counted toward
  an opening or a gate's baseline, and hideable from the legend.

### The AI gateway

- Asked for the date or the time, it answers from the clock, not the model.
- A part of a long answer that draws no acknowledgement is sent again, and a
  radio is given a moment to switch from transmit to receive.
- A station heard through a digipeater is told it was heard on RF.
- The model is told its answer may go out on amateur radio and must be fit
  for it.
- A place name it cannot read is said to be unread; a distant weather
  reading says it is not local.

### Running unattended

- A background loop that fails is restarted, and the notify channel hears
  when the agent cannot hear the feed for 15 minutes.
- New setting `log_compress` gzips rotated packet logs (about 2.6:1).
- E-mail says when it cannot send.
- `tweepy` (Twitter) is optional.
- Dependency updates for published advisories (urllib3, multidict).
