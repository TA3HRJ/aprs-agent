# Release draft — v3.2.97

**Not published.** This is the body for the GitHub release, written here
because the release itself has to be built on the documented environment and
this machine is not it. See the build note at the end.

Suggested release name:

> **v3.2.97 — the detector learns what it cannot see**

Asset, to match every previous release: `aprs-agent-v3.2.97.zip`

---

## Body

Thirty versions since v3.2.67, and almost all of them are the same shape: a
number the software stated confidently, checked against the feed, and found to
be answering a different question than the one it appeared to answer.

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

---

## Build note — why this is a draft

The release environment is pinned in `requirements-build-win32.txt`:

```
Interpreter: CPython 3.13.9, 32-bit  (C:\Python313-32\python.exe)
```

with exact versions, including `cryptography==45.0.7` chosen because it is the
newest release carrying a **win32 wheel** inside atproto's cap. That file
exists so a build can be reproduced instead of drifting with whatever PyPI
serves that day.

This machine has 64-bit CPython 3.13.15 and no PyInstaller, and its installed
dependencies resolved to different versions (atproto 0.0.71, cryptography
50.0.0). Building here would ship a 64-bit binary where every previous release
was 32-bit, from an unpinned dependency set — the exact drift that file was
written to prevent.

To build and publish, on the documented environment:

```
C:\Python313-32\python.exe -m pip install -r requirements-build-win32.txt
C:\Python313-32\python.exe -m PyInstaller aprs_agent.spec --noconfirm
```

then zip `dist/` as `aprs-agent-v3.2.97.zip` and attach it to a release tagged
`v3.2.97`, matching the naming of every release since v3.2.38.
