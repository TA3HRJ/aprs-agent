# Release draft — v3.2.100

The body for the GitHub release. Built 2026-08-31 on the pinned 32-bit
environment (`docs/RELEASE-HOWTO.md`); the artefact is
`aprs-agent-v3.2.100.zip`, 58.1 MiB, 240 files, sha256
`C604CC8C7FC1E2AF60C2BE427F060ECB52E17526327BF1FED563D3D6FAB988A8`.

Suggested release name:

> **v3.2.100 — the watch that could not say it had stopped**

Asset, to match every previous release: `aprs-agent-v3.2.100.zip`

---

## Body

Three versions since v3.2.97, and all of them came out of one afternoon
spent reading what the software had actually said on the air and in its own
logs, rather than reading its code. Two of the four faults below had been
live for days without anything reporting them.

### A background loop died, and for 39 hours nothing said so

The silence and propagation watch stopped on 2026-08-29 at 16:45:26. It was
found on 2026-08-31. In between: no silence notification was sent, no
propagation opening was recorded, no assessment ran.

Nothing looked wrong. The map went on showing silence cells the whole time,
because those are computed per request and never came from the watch. The
history table went on filling, because a *different* loop writes it. The only
honest signal was a table that had simply stopped growing.

Two faults made a silent death possible, and both are fixed:

- **The task's reference was thrown away.** `asyncio.create_task(...)` with the
  result discarded leaves the task reachable from nothing, and an exception in
  it is reported only from `Task.__del__` — which may never run. Three days of
  journal contained no traceback of any kind. Every long-lived loop is now held
  and supervised: it logs its own death, with the traceback, at the moment it
  happens. A loop that exits *cleanly* is reported too, because none of them
  has a return path, so returning is as much a fault as raising.
- **The scan body was unguarded.** One exception anywhere in it ended the watch
  for good. The body now sits inside a guard that logs and carries on, with the
  pacing sleep outside it so a failed scan waits rather than spins.

What this release cannot tell you is *which* exception started it. The task was
already gone by the time anyone looked, and the traceback was never written
anywhere. The next one will be named.

### An episode that survives a restart keeps its note

Found while verifying the fix above, which is the only reason it was found at
all: the watch was healthy again and seven of eight alerting cells still had no
AI note.

Open episodes are restored across a restart, inside a 30-minute grace window —
correctly, since an episode that was open before is still open and should not
re-alert. But the note was written *only* when an episode opened. A restored
episode never opens again, so its assessment was permanently out of reach and
the note stayed empty for the rest of that episode's life, however many days
that was.

The notes now ride the same checkpoint as the episodes and come back with them,
filtered twice: the episode must have returned too, and the note must be
non-empty. A note without its episode is a verdict about something that is no
longer happening.

This one had been live far longer than the outage above and left no trace
anywhere — it only ever looked like a popup that happened to be missing a line.

### The gateway stopped giving signal reports it could not have measured

Asked `test.from VK` by a station in Australia, the AI gateway replied:

> OK VK2AHB-7, receiving you 5x9. Test acknowledged. 73.

This service has no receiver. That packet crossed the APRS-IS backbone over
TCP and arrived through somebody else's igate. `5x9` is a report on a radio
path that was never measured, sent to the one person likely to act on it — an
operator testing that path.

The system prompt already forbade role-playing a QSO, in as many words, exactly
as it forbade signing with another callsign before v3.2.97 had to take that out
in code. So this is out in code too: a sentence that *both* claims to have
received the sender *and* carries a report token is dropped. Both halves are
required, so "RST = Readability, Signal, Tone" and "599 is a typical CW contest
report" are correct answers and survive untouched.

And a test message no longer reaches the model at all. It is the commonest
thing anyone sends a service callsign and the one question where every true
fact is already in hand, so it is answered from the packet:

> Test OK VK2AHB-7, gated by VK2RAG-1. Internet-fed service - I cannot give a
> signal report.

A sender who reached APRS-IS directly gets no igate named, because naming a
backbone server as the station that heard them would be the same invention
somewhere else.

### The pricing gate that called itself dormant

A window deferring background AI calls during DeepSeek's peak-pricing hours
carried a comment saying it was dormant until that pricing began. There was no
activation flag; it had been firing on the clock since v3.0.7. Measured on the
live database: **359 of 1,110 silence episode openings (32.3 %)** had opened
inside that window and carry no assessment because of it.

DeepSeek's published window is also weekdays only, which the code never tested,
so 14 hours a week were being skipped against a discount that does not exist on
those days.

Thirty days of billing on that provider came to **$0.36**. The gate was trading
a third of the notes for a fraction of that, so it is gone rather than
corrected. The AI gateway's own `enabled` switch remains the one master control
for auto-triggered AI calls, which is what it was always documented to be.

### Under the hood

The guard rail is now **twenty checks**, nineteen of which run offline — three
more than v3.2.97. Each was written from a live failure and, before being
trusted, was **watched failing** against the broken code it exists to prevent:

- a service with no receiver never reports a signal, and a test is answered
  from the packet
- a background loop cannot die in silence, and one bad scan does not end a
  watch
- an episode restored across a restart keeps the note that belongs to it

Every file in this archive was verified against the `v3.2.100` tag before
publishing, and the running executable reports `3.2.100` from its own `/api/info`.
Against v3.2.97 the archive changes by exactly four files — the two executables
and the two `base_library.zip` they carry — with no file added, removed, or
otherwise altered.
