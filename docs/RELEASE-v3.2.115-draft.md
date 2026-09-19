# Release draft — v3.2.115

The body for the GitHub release. Built 2026-09-19 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). The artefact is
`aprs-agent-v3.2.115.zip`, 59.6 MiB, 248 files, sha256
`2EBB1EF260AB0C308CA980615B6066B9E1FEC88FFEEE7E5C5E08EE220DB3AA06`.

All 82 exported files matched their blobs in the tag, and all 10 shipped root
and static files in the archive matched byte for byte. The built web binary's
own `/api/info` reports `3.2.115`.

Against v3.2.111: nothing added, nothing removed, five files differing by CRC —
`static/index.html` at +9 bytes (the About line: a callsign one character
shorter, an address five longer in two places), both executables (+1,289 and
+927 bytes, carrying the changed modules), and both `base_library.zip` at
identical size with new internal timestamps, as on every rebuild. Dependencies
are unchanged since v3.2.111, including the 32-bit ceiling of cryptography
48.0.1.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.115 — nothing written, nothing answered, silently lost**

Asset, to match every previous release: `aprs-agent-v3.2.115.zip`

---

## Body

Four versions since v3.2.111. Two of them fix things that were lost without a
word: propagation openings that never reached the history, and gateway answers
that arrived but were never shown.

### Propagation openings were dropped on a busy database

Over a week on the live server, 13 of 247 detected openings never reached the
propagation history, so they were missing from the map timeline and from the
evidence lookup. Each one was logged as `history write failed: database is
locked`.

Once a minute the program saves every station it knows, in one transaction.
With a quarter of a million stations that save held the database for ten to
eighteen seconds, and every other write gave up after five. **Every database
connection now waits up to sixty seconds.** Reads that used to happen on the
web server's own event loop now run in the background, so a longer wait can
never freeze the interface.

### The AI gateway's first answer after a restart could vanish

APRS messages carry a number, and a receiving app uses it to recognise a message
it has already shown: a repeat is acknowledged and then not displayed. The
gateway numbered its replies from a counter that started again at every
restart, so **the first answer after any restart was always numbered 2 and 4**,
whoever it went to. A station that had heard from the gateway before could
acknowledge a new answer and never see it. This was found when an iPhone showed
one line of a two-line reply.

The last number used is now kept next to the config file and continued after a
restart. Where there is nowhere to keep it, the numbering starts from the clock,
so two runs never start from the same place. Numbers also step by one now, not
two.

### About panel

The maintainer's callsign changed from TA3HRJ to **TA3HX**. The About panel
shows the new callsign and contact address.

### Under the hood

The guard rail is **twenty-seven checks**, twenty-six of which run offline. Two
are new in this release, one for each fix above, and each was watched failing
against the code it replaced before being trusted.
