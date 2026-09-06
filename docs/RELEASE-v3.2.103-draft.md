# Release draft — v3.2.103

The body for the GitHub release. Built 2026-09-06 on the pinned 32-bit
environment (`docs/RELEASE-HOWTO.md`), from a clean `build/` and `dist/`. The artefact is
`aprs-agent-v3.2.103.zip`, 58.2 MiB, 240 files, sha256
`8B8ABA7E38D9FAA3B472FD225A75343D6BB4F07746754F5CE714FA2CB7E888DC`.

Against v3.2.100: nothing added, nothing removed, five files differing by CRC
— both executables, both `_internal/base_library.zip` (same size, changed
internal timestamps, as on every rebuild) and
`aprs-agent-web/_internal/static/index.html`, +2552 bytes, which is the
Messages source selector and the start/stop handlers. All four shipped root
files match `git show v3.2.103:`, and the built binary's own `/api/info`
reports `3.2.103`.

Suggested release name:

> **v3.2.103 — three faults that reported success**

Asset, to match every previous release: `aprs-agent-v3.2.103.zip`

---

## Body

Three versions since v3.2.100, and the thread running through all of them is
the same: software that said it had done something it had not.

### The Stop button worked. The answer was wrong.

Reported as a dead Stop button on the admin panel. It was not the button, not
the browser and not the proxy — the web server's log showed four
`POST /api/stop` requests answered **200**, and three minutes after the last
one the agent was still running with its packet counter climbing.

`/api/stop` had been answering `{"ok": true}` on the strength of having
*scheduled* a stop, which is not the same as stopping. Underneath it,
`start()` guarded only on a flag that is set part-way through startup, so a
second start could slip into that window and replace the objects the first one
was waiting on — after which the stop signal went to an event nothing was
listening to, and the first agent ran on untouchable.

Now: `start()` refuses while the previous agent's thread is alive. `stop()`
says out loud when it cannot even signal. `/api/stop` waits to see the agent
actually stop and answers about **the agent**, not about a callback — and when
a stop does not take, it logs that plainly and dumps, from inside the agent's
own loop, whether the stop event is set and what is still running. The buttons
act on the answer instead of going quiet.

### A watch that could not say it had stopped

The silence and propagation watch died and nothing reported it for **39
hours**. No notification was sent, no propagation opening was recorded, and no
assessment ran — while the map went on showing cells, because those are
computed per request and never came from the watch.

Two causes, both fixed: the task's reference was thrown away at creation, so
an exception inside it could be reported only at garbage-collection time and
in practice never was; and the scan body was unguarded, so one exception ended
the watch for good. Every long-lived loop is now held and supervised, logs its
own death with the traceback at the moment it happens, and survives a failed
scan instead of being ended by it. A loop that exits *cleanly* is reported
too, because none of them has a reason to return.

### An episode that survives a restart keeps its note

Found while verifying the fix above, which is the only reason it was found:
seven of eight alerting cells still had no AI note. Open silence episodes are
restored across a restart — correctly, since they have not re-opened — but the
note was only ever written *when* an episode opened, so a restored episode
could never get one again for the rest of its life. The notes now ride the
same checkpoint as the episodes and come back with them.

### The messages panel keeps what matters

With the world feed on, the 400-entry Messages panel spans **twelve minutes**,
and measured on the live service it held **none** of the gateway's own traffic
and 7 of 400 messages involving the operator's own callsign prefixes. The one
conversation the service owns was the one it never had, and a restart emptied
it anyway.

The panel keeps its live view, and what is worth keeping now goes to the
database beside the other histories: the gateway's own conversation
unconditionally, plus anything matching the station filter, for fourteen days.
A new **Kept** source in the panel reads it back.

Everything else is not stored — about 48,000 messages a day. Disk is the
smaller reason: a searchable fortnight of third parties' messages is a
different object from a map of their positions.

### "TA*" meant Turkish stations, and also TACTICAL

A wildcard station filter is a prefix, and a prefix cannot tell a callsign from
a group name — `TA*` matched `TACTICAL`, an American group addressee, and one
row of it was archived within minutes of the feature shipping. Every amateur
callsign carries a digit in a fixed position and no group or object name does,
so that is now the test, in the three places the filter decides something:
what is archived, **who the AI gateway answers**, and what may count as a
station that fell silent. The APRS-IS server-side filter is deliberately left
alone — it speaks the network's own syntax and cannot express this. An exact
filter entry is still honoured exactly.

### The AI gateway stopped reporting signals it never measured

Asked for a test by a station in Australia, it had replied *"receiving you
5x9"* — a report on a radio path it has no receiver for. A sentence that both
claims to have received the sender and carries a report token is now dropped
before transmission, and a test message never reaches the model at all: it is
answered from the packet, naming the igate that actually gated it and stating
plainly that no signal report is possible.

### A pricing gate that called itself dormant

A window deferring background AI calls during a provider's peak-price hours
described itself as inactive. It had been firing on the clock since v3.0.7, and
had left **359 of 1,110 silence episode openings (32.3%)** without an
assessment. Thirty days of that provider's billing came to $0.36. The gate is
gone.

### Under the hood

The guard rail is now **twenty-three checks**, twenty-two of which run offline
— six more than v3.2.100. Each was written from a live failure and, before
being trusted, was watched **failing** against the broken code it exists to
prevent.
