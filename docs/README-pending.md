# README update — APPLIED 2026-08-14

**Status: done.** All three blocks below went in, and line 26 took **option 1**.
Kept as the record of what was decided and why, not as a pending item.

Two things were added to block 1 beyond the wording accepted here, because
v3.2.24 and v3.2.25 shipped between the draft and the sweep and made the
original text incomplete:

- **A second demotion reason.** Grey no longer means only "chronic" — a cell
  whose silent callsigns belong to fewer than `min_silent` operators is also
  demoted (F-25). The colour line now reads "grey for measured but not
  announced" rather than "grey for chronic". The threshold is described as
  "too few separate operators" rather than a number, for the same reason the
  0.35 recurrence cut was left undocumented: a README that quotes a tunable
  goes stale the day it is tuned.
- **Two new honesty statements**: that popups flag stations whose own beacon
  cannot be trusted about their position (F-33), and that nothing is judged at
  all while the APRS-IS feed is down (F-35).

Block 2 also gained one clause: the bundle now carries how many distinct
operators and independent gates the silent set represents.

**No GitHub Release was cut, and the badge was not touched.** Option 1 removes
the reason to — the sentence is now true whatever the badge says, and a release
without a Windows build would promise a download that does not exist.

---

Three blocks changed, and one line needed a decision.

---

## 1 · Silence Map row (line 38)

The row explains how cells are detected but never says what makes one an
**alert**. That was harmless while alert meant "threshold met"; it is not
harmless now that the word means something narrower and the map has two
colours it does not mention.

### Current

> | 🗺️ | **Silence Map** | Leaflet map of all heard stations with real APRS symbols; detects regions where stations fall silent together (per-station beacon-cadence baseline, Maidenhead cell clustering, igate-failure discrimination) and paints affected cells; timeline slider replays the last 14 days of snapshots; new alerts get an AI assessment (via AI Gateway) shown in cell popups and are sent to the Monitor notify channel (Telegram/email). …

### Proposed (replacing the first two clauses, keeping the rest of the row unchanged)

> | 🗺️ | **Silence Map** | Leaflet map of all heard stations with real APRS symbols; detects regions where stations fall silent together (per-station beacon-cadence baseline, Maidenhead cell clustering, igate-failure discrimination) and paints affected cells. **An alert means the silence is news, not merely that the threshold was met.** A cell whose silent stations are all ones it habitually misses is marked chronic: it stays on the map in grey and drops out of the alert list, the notifications and the AI spend. What keeps a cell alerting is a station that is *unusual there* — one present in under 35 % of that cell's own past alerts — and the popup names it, so the reason is a callsign rather than a colour: *"New here: PY2GR-D — normally not among this cell's missing stations."* The raw threshold result is still reported as `threshold_met` and is still what gets stored, so nothing is hidden and fourteen days of history keep the meaning they were written with. Cell colour separates the four cases: red for a regional silence, yellow when a shared igate was **seen** to go quiet, orange when one gate carries every silent station but cannot be seen at all, grey for chronic. Timeline slider replays the last 14 days of snapshots; new alerts get an AI assessment (via AI Gateway) shown in cell popups and sent to the Monitor notify channel (Telegram/email). …

**Why this wording.** "Alerting often" and "the same stations again" are
different things and the second is the one that matters: on live data a cell
alerting in 2 % of runs still produced the identical set of silent stations
every time. Saying "news" rather than "chronic" first puts the reader on the
right question.

---

## 2 · Exportable evidence row (line 43)

The bundle gained fields. The row lists its contents, so the list is now short.

### Current tail

> …the detection parameters that selected the cluster, per-station silence detail, full USGS quake fields including the time offset and hypocentral distance, and the provider/model behind the shown note.

### Proposed tail

> …the detection parameters that selected the cluster, per-station silence detail, **how often each silent station appears among that cell's past alerts and which of them are unusual for it, how much of the cell's recorded history was already alerting**, full USGS quake fields including the time offset and hypocentral distance, and the provider/model behind the shown note.

---

## 3 · Phone layout bullet (line 493)

### Current

> …the settings sidebar folds behind a ⚙ overlay, the silence-alert list collapses to a one-line tappable summary, and the stat bar wraps into two rows…

### Proposed

> …the settings sidebar folds behind a ⚙ overlay, the silence-alert list collapses to a one-line tappable summary, the map legend folds behind a **Key** button (four cell colours are worth one tap rather than no explanation), and the stat bar wraps into two rows…

---

## The line that needs your decision — line 26

> This document describes the current release (see the badge above).

The badge reads from GitHub Releases, and the newest is **v3.2.4**. If these
edits go in, the README describes **v3.2.21** and that sentence becomes false —
a visitor comparing the text against the live demo would be right and the
README wrong.

Three ways out, in the order I'd pick them:

1. **Change the sentence** to something like *"This document describes what is
   running on the live demo; the download badge tracks the latest Windows
   build, which may be older."* Costs nothing, stays true whatever the badge
   says, and matches the deliberate decision that releases lag.
2. **Cut a v3.2.21 release with a Windows build.** Makes the sentence true
   again, but it is real work and nobody has asked for a Windows build.
3. **Leave everything.** The README stays accurate for 3.2.4 and inaccurate
   for the demo people actually visit — which is the worse of the two
   audiences to be wrong for.

I'd take 1.

---

## What I deliberately did NOT put in

- **The 0.35 threshold as a configurable knob.** It has one day of data behind
  it. Documenting it invites people to tune it before we know it is right.
- **Numbers from the live measurement** ("removes about 45 % of cells"). True
  this morning, not a property of the software, and a README that quotes
  yesterday's traffic ages badly.
- **`persistence`.** It is published and real, but it decides nothing now, and
  explaining a field that no longer has consequences costs the reader more
  than it gives.
