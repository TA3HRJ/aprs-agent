# Release draft — v3.2.125

The body for the GitHub release. Built 2026-09-21 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). The artefact is
`aprs-agent-v3.2.125.zip`, 59.7 MiB, 248 files, sha256
`83FF0CB1325B34F35F55F1DBF7492775D157902D05755E8F2CBA69B604D35FB5`.

All 89 exported files matched their blobs in the tag, and every shipped root
and static file in the archive matched the tag byte for byte. Both bundled
executables carry `config.VERSION` 3.2.125 and the release's new constants.

Against v3.2.119: nothing added, nothing removed, eight files differing by
CRC — `HELP.html` (+1,791 bytes, the new section on station lookups and
NOLOOKUP, in both languages, three copies), `static/index.html` (+1,345, the
usage counter), both executables, and both `base_library.zip` at identical
size with new internal timestamps, as on every rebuild. Dependencies are
unchanged, including the 32-bit ceiling of cryptography 48.0.1.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.125 — the day it met strangers**

Asset, to match every previous release: `aprs-agent-v3.2.125.zip`

---

## Body

Six releases since v3.2.119, all of them in the AI gateway, and every one of
them written from traffic rather than from testing. The service was announced
in two APRS groups on 20 September and the people who tried it found more in
an afternoon than months of use by its author had.

### It answers from the registry instead of sending you elsewhere

The station database holds a quarter of a million stations, and the gateway
used to answer questions about them with "I have no live data". Now, without
a model call:

- **Which igate heard you** — from the path of your own packet, and if you
  came in over the internet it says so rather than naming the core server.
- **The nearest igates or repeaters**, with distances, measured from a grid
  you name or from your own last beacon.
- **Openings near you**, from the propagation the program itself measured.
- **Another station's last position**, with its age and its distance from
  you — one observation, the same fact the map draws. Never a name, a licence
  record or an address. A station that sends **NOLOOKUP** is left out of
  other people's answers; **LOOKUP** puts it back. `HELP.html` says so in
  both languages.

Refusals now name their own reason: no data, no place names, or a station
that asked to be left out. A UK postcode is recognised as a postcode instead
of being read as a Maidenhead square on the other side of the world.

### It holds a conversation

The last three exchanges with a station travel with its next question, for
ten minutes, in memory only. Follow-ups that name nothing — "how long would
it take by car?" — now land.

### It knows what it is

"What can you do" is answered from the code rather than invented by the
model, before the rate limiter and at most once per sender per ten minutes.
A message meant for another station is answered as what it is, rather than
the model greeting you by somebody else's name. And it no longer talks to
other machines: a sender whose callsign is not callsign-shaped is ignored
before the acknowledgement, after two services spent forty seconds answering
each other.

### It costs the channel less

A re-sent question is answered from cache rather than bought twice, a
duplicate that arrives in the same second draws no second copy, and a
question asked a third time is answered rather than met with silence.

### Usage

The About panel now shows how many operators have used the gateway today and
in total, and how many questions it has answered, linked to the Messages tab.
Aggregates only.

### Under the hood

The guard rail is **thirty-one checks**, thirty of which run offline.
Four are new in this release line (`check_gateway_intent`, `check_context`,
`check_lookup`, `check_gateway_stats`), and each was watched failing against the
code it replaced before being trusted.
