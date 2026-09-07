# Release draft — v3.2.107

The body for the GitHub release. Built 2026-09-07 on the pinned 32-bit
environment (`docs/RELEASE-HOWTO.md`), from a deleted `build/` and `dist/`. The artefact is
`aprs-agent-v3.2.107.zip`, 58.2 MiB, 240 files, sha256
`6A1B02E5A2AF6CE90686A6885165693FF4B426E2E2113C93CE11484997D91832`.

Against v3.2.103: nothing added, nothing removed, five files differing by CRC —
`static/index.html` at +2530 bytes (the phone work), `aprs-agent-web.exe` at
+351, both `_internal/base_library.zip` (identical size, changed internal
timestamps, as on every rebuild), and `aprs-agent.exe` at **exactly the same
size with a different CRC**: the only change reaching the CLI is the version
string, and "3.2.103" and "3.2.107" are the same length. A size comparison
would have called that file unchanged. All four shipped root files match
`git show v3.2.107:`, and the built binary's own `/api/info` reports
`3.2.107`.

Suggested release name:

> **v3.2.107 — the lock that only one loop could hold**

Asset, to match every previous release: `aprs-agent-v3.2.107.zip`

---

## Body

Four versions since v3.2.103. One of them closes a question that had been open
in the record since 2026-08-31; the rest are the phone.

### A shared lock, two event loops, and a watch that kept dying

The stat bar showed 337 errors over a nine-hour run. Two things were wrong,
and the smaller one led to the larger.

**Most of those 337 were not this program's errors.** The tally matched
`error`, `fail` and `fatal` against every line of the Live Log — and the Live
Log carries the packet feed. A station whose beacon comment says "Failsafe test
beacon" was raising the operator's error count. Measured against the journal:
65 real lines behind a badge reading 337. Packets are excluded now, while
untagged internal errors like `Read error from APRS-IS` are still counted.

**The 65 that were real contained twelve of these:**

```
[silence] scan failed, watch continues: RuntimeError:
<asyncio.locks.Lock object …> is bound to a different event loop
```

The silence-cell cache is read from two event loops — the web application's and
the agent thread's — and its lock was a single module-level `asyncio.Lock`. In
CPython 3.10 such a lock binds to the first loop that touches it and refuses
every caller on any other. The cache warmer runs at web-app startup, so it
always bound there first, and the agent's silence watch always lost. Twelve
scans in nine hours simply did not happen.

**This is almost certainly what killed the silence watch outright on
2026-08-29**, when it stopped for thirty-nine hours and nothing reported it.
The record from that day says the exception could not be named because the task
was already gone, and that the next occurrence would name it. The guard added
in v3.2.99 is what turned a silent death into a line of text, and the line
named it.

The lock is now created per event loop, with closed loops dropped rather than
accumulated. Two loops may rebuild the cache at the same time, which costs one
extra scan in a worker thread; against a scan that never happens, that is not a
difficult trade.

### The stat bar on a phone is two rows again

Reported as the bottom band overflowing once the packet counter passed a
million. It was not the digits — the bar wraps on a percentage and never on
content, and no number measured anywhere near its column's width. The bar had
grown from **eight cells to nine** when `Stations` was split into `Heard` and
`Registry`, and nine cells wrap to 4+4+1, leaving `Lifetime` alone on a third
row.

On a phone `Registry` now gives up its own column and rides with `Heard` as
`14842/233750`, labelled "Heard / Registry" — both numbers kept, which is what
the split was for, and the bar is two rows with its columns lined up again.

An attempt in v3.2.104 to widen the Packets column instead was **reverted in
v3.2.105**: it fitted the number better and broke the alignment between the two
rows, which is worth more.

### The module badge row is back for the operator

The row of extension indicators — AI, Station AI, World Feed, Telegram — was
hidden below 700 px on the reasoning that "which extensions are running is
operator detail, and the map is why a visitor is there". True of a visitor; the
admin panel is exactly where that question gets asked, and the rule could not
tell them apart. Now it can: hidden on the public page, shown on the operator's.

Also: `-webkit-text-size-adjust: 100%`, so a phone browser cannot inflate text
the layout has already sized, and stat values no longer wrap — a number that
wrapped would double its cell's height and push the whole band into the list.

### Under the hood

The guard rail is **twenty-four checks**, twenty-three of which run offline.
Each was written from a live failure and watched failing against the broken
code before being trusted.

One of them records its own limit, which is worth repeating here: the
behavioural half of the event-loop test **cannot fail** on CPython 3.13, which
no longer raises where 3.10 does. The same property is therefore also asserted
structurally, and that half fails on any interpreter. A check that can only
pass on the machine it runs on is not a check.
