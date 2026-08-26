# Release draft — v3.2.97

The body for the GitHub release. Built 2026-08-26 on the pinned 32-bit
environment (`docs/RELEASE-HOWTO.md`); the artefact is
`aprs-agent-v3.2.97.zip`, 58.1 MiB, sha256
`4BE998EE45269FD13A474057CE9034B06495CFA777E0E53EC8498EA8FB4D9D3A`.

Suggested release name:

> **v3.2.97 — the detector learns what it cannot see**

Asset, to match every previous release: `aprs-agent-v3.2.97.zip`

---

## Body

Thirty versions since v3.2.67, and almost all of them are the same shape: a
number the software stated confidently, checked against the feed, and found to
be answering a different question than the one it appeared to answer.

**Two things about the download before the changes themselves.**

This build moves from **CPython 3.8 to 3.13**, which the previous release did
not have: v3.2.67 shipped `python38.dll` and OpenSSL **1.1.1**, both of which
reached end of life before it was published — Python 3.8 in October 2024,
OpenSSL 1.1.1 in September 2023. Every AI, Telegram and WhatsApp call this
software makes goes over that TLS stack. v3.2.97 ships CPython 3.13 and
OpenSSL 3.

And it is **smaller than v3.2.67 anyway** — 58 MiB against 59 — because the
frozen Desktop GUI is no longer bundled here. It has its own release line and
its current build is
[v2.8.3-desktop-final](https://github.com/TA3HRJ/aprs-agent/releases/tag/v2.8.3-desktop-final);
that is where Desktop users should go. This archive carries the CLI and the
Web GUI, which is the one to use.

One small loss worth naming: yarl's compiled URL quoter is not published as a
32-bit wheel for this Python, so URL encoding runs its pure-Python path. It
costs 0.21 µs per URL — about five million a second — on a path that runs once
per HTTP request and never during APRS ingest.

### The evidence bundle answers the link you asked about

`/api/prop/evidence` matched a link within ±300 seconds while walking the
buffer newest-first. A sender beaconing every 15 s puts twenty records inside
that window, so the bundle answered with a *later* link carrying a *later*
baseline — and every conclusion drawn from it compared two different events.
One pair returned the same wrong answer six times in a row.

Exact timestamps now win outright, at both doors. The tolerance remains for a
timestamp rounded to a stored event, but resolves to the **nearest** record
rather than the newest.

### A gate can stop being able to report anything, silently

A gate's alert bar is `max(3·mean, mean + 4σ)`. Once that climbs past the
5000 km ceiling nothing can ever clear it — longer links are discarded as GPS
garbage first — so the gate stops flagging and **no counter moves to say so**.
From outside, a gate that has gone deaf and a gate over a quiet band report
exactly the same thing: nothing.

**25 of 7,316 established gates were already in that state.** They are
reported now, with the numbers that put them there, because a reader weighing
"no opening here" needs to know some gates could not have said otherwise.

### One fixed error, repeated, is not two senders

Some gates measure the same large distance every time, because the fault is a
fixed coordinate rather than anything in the traffic — one carries **793 links
at 1250.5 km ± 0.4**. Repeated, such a link supplies its own "second sender"
and manufactures a band opening. Three of 246 stored openings existed only
because of one.

Those links are now kept out of the opening rule — the link only, not the
gate, so a suspect gate measuring something genuinely different still counts.
They stay on the map, labelled.

### A weather warning is not a station that fell silent

The weather service broadcasts severe-weather products over APRS as ordinary
**stations**, not objects — 557 of them. Silence detection rests on beacon
cadence, and a warning has none: it transmits while in force and says nothing
for the days between. Its silence was fair weather, reported as a regional
outage.

Excluded now. Over fourteen days of stored history that removed **3,640
cell-snapshots** from ever reaching the alert threshold.

### The silence ratio counts operators

Three SSIDs of one callsign are three radios in one shack on one power strip
and cannot fail independently. The alert has been qualified on operators since
v3.2.25 while the proportion beside it still divided callsigns by callsigns —
so a reader was told "80 % of this square fell silent" about two operators,
one still transmitting. Both ends count operators now, and the callsign figure
is published beside it so fourteen days of history keep their meaning.

### An absent opening says which absence it is

`opening: null` covered four different situations and outside readers took all
of them to mean "this was not an opening". It now names which: a recorded
event, the rule met with nothing written, genuinely one sender, or — the one
that mattered most — **this process cannot answer**, because the counts come
from a buffer a restart empties.

### Positions that are not on Earth

The parser accepted latitudes past 90 and longitudes past 180 if the digits
looked right; one link reported 4,646 km to a point that does not exist, and
the whole bundle around it was arithmetically perfect. Refused at the parser
now, and at the database load, which was a second door. 47 stored stations
carried impossible coordinates.

### Smaller things

- The AI gateway answers weather from the nearest station it has actually
  heard, with the distance and age stated, radius configurable
  (`wx_radius_km`, default 250 km).
- A callsign sign-off is stripped before an answer goes on air.
- The packet feed no longer floods the system journal — it was 97 % of it, and
  evicted every diagnostic line within a day. `log_file` keeps a copy that
  rotates on its own terms.
- The module badge reports whether an extension *worked*, not just whether it
  is switched on.
- `README`, `HELP` (both languages) and `aprsconfig.toml.template` were swept
  against the code; the template had been missing five documented keys.

### Under the hood

The guard rail is now **seventeen checks**, sixteen of which run offline. Each
one was written from a live failure and verified to fail against the broken
code before being trusted — several of them caught faults in the same session
that produced them.
