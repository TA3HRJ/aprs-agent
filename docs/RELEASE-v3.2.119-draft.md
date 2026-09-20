# Release draft — v3.2.119

The body for the GitHub release. Built 2026-09-20 on the pinned 32-bit
environment, CPython 3.13.15 32-bit, from a `git -c core.autocrlf=false
archive` export of the tag (`docs/RELEASE-HOWTO.md`). The artefact is
`aprs-agent-v3.2.119.zip`, 59.6 MiB, 248 files, sha256
`CFE89C38C855FB6595B73E392DE17F811A714A5B152E905A901EDA74985939CA`.

All 86 exported files matched their blobs in the tag, and every shipped root
and static file in the archive matched the tag byte for byte. Both bundled
executables carry `config.VERSION` 3.2.119 and the new gateway constants.

Against v3.2.116: nothing added, nothing removed, four files differing by CRC
— both executables at +3,507 bytes, carrying three releases of gateway
changes, and both `base_library.zip` at identical size with new internal
timestamps, as on every rebuild. Dependencies are unchanged, including the
32-bit ceiling of cryptography 48.0.1.

`aprsconfig.toml`, `*.db` and loose `.py` files: none in the archive.

Suggested release name:

> **v3.2.119 — the gateway learns to hold a conversation**

Asset, to match every previous release: `aprs-agent-v3.2.119.zip`

---

## Body

Three releases since v3.2.116, all of them in the AI gateway, and all of them
written from one afternoon's worth of strangers using it for the first time.

### It remembers the sentence before

A station asked for the best way from Bremen to Berlin, got an answer, then
asked *"How long would it take by car?"* — and was told to name the two
places. Every question went to the model on its own.

**The last three exchanges with a station now travel with its next question**,
for ten minutes, in memory only and never written to disk. Follow-ups that
name nothing — which is how people write them — now land.

### It answers "what can you do"

That is the first thing a newcomer sends, and it was the one question with no
answer: it went to the model, which described the service in its own words,
and if the sender had spent their burst on earlier questions the rate limiter
refused it outright. It is now answered from the code, before the limiter,
costing neither a model call nor a token — and at most once per sender per ten
minutes, so a free answer cannot be used to make a distant igate transmit on
demand.

### It stops mishearing the question

*"Tell me a joke about the weather"* came back as a temperature reading from a
station 28 km away: the weather shortcut matched the word anywhere in the
text. It now stands down for a joke, poem, song, story or riddle in either
language, and a real weather question still reaches the registry without
touching the model.

### Asking twice no longer costs twice, and asking a third time is not met with silence

A client that gives up waiting numbers its re-send afresh, so the same
question arrived as two, was paid for twice, and went out twice. A question is
now indexed by its words as well as its number for two minutes.

At the other end, an answer could be replayed twice and after that the sender
got nothing — indistinguishable from a dead gateway. The cached answer now
goes out again instead, still without a second model call, and each copy costs
a rate token, so how often someone may ask is the bucket's decision rather
than a flat cap.

### Under the hood

The guard rail is **twenty-nine checks**, twenty-eight of which run offline.
Two are new — `check_gateway_intent.py` and `check_context.py` — and each was
watched failing against the code it replaced before being trusted.
