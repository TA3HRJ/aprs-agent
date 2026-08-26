# What to do next — draft

A proposed order for the open items in [FINDINGS.md](FINDINGS.md). This is a
plan, not a record: it gets rewritten as work lands. Nothing here is a new
feature; every item makes something that already exists tell the truth.

The ordering principle: **fix what actively misinforms someone before fixing
what merely under-informs them.**

---

## WHERE THIS STANDS — 2026-08-21

**Deployed: v3.2.80** on the VPS. The next package is **§B · Propagation
evidence**: go straight to its **Start here** block, which carries the command,
the measured red, the definition of done and the scope for that session.
Nothing else in this file needs reading first.

Everything from the next heading down to §B is history — kept for the
reasoning, not for the status. It stopped being current at v3.2.31.

---

## OPEN AS OF 2026-08-14 — superseded, kept for the reasoning

**Deployed at the time: v3.2.31**, and GitHub was level with it: badge, download
and demo all read 3.2.31. The stop below was lifted; work resumed and shipped
through v3.2.80.

### ✅ Closed in the evening — v3.2.26 … v3.2.31

Six versions, and the useful part is that **three separately-chased symptoms
turned out to be one fault** — see the F-38 block in [FINDINGS.md](FINDINGS.md).

| | |
|---|---|
| **F-38** | `/api/silence` sent 1.08 MB to draw 32 rectangles; with `/api/stations` trimmed, 2.43 MB → 0.96 MB per poll |
| **F-39** | the copy was a five-second deadline, not a clipboard fault; the bundle now opens in a selected text box |
| **F-40** | the service worker served old code and no reload could escape it; the offline cache is gone |
| **F-41** | T2 backbone servers are not independent gates; 23 of 36 cells reclassified, alerting 20 → 8 |
| F-37 | a caveat severed by the v3.2.25 edit, plus the check that would have caught it |

### 🛑 Stopped here — 2026-08-15, 00:45

Deploying stopped mid-thread, at the operator's word and rightly. Eight releases
in one day is itself part of what went wrong; see F-43. Nothing below should be
started without reading that entry first.

**Broken, and not fixed:** the evidence copy still fails. The last screen showed
the 20-second deadline firing — *"the server did not answer in time"* — on a
propagation link. That is the F-36 tail, still unexplained, and it is the thing
actually blocking the operator's work. v3.2.32 added tracing for it; the trace
has not been read yet.

**The first thing to do, before any detector work:** persist `_gate_stats`.
Station records, cadence history and lifetime uptime all survive a restart;
the gate baselines that every propagation judgement depends on do not, and
without them `PROP_MIN_SAMPLES = 20` may never engage in production at all.
F-03's numbers cannot be trusted until baselines can accumulate — and my own
measurement of them is corrected in F-43.

**Do not re-run the F-03 analysis on a freshly restarted process.** That is the
mistake it took six outside readings to notice.

### ⏱ Still open, and now the only slowness thread left

`/api/stations` is **939 KB and up to 5 s cold**, and the page asks for the full
capped list rather than the viewport: 2,739 requests with no query string
against 4 with a `bbox`. The ETag works — repeat polls inside the cache window
answer `304` — but the token turns over as the registry updates, so a poll
spaced further apart always pays full price.

Two candidates, neither measured: have the map ask by `bbox` at the zoom levels
where it already clusters, and drop `last_seen_ago_s` (83 KB, derivable from
`last_seen` client-side).

**The 7.85 s rebuild tail from F-36 is still unexplained** and is now less
urgent, because nothing user-facing races it any more.

### 📋 Waiting on the operator

- **Proximity site-merging (F-25).** Six cells would collapse further under the
  200 m rule and one of them alerts. Reported, never applied — a position
  cannot tell a club site from two neighbours. A few days of that list is the
  evidence for whether the radius is right.
- **The `recurrence` / `per_station` contradiction** seen in the KM59 bundle:
  recurrence reported 0 for five stations the same file said had been silent
  here 3 to 87 times. Unreconciled, and it drives the `alert` definition.
- **`peak_silent` is circular** when the peak was set by the episode being
  read — same family as the F-16 denominator bug.
- **The map loading animation**, still an undecided idea from the morning.

### ✅ Closed — v3.2.25

- **F-25 — a callsign is not a witness.** Cells carry `sites`,
  `sites_colocated`, `independent_gates` and `self_gated`; fewer than
  `min_silent` operators demotes a cell out of `alert`. Eight cells demoted on
  the live feed, none still alerting. The proximity count is **reported and
  never applied**, by the operator's decision — a position cannot tell a club
  site from two neighbours.

### ⏳ The one measurement this leaves open

Six live cells would collapse further under the proximity rule and **one of
them is currently alerting** (`PN36`, 3 operators → 2 sites). Left alone
deliberately. After a few days that list is the evidence for two questions:
whether 200 m is the right radius, and whether the rule should ever decide
anything rather than only inform. Nothing else about F-25 is waiting on it.

### ✅ Closed — v3.2.24

- **F-34 — the feed had no liveness check.** `readline()` now has a 120 s
  deadline, logs when it fires, and reconnects. Verified against a socket that
  accepts and then says nothing: the loop returns at the deadline and logs;
  with keepalives flowing it never fires.
- **F-35 — a deaf feed read as "nothing is silent anywhere".** Deaf is a state
  now (`StationDB.deaf_since()`). The monitor loop holds every episode instead
  of retracting it, the cached cells are held rather than overwritten,
  `/api/silence` carries `deaf`/`deaf_since`, the evidence endpoint answers
  **503 naming the feed** instead of 404 naming the cell, and the page shows a
  bar. Verified end-to-end through the real handlers with the feed clock moved
  back 729 s.
- **F-36 — the cache floor.** 2.0 s → 10 s, and an empty result is now cached.
  **Partial:** median 0.101 s and 7-in-90 over half a second, against ~1-in-5
  before — but a 7.85 s outlier remains and did not reproduce on demand. See
  the measured block under F-36 in [FINDINGS.md](FINDINGS.md).
- **F-33 — `suspect_position`.** Cells carry how many of their silent stations
  beacon a US callsign from an eastern longitude on hotspot firmware. Live:
  7 cells of 2,125 carry it, **5 of them entirely** — NM58 reads 3 of 3.
  Flagged in the popup, in both languages, and in the bundle's caveats.

### ⏱ Still unexplained: the rebuild that costs eight seconds

Three hypotheses are now retired — `COUNT(DISTINCT ts)`, the unindexed `cell`
scans, and the cache window. The window was real and shipped; it did not take
the tail with it.

What is established: the walk runs about a fifth as often, and the common case
is sub-quarter-second. What is not: why an occasional rebuild costs eight
seconds where the next one costs 0.086 s. The server has other pollers keeping
the cache warm, so a request's starting state cannot be controlled from
outside — any fourth hypothesis needs instrumentation inside the build, not
another probe from the edge.

### Open questions, no code yet

- **Callsign → aprs.fi.** The callsign is *already* clickable (it opens our
  own detail modal), so the ask becomes an additional external link rather
  than a replacement. Why the existing click appeared unresponsive was never
  established — needs a live look.
- **"triangle" and earthquakes — awaiting the operator's decision.** The
  symbol is the sender's choice, and APRS already has a real quake symbol
  (`\Q`, typed `quake`, rendered 🌍) which this object did not use. Proposed
  instead: read the magnitude out of the packet's own text, and corroborate
  against the USGS feed already polled for silence correlation — "matches
  USGS M4.3 · 12 km · 6 min" is evidence, "it is a triangle" is not.
- **NM58 — reasoned from code, unverified.** Four silent stations at
  ~90°E/38°N with US callsigns, three of them SSIDs of one base callsign
  (`KC9SIO-B/-D/-N`). Counted as three independent witnesses; collapsed to one
  site the cell would fall under `min_silent` and never appear. This is F-25
  with a concrete live example, and the check is one query.
  — **Verified 2026-08-14**, see the addendum to F-33 in
  [FINDINGS.md](FINDINGS.md).
- **A loading animation over the map — operator's idea, 2026-08-14, undecided.**
  Recorded verbatim, not assessed: hold an animation of the kind seen on other
  sites until the map has fully loaded, so that it covers both the clipboard
  error and OpenStreetMap's empty start. Asked as a question — "would that be
  the right thing to do?" — and awaiting the operator's own decision.

### Note for whoever runs the next clipboard test

The in-app browser runs on the operator's own machine and shares their system
clipboard. A verification click during this session overwrote it with another
cell's bundle, and the operator understandably read that as a bug. Say so
first, or do not run clipboard tests there.

---

## ✅ DONE — the README sweep, 2026-08-14

Applied in one pass, as intended. Line 26 took **option 1**: the README now
says it describes the live demo and that the badge tracks the Windows build,
which may be older — true whatever the badge says, and it matches the standing
decision that releases lag deliberately.

| | |
|---|---|
| README · Silence Map row | what `alert` means, **both** demotion reasons, the colours, the position caveat, and what happens when the feed stops |
| README · evidence row | recurrence, novel stations, alerting history, operators and independent gates |
| README · phone layout bullet | the Key button |
| README · line 26 | option 1 |
| GitHub Release + badge | **cut after all** — see below |

The record of what changed and why is in
[README-pending.md](README-pending.md), kept rather than deleted.

### GitHub levelled with the demo — v3.2.25

**Released with a real 32-bit Windows build** (58.4 MB, built and smoke-tested
locally on the Python 3.8.10 32-bit / PyInstaller 6.19.0 rig). Badge, download
and demo all read 3.2.25 for the first time since v3.2.4 — twenty-one versions.

The three folder-mode builds were checked before packaging: no database, no
config and no path leaked into the archive, and the web build was run and
answered `/api/info` 3.2.25 with the new `deaf` fields present.

**The gap will reopen, by design.** Deploys are tag-driven and hourly; a
Windows build is manual. Line 26's wording was chosen to stay true in both
states, so nothing needs editing when it does.

---

## SHIPPED 2026-08-14 — v3.2.16 … v3.2.21

Six versions, and two of them fixed what the four before them broke. Worth
recording as the cost of the pace, not just the outcome.

| version | what |
|---|---|
| **v3.2.16** | persistence had compared a cell's alerting rows against its own rows — 1.0 for every cell by construction |
| **v3.2.17** | the timeline was cutting the legend in half; and it exposed a regression where replayed snapshots drew nothing at all |
| **v3.2.18** | the reload guard suppressed retries on intent rather than outcome (hardening — the fault it was written for was never confirmed) |
| **v3.2.19** | legend and timeline stacked so neither can cover the other |
| **v3.2.20** | the AI prompt was telling the model every cell was chronic — the same denominator artefact, third location, and the one that spoke to the operator in prose |
| **v3.2.21** | **chronic moved from "how often" to "the same faces"** — see F-31 |

### F-04 is now largely answered, without touching a threshold

- **The single-gate rule is correctly rare, not too strict.** 1 of 37 alerting
  cells has all its silent stations behind one gate; most have three or four.
  `outage` is doing honest work on multi-gate cells. This closes the watch
  item recorded at the v3.2.12 baseline.
- **Persistence was the wrong axis** and never fired. Recurrence — is this the
  same cast of stations again — cuts 46 % of threshold-meeting cells and gives
  every survivor a callsign that justifies it.
- **Still untouched:** `min_silent = 3`, `min_ratio = 0.5`. Nothing measured so
  far argues for moving them, which is a perfectly good answer to have on
  record.

**Let the new `alert` sit for a day before anything else moves.** Its
definition changed this morning; the next measurement is worth more once it
has run through a full daily cycle.

---

## SHIPPED 2026-08-13 — v3.2.14 and v3.2.15

Three findings closed, in the order this file called for: the one that could
make the page unusable, then the one that misinformed every reader, then the
one waiting on a decision only the operator could make.

| version | finding | what changed |
|---|---|---|
| **v3.2.14** | **F-19** | one evidence request at a time, a real `AbortController` with a 20 s deadline, and a working state on the clicked link. The service worker's navigate race no longer leaves its losing `fetch` running either |
| **v3.2.15** | **F-24** | below `PROP_MIN_SAMPLES` the gate baseline stops publishing `mean_km` and `sigma_km`. It reports `ema_km`, `ema_alpha` and `first_sample_weight` instead, and states that 77 % of the figure is still the gate's first packet |
| **v3.2.15** | **F-26** | `alert` now means the silence is *news*: threshold met AND either not chronic or past the cell's own worst. `threshold_met` keeps the old meaning; `silence_history` still stores the raw result |

**F-02 is closed by F-24** — it asked for wording saying mean and sigma are not
meaningful yet; the fix removed the fields instead, which is the stronger
version of the same point.

**F-15c is closed by F-19** — the copy feedback the operator missed twice now
lives on the button.

### Measured on the VPS the same evening — and it changed the answer

v3.2.15 reported `persistence: 1.00` for all 39 threshold-met cells. That was
a bug (**fixed in v3.2.16**): only alerting snapshots are stored, so the ratio
compared a cell's rows against its own rows. Corrected, the live distribution
is:

| persistence | cells (of 41) |
|---|---|
| below 0.40 | 29 |
| 0.40 – 0.74 | 10 |
| 0.95 – 1.00 | 2, both younger than 24 h |

**Nothing is chronic today**, so `alert` is back to 41. EN03 — the cell three
outside models called an artefact on "860 of 860 snapshots" — alerts in **48 %
of runs**. The premise F-26 was built on came from our own export.

**This is now F-04's input, not a reason to retune.** Moving the threshold to
0.5 would demote two or three cells, and it may well be right, but one
evening's snapshot is not a calibration and this project has already been
burned once by adjusting a rule the day it was questioned.

Still worth watching:

- **Whether any cell reaches 0.9 with more than a day of history.** None has
  yet; the two at 1.00 are simply too young to judge.
- **Anything that alerts because it passed its own peak.** That case is the
  reason plain suppression was rejected, and the first one is worth reading.

---

## A · The silence alert chain — SHIPPED in v3.2.12

> Done. `shared_gate` is now its own cause, carried through the colour, popup,
> alert list, legend, both languages and the notification text; the bundle
> carries `gate_of` with each gate's tracked state; the assessment prompt
> receives the cell history and the measured onset spread; and a `context`
> block places the current ratio in the cell's own past.
>
> Live afterwards: 46 cells reading `outage`, 2 reading `shared_gate` — NL79
> through `T2HK` and MK65 through `T2KA`, both **T2 backbone servers**, which
> never appear as stations and so could never be confirmed silent. Those two
> would previously have alerted as regional outages.
>
> Detection thresholds untouched. Whether a multi-gate cell should still read
> as an outage is F-04's question, and answering it by adjusting a rule the
> same day it was questioned is a mistake this project has already made once.

<details><summary>Original plan (kept for the record)</summary>

### A · The silence alert chain — first, and not close

Four findings, one wrong alert. Today an operator can be told *"regional power
or infrastructure outage, high confidence"* over Telegram or email when what
actually happened is that one igate — which never beacons, so we cannot see it
— lost its internet, on a cell that has looked the same for a fortnight.

Every other open item is about a reader being under-served. This one is about
the operator being actively misled, by a message that arrives on their phone
and asks them to act.

| finding | change |
|---|---|
| **F-13** | put `gate_of` in the bundle: which stations came through which gate, whether that gate is tracked, when it was last heard |
| **F-13** | give the untracked-gate case its own cause instead of `outage`. All silent stations sharing one gate is strong evidence of a shared path failing, whether or not that gate can be seen |
| **F-11** | pass the cell history summary into `_assess_silence()`'s prompt, so a two-week-old condition stops being diagnosed as a fresh event |
| **F-01** | have the note state the measured onset spread instead of asserting "simultaneously". Nine seconds and eleven hours are both in the data; only one of them is an outage signature |
| **F-14a** | one field placing the current ratio inside the cell's own distribution, so "this is normal for this cell" does not require reading 567 rows |

**Files:** `station_db.py` (`silence_cells` cause branch), `web_gui.py`
(`get_silence_evidence`, `_assess_silence`).

**Risk:** low on the bundle side, moderate on the cause branch — changing what
`cause` can contain touches the map legend and the notification text. Worth
checking both before shipping.

**Verify:** re-export KO84. The bundle should name `R3XBI` as the shared gate
and say it is untracked; the cause should no longer read `outage`; and the note
should not claim a fresh regional outage on a cell with 13 of 13 alerting
snapshots.

</details>

**What the verification actually showed.** KO84 had moved on by the time the
work landed — ten stations silent through *three* gates, so the single-gate
rule no longer applied to it and it still reads `outage`. `R3XBI` does now
report `tracked: false` in its bundle, which was the point. The classifier
change proved itself on other cells instead. Worth remembering that a case used
to justify a change may not be there to confirm it.

---

## Watching A before starting B

Deliberate pause, not a stall. The `shared_gate` branch is new and its rate is
itself the evidence for F-04, so it is worth a few days of running before
anything else moves.

**Baseline at deploy, 2026-08-13, v3.2.12:**

| | |
|---|---|
| cells reading `outage` | 46 |
| cells reading `shared_gate` | 2 (NL79 via `T2HK`, MK65 via `T2KA`) |
| cells reading `igate` | 0 in that sample |

**What would mean something when we come back:**

- `shared_gate` staying at one or two percent says the branch is catching a
  narrow real case and the alert text is now honest for it.
- `shared_gate` climbing towards a large share says most "regional outages"
  were always one path, and the `outage` label itself is the thing that needs
  rethinking — which is F-04's question arriving with an answer attached.
- Both near zero, with cells still alerting as outages through several
  untracked gates, says the single-gate rule is too strict to matter and the
  interesting version is "one gate carries the overwhelming majority", not
  "one gate carries all". That is a detection change and needs its own
  evidence, not a same-day guess.

Whatever it shows, the numbers come from `/api/silence` and cost nothing to
collect: the cause distribution is one line.

---

## B · Propagation evidence — second

The bundle currently contradicts itself, and the fix unblocks the calibration
that has been waiting since July.

### ✅ The head is done — v3.2.81 / v3.2.82, 2026-08-22

`python3 tools/check_prop_bundle.py --max 12` on the VPS: **0 problems, exit 0**,
against 12 of 93 live anomalous links. It read 43 problems across 12 links the
night before.

| assertion | was | now |
|---|---|---|
| `at_flag` carries `sigma_km` | 12 of 12 failing | pass |
| `at_flag` carries `threshold_km` | 12 of 12 failing | pass |
| `gate_baseline.samples` exceeds `at_flag.samples` | 12 of 12 failing | pass |
| the published multiplier's denominator clears the 300 km floor | 7 of 12 failing | pass |

**What shipped:** F-2026-08-16-01, F-2026-08-16-01b and F-16's recording half,
plus two findings the work produced — see F-2026-08-22-01 and -02 in
[FINDINGS.md](FINDINGS.md).

**One live bundle, as it now reads** (XE2BNC-1 → KF6NYM-15, 373.9 km):

| | samples | threshold |
|---|---|---|
| `gate_baseline` — at flag | 3265 | **327.4 km** → cleared by 1.1x |
| `gate_baseline_now` — at export | 3360 | **474.4 km** |

A reader given only the second would conclude this link should never have been
flagged: 374 is short of 474. That is the circle, and it is now two named
blocks instead of one ambiguous name.

**Three things worth carrying forward.**

1. **The check would have passed by examining nothing.** The ring buffer is in
   memory; the deploy restarts the service and empties it, and the old check
   exited 0 on an empty list. Fixed before deploying, and the first live run
   after the deploy printed exactly that failure.
2. **The check was comparing two different events.** `/api/prop/evidence`
   without a `ts` answers with the most RECENT link for a sender→gate pair, and
   pairs repeat — **W0ZC-15 → RA4NHY-1 appears 19 times**, XE2BNC-1 →
   KF6NYM-15 seven, all at an identical distance. So link A's `at_flag` was
   being held against link B's baseline. Invisible while the baseline was read
   live, because it was larger either way. The check now sends the timestamp
   and refuses to run if the bundle answers with a different one.
3. **"43 problems / 12 links" was never a stable number.** `--max 12` caps the
   sample; the pool was 33 on the 21st and 93 on the 22nd. Read the cap.

### What is left in B

F-09, F-22 and F-23 — presentation, independent, unchanged by this. F-03 now
has the field it needs and starts its measurement clock here: it wants a few
days of data before the absolute-floor branch can be judged.

**One new OPEN item, from F-2026-08-22-01:** the opening alert filters on
`at_flag.established`, and a gate can be established by sample count while the
bar its own history sets is 0.3 km — under the floor. By the same reasoning
those links were flagged by the floor alone and should not raise a
notification. Deliberately not done here: it changes what puts a notification
on somebody's phone, and that needs its own evidence.

<details>
<summary>The red this replaced, 2026-08-21 (v3.2.80)</summary>

```
cd /opt/aprs-agent && python3 tools/check_prop_bundle.py --max 12
```

Exit code 1. **43 problems across 12 anomalous links.**

**What this run added to the finding.** F-2026-08-16-01 was written from one
link, where `gate_baseline` had exactly one sample more than `at_flag` and a
single EMA step explained it. Across twelve links the drift ranges from **1 to
21 samples**:

```
extra samples between flag and read:  1(x3)  3  4(x3)  5(x2)  6  20  21
```

So the single-step arithmetic in the finding was the mild case. On a busy gate
the published baseline is not one event stale, it is twenty — and the busier
the gate, the further the number drifts from the one the decision actually
used. That strengthens the item rather than changing it: it is still a
circle, just a wider one.

Real denominators seen in the multiplier, all under the 300 km floor:
**46.9, 65.4, 117.3, 168.7 km**.

</details>

**Scope for that session (done):** the head only — F-2026-08-16-01 plus the recording
half of F-16. That is what starts F-03's measurement clock. F-09, F-22 and
F-23 are presentation, independent, and can wait again.

| finding | change |
|---|---|
| **F-16** | record the gate's `samples`, `mean`, `sigma` and threshold **as they stood at flag time**, on the link. Show both that and the current baseline |
| **F-2026-08-16-01** | **first, and it is half of F-16 done badly.** `at_flag` shipped in v3.2.34 carrying only `samples` and `ema_km`, and the bundle's `gate_baseline` block was left reading live — so the published baseline is the post-event one. Measured: `at_flag` 40 samples / 0.1 km, `gate_baseline` 41 samples / 27.0 km / threshold 508.3, where the extra sample **is the link being judged** and `0.95 × 0.1 + 0.05 × 538.2 = 27.0` exactly. Add σ and the threshold to `at_flag`; make `gate_baseline` either flag-time or plainly named as the after state |
| **F-2026-08-16-01b** | the popup's multiplier divides by the EMA, which hugs zero on gates that mostly hear stations beside them — one link read **5382× its usual reach** where the ratio to the mean is 19.9, and the gate next door would have said 2696× for the same distance. Take the multiplier against the **threshold** instead: it cannot approach zero and it is comparable between gates |
| **F-03** | with that field recorded, count how many of the anomalies came from gates below the 20-sample threshold. Then decide whether the absolute-floor branch is producing signal or noise — with numbers, not judgement |
| ~~**F-02**~~ | ~~say plainly that mean and sigma are not meaningful yet~~ — **closed by F-24 in v3.2.15**, which removed the fields rather than annotating them |
| **F-09** | replace `opening: null` with three states — a recorded event exists / the rule is met right now but nothing was written / genuinely one sender. Add the live field context (other anomalous links and distinct senders in the same field) and the repeat count for this sender→gate pair<br><br>**✅ SHIPPED v3.2.91.** `opening_status.state` names which of four situations an absent `opening` is — `recorded`, `rule_met_not_recorded`, `single_sender`, `unknown` — and `context` carries the field counts, the live sender list and the repeat count for the pair. The fourth state is the one the original finding did not anticipate: the counts come from a ring a restart empties, so a fresh process would otherwise report an absence it cannot know. |
| **F-22** | group openings by **receiving gate** as well as by midpoint field. The current rule cannot see the strongest evidence there is — one gate hearing several distant unrelated senders — and the operator has already run this grouping by hand once, which is how the finding was found<br><br>**❌ MEASURED AND DECLINED — 2026-08-26, F-2026-08-26-06.** `context.at_this_gate` reports the gate grouping beside the field one (v3.2.91) and that is where it stops. Measured over 180 links / 7.74 h: the gap is **2 links (1.1%)**, both flagged by the 300 km floor alone at a 12-sample gate, so the established filter the opening loop already applies removes them — **additional openings: 0**, against 13 the field rule found in the same ring. The two filters compose. And the gap turned out to be a grid artefact: fields `FF` and `GF` are adjacent, so the midpoints straddled a boundary rather than lying 1,600 km apart. If that is worth fixing the answer is neighbouring-field grouping, which is a different finding. Re-ask with `tools/measure_f22.py`. `context.at_this_gate` asks the rule of the receiving gate beside the field grouping, so the two can be compared. Detection is unchanged, deliberately: grouping by gate means trusting gates, and the instrument for deciding whether a gate deserves it only arrived in v3.2.88–90 (F-2026-08-26-01/03/04). Now decidable, still undecided. |
| **F-23** | carry the gate's anomalous fraction. A gate with four anomalies in six measured links is a candidate for being misplaced, and reads today as four separate discoveries<br><br>**✅ SHIPPED v3.2.91.** `context.gate_anomalous_share` carries the gate's lifetime measured links beside its anomalous count. The detector-side work this finding turned out to need shipped separately — see F-2026-08-26-01 through -04. |

**Order inside B:** F-2026-08-16-01 first, then the rest of F-16 — they are the
same field, and the 16th's fix was applied to one of the two routes that read
it. F-03 leans on both. F-09, F-22 and F-23 are independent.

**Why this one goes to the front:** every other item in B makes the bundle say
*more*. This one stops it saying something false — it currently offers, as the
gate's own history, a number the event itself wrote. An outside reader used it
to compute a threshold and a margin, correctly, and reached a confident verdict
from a circle. Fix what misinforms before what under-informs.

**F-22 and F-23 must ship together.** Grouping by receiving gate is right, but
a misplaced gate would then manufacture apparent openings from everything it
hears — so the fraction that disqualifies such a gate has to exist before the
grouping starts trusting gates.

**Cheap check before writing any of F-22:** how many gates saw 2+ distinct
senders inside the 30-minute window, against how many produced a recorded
opening? The gap between those two numbers is the size of the finding.

**The earlier run, 2026-08-17 — superseded by the measured red at the top of
§B.** Kept because it is where the check earned its place, not as the baseline
to work from: it sampled 7 links where the 2026-08-21 run sampled 12, and its
numbers below (6 of 7 links, largest multiplier 23x, drift 1–8 samples) are the
narrower picture. **Use the 2026-08-21 figures — 43 problems across 12 links,
drift 1–21 — as the red this package has to clear.** `tools/check_prop_bundle.py`
asserts the three things this package has to make true, and run against the
live bundle on 2026-08-17 it reported every one of them broken:

```
checked 6 of 7 anomalous links
largest published multiplier: 23x  (SQ8MAE-9 -> SR8MBR-1)

FAIL  at_flag has no sigma_km / threshold_km, so the bundle cannot show
      what the distance was compared against
FAIL  divides 446.3 km by an ema of 19.5 km — a denominator below the
      300 km floor cannot bound the result
FAIL  gate_baseline has 407 samples against at_flag's 399. The extra 8
      arrived after the flag, so the baseline offered as this gate's own
      history includes the event it is judging
```

Every link sampled failed all three, and the sample-count gap is between 1
and 8 depending on how busy the gate is — the drift is not an edge case, it
is what the bundle does. Writing the check first means the fix is provable in
one command instead of by reading JSON and hoping.

**Scheduled:** the week of 2026-08-24. Not for technical reasons — the change
is a day's work — but because it edits `station_db.py`'s hot path and the
class of mistake it invites is the invisible kind: a wrong baseline looks
exactly like a right one. That is work for a fresh session, not the end of a
long one.

**Files:** `station_db.py` (`_prop_links.append`, `gate_baseline`,
`find_prop_event`), `web_gui.py` (`get_prop_evidence`).

**Risk:** low. Additive fields plus one wording change.

**Verify:** a link whose printed baseline says it should not have been flagged
must also carry the baseline that did flag it, and the two must differ in the
direction the caveat describes. Additionally: `gate_baseline.samples` must never
exceed `at_flag.samples`, and no published multiplier may have a denominator
below the 300 km floor.

**Note:** F-03's measurement needs a few days of data after the field ships.
That waiting period is the reason to start B soon even though A matters more.

---

## C · Text and ergonomics — cheap, ride along with A or B

| finding | change |
|---|---|
| ~~**F-14b**~~ | ~~sharpen the symbol caveat: *the symbol is a fixed setting chosen when the station was configured; it does not change with conditions and reports nothing about the current weather.* A caveat has to close the inference, not name the source~~ — **already shipped**: the caveat now says FIXED SETTING and closes with "a rain-cloud icon does not mean it is raining" |
| ~~**F-10**~~ | ~~split the export prompts into the three questions that actually have different answers~~ — **already shipped**; both `sil_prompt` and `prop_prompt` ask three numbered questions and say why the answers differ. The row survived its own fix |
| ~~**F-12**~~ | ~~`?blind=1` to omit the whole `assessment` block server-side, plus a "copy blind" action, so a blind pass never depends on hand-editing JSON~~ — **shipped in v3.2.71** |
| ~~**F-15c**~~ | ~~move the copy feedback into the button itself~~ — **closed by F-19 in v3.2.14** |

**Risk:** none worth naming. Text, one query parameter, one small piece of UI.

---

## E · Non-independent stations in a silence cell — new, and it feeds D

**F-25.** In EN03 all four silent stations arrived through one gate, and two
pairs sit roughly a hundred metres apart. The gate was **alive**, so the cause
fell through to `outage` — the most alarming label available — for four
observations that cannot fail separately. `shared_gate` only fires when the
shared gate is silent or untracked; the case where the gate is fine and the
dependency is still total has no label at all.

The cell counts four stations. It is looking at two sites behind one path.

| change |
|---|
| carry, per cell, how many **distinct sites** and how many **distinct gates** the silent set actually represents |
| decide whether the ratio's denominator should count sites rather than callsigns — this is F-04's question in a sharper form |

**Check first, before any code:** four co-located `…SVR`/`…SVS` pairs arriving
through a single gateway look like one upstream feed rather than four radios.
Confirmed while writing F-25 that they are *not* APRS Objects — those are
already excluded — so what they actually are is worth one query.

---

## D · Silence threshold calibration — whenever

**F-04.** `min_silent = 3` and `min_ratio = 0.5` have never been measured
against anything. Fourteen days of `silence_history` are available now, so this
needs no preparation — only someone's attention. It is an analysis, not a code
change, and its answer may well be "leave them alone", which is a perfectly
good outcome to have on record.

---

---

## H · "What is the weather" — ✅ SHIPPED in v3.2.76 / v3.2.77

Same shape as §G and shipped with the same template method. The gateway held
live readings from thousands of APRS weather stations and answered every
weather question by pointing people at a forecast service.

Answered from `station_db.nearest_wx()`, not the model, because a reading is
only meaningful with two numbers a model reliably drops when it summarises:
**how far away it was taken and how old it is.** Both are template fields, so
neither can go missing. A city name is refused rather than geocoded — there
is no gazetteer here, and the wrong Izmir is worse than no answer.

`tools/check_weather.py` holds distance present, age present, nothing
reported past the radius, no city guessed, and a spent daily quota still
answering.

### Three things the build turned up

**The daily ceiling was gating the whole service, not the bill.** Its own
docstring says it exists so nobody wakes to an API invoice. A template answer
sends no invoice, and with the check in front of everything an exhausted
ceiling silenced answers that cost nothing. It now guards only `_ask_ai`.

**The radius had to be measured, not guessed.** Shipped at 100 km; the live
registry then showed 235 stations within 100 km of this operator and *not one
of them measuring weather*, with the nearest that did at 213 km. At 100 km
this instance would have refused every weather question in the region it was
built for. Now `wx_radius_km`, default 250.

**Weather does not survive a restart.** SQLite carries 24 station columns and
none of them start `wx` — readings live in memory only. After each deploy the
registry has no weather at all until every station sends its next *weather*
packet, which is not the same as its next beacon: 396 s after restart TA3ONK-13
had beaconed and still carried nothing, while K5WNG was back in 54 s. Not
filed as a fault — live weather arguably should not be persisted — but it
means the first weather question after a restart can honestly answer "none in
my records" while a station 200 km away is transmitting one.

## G · "Where is my other radio" — ✅ SHIPPED in v3.2.75

The first night of public use produced this, and it is the one question the
gateway is uniquely placed to answer and does not:

```
WD4ITE-15>DMWGPT: Where is WD4ITE-9
DMWGPT>WD4ITE-15: WD4ITE-9's position is not available to me directly.
                  For live APRS location, check aprs.fi or findu.com.
```

The registry holding 175,000 stations — position, last heard, locator, symbol,
gate — is inside the same process that produced that answer.

**The current answer is not wrong.** It is correct and unambitious, which is
why this is an addition and not a fix, and why it gets the higher bar.

### What could go wrong, in the order that matters

**It turns a general assistant into a people-finder.** The data is public and
aprs.fi already serves it, but a chatbot that answers *"where is XX1YYY"* is a
different social object from a map somebody chose to open. Tracking another
operator is not a hypothetical concern in this hobby.

**Stale data arrives in the present tense.** The registry says *last heard three
hours ago at X*; a model handed that position will say *"XX1YYY is at X"* and
drop the qualifier. This is the fault this project has spent weeks removing —
a figure that describes one thing presented as though it described another.

**Our view is partial and sometimes wrong.** We know what our feed saw, and we
have measured the positions themselves: 5.8 % fall outside the area their own
callsign prefix is allocated to, and some sit at exactly 0,0.

**A data channel invites invention.** The gateway has already claimed a
restriction it did not have. Give it a lookup and an empty result becomes an
opportunity to fill the gap.

**Scope creep.** After *where* comes *who is near me*, *has it moved*, *tell me
when it appears*. That is a different product with different obligations.

### The line

All of the risk is in third-party lookup. None of it is in asking about
yourself — and the sender's callsign is already in the packet header, so who is
asking is known rather than claimed.

| | |
|---|---|
| **Safe** | the sender's own callsign — *is my beacon getting out, when was I last heard* |
| **Defensible** | another SSID of the sender's own base callsign — the WD4ITE case above |
| **Out of scope** | anything else |

### The design: keep the model out of it

The invention risk is not manageable by prompt. If the question names a
callsign whose base matches the sender's, **the answer is built from a template
and the model never sees the request**:

```
WD4ITE-9: 36.85N 76.06W (FM16su), heard 14 min ago via <gate>.
Source: this station's own feed. Full history: aprs.fi
```

Base does not match — one fixed line, no model:

```
I do not give out other stations' positions. Try aprs.fi or findu.com.
```

That buys four properties a prompt cannot: the age is a required field rather
than something a model may drop, the source is stated as *our feed* rather than
authority, an empty registry says *not in my records* instead of guessing, and
the scope cannot drift without a code change.

**Explicitly not in scope:** proximity search, movement history, notifications,
third-party lookup.

### What shipped

Exactly the safe half, and nothing beyond it. A question naming the sender's
own base callsign is answered from the registry by a template with no model
call at all; another operator's callsign gets a flat refusal; anything else
follows the ordinary path to the model. `tools/check_selflookup.py` holds all
four of those, plus the rule that a position never travels without its age.

Proximity search, movement history, notifications and third-party lookup
remain out of scope, and the check is what keeps them out.

### Why it was parked

Not for technical reasons. The service is in the middle of a public argument
about whether it belongs on the air at all; adding a capability that looks like
tracking, in that week, would be answering a fair question with a worse one.
Nothing is lost by waiting — the answer it gives today is honest.

**Order:** after B. Revisit when the discussion has cooled.

## I · Per-gate range mapping — DRAFT, operator's idea 2026-08-22, nothing agreed

**The question as asked:** can each igate's range be mapped from the cumulative
signal data, RX and TX?

**Answer: RX yes, and the measurement is already happening. TX no, and that is
not an effort question — the data does not exist in the feed.**

### RX · the boxes are already being ticked, then thrown away

Every `qAR`/`qAO` packet is one measured RF path: the sender's in-packet
position to the gate's known position. On the live feed that is roughly
**23,000 measurements an hour across 7,877 gates**. All of it collapses into
three numbers per gate and the rest is discarded:

```python
self._gate_stats[gate] = [count, ema_mean, ema_var]
```

The only missing ingredient is **direction**. Distance is computed
(`_haversine_km`); bearing is computed nowhere. So this is not new data
collection — it is keeping a dimension of a measurement already being taken.

Shape, if it goes ahead: per gate, 12 sectors of 30° or 16 of 22.5°, each
carrying a sample count, a maximum, and a high percentile. The percentile
matters more than the maximum — one misconfigured GPS sets a maximum forever,
which is the whole reason `PROP_MAX_KM` exists.

Two known traps, both already paid for once:

- it must not walk the registry on the event loop (v3.1.2, then v3.2.10 again)
- it must survive a restart the way `export_gate_stats` does, or the map is
  empty every time the service is deployed — the same in-memory lesson that
  F-2026-08-22-02 just cost us

### TX · not in APRS-IS, and not in this agent

APRS-IS records only who **heard** a packet; that is what the `qAR,GATE`
construct means. What an igate transmits to RF never enters the feed. Nor can
this agent measure its own: `fixed_beacon` sends over TCP to APRS-IS, and there
is no transmitter in the system.

Any "TX range" drawn from what we have would be a guess wearing the clothes of
a measurement — the exact failure class Package B was spent removing.

**But there is real TX data, for a different device.** A digipeated packet
carries the digi's callsign in its path (`WIDE1-1*`). When a gate hears that
re-transmission, the **digi → gate** leg is a genuine transmit path. Those
packets are currently excluded outright (`digipeated` → no `rf_direct`,
`packet_parser.py`), because the link engine wanted one clean RF leg. So:
TX range is impossible for igates and available-but-unused for digipeaters.
Worth deciding deliberately rather than by omission.

### The hard part is not the data — it is what an empty sector means

A gate's map is shaped by **where stations happen to be**, not by where it can
hear. No stations to the south means no measurement to the south, which is not
the same as no coverage. That is F-2026-08-16-01's mistake in a new costume:
the absence of data read as a fact about the world.

So it has to be in the design before the first line is written:

- a measured sector is drawn; an unmeasured one is drawn as **visibly
  unmeasured**, not as zero range
- every sector carries its own sample count
- one sector with three samples and one with nine hundred must not look alike

### What it would feed

A range rose is a strong detector for a **misplaced gate**: uniform 400 km in
every direction is far more likely a wrong position than a remarkable aerial.
That is exactly what F-23 wants (a gate's anomalous fraction) and what makes
F-22's grouping safe. If this is built, it should be built knowing it serves
those two.

### Where it would live

**Not a new tab.** The natural home is the station detail panel when the opened
station is a gate, plus an optional map overlay for a single selected gate.

### Why this is on the list at all

"Not on this list" says no new features, and that rule is right. The argument
for this one is that it adds no new surface and no new collection: it keeps a
dimension of an existing measurement, renders it inside an existing panel, and
its first customer is an open finding about gates whose positions cannot be
trusted. If that argument does not hold, this belongs below the line instead —
that is the operator's call, not a decision to be made by writing the code.

**Priority as drafted:** after the rest of B. F-03's measurement clock started
2026-08-22 and wants a few days of data before the floor branch can be judged,
and this fits that window without competing with anything.

**Open before anything is built:** sector count (12 or 16); percentile or
maximum; whether anomalous links are excluded from the envelope (a tropo
opening is not a gate's normal reach) or drawn as a separate ring; and whether
the digipeater TX leg is in scope or explicitly out.

---

## Not on this list

- **New features.** The surface is already wide: map, silence, propagation,
  missing stations, quakes, evidence export, nine extensions. Maturing means
  making those trustworthy, not adding a tenth thing.
- **Anything the AI note says.** Its weakness is structural, not a wording bug.
  Once A lands, the open question is whether the note should describe only what
  it measured, or stop producing prose at all and emit structured claims the
  interface renders. That is a design decision, and it belongs to the operator,
  not to me.

---

## E · "Stations" in the stat bar counts the session — 2026-08-15

The Web GUI's stat bar labels the run counter as **Stations**. It starts at
zero on every restart, so twenty seconds after a deploy the interface tells a
visitor the network holds 1,641 stations, and four hours later it says 40,000
— while the registry has held ~173,000 the whole time. Nothing about the label
says which of those two numbers it is.

This was caught twice from opposite directions on the same day.

The first was `/api/counters`, written for the landing page. Its first version
reported the same run counter under the same name; measured 26 seconds after a
deploy it read **1,641 against a registry of 173,659** — a factor of 90. Fixed
before it shipped (v3.2.51): `stations` is the registry, and the run counters
stay as `heard_this_run` / `calls_this_run`, named for what they are.

The second was the landing page's own screenshot. The crop happened to place
the app's stat bar — *37,717 Stations* — directly above the page's registry
count of *173,754 stations on record*. Same word, two numbers, four lines
apart. The screenshot was re-cropped; the interface was not.

So the fault is the map's cluster-badge fault again, one layer up: **a number
that describes how recently the process restarted, presented as a description
of the network.** It has now been found in the badges, in a new API, and in
the stat bar. Worth assuming there is a fourth.

| change |
|---|
| relabel the stat-bar figure as **Heard (session)** / **Duyulan (oturum)**, or show the registry total beside it |
| whichever is chosen, the i18n strings and the public page's copy of the bar both need it |

Small and self-contained. The reason it is written down rather than done is
that the *right* answer may be to show both numbers, and that is a layout
decision on a bar that is already full.

---

## F · "AI: active" while the gateway could answer nothing — ✅ BUILT 2026-08-18

The AI Gateway raised an exception on every message it received for most of a
day. `/api/info` reported `active.ai: true` the whole time, the badge row on
both the admin and public pages showed the module lit, and the only sign
anything was wrong was a log line that stopped appearing — which nobody was
watching for, because you do not watch for absences.

`active.ai` is computed from configuration alone:

```python
ai_ok = bool(ai_cfg.get("enabled")
            and (ai_cfg.get("provider") or ai_cfg.get("base_url")))
```

That is an honest answer to "is this feature switched on", and it was being
read as "is this feature working". The two are not the same claim, and this is
the third time that distinction has cost something on this project.

| change |
|---|
| have the extension record its last outcome — answered, refused by a limiter, or raised — and let the badge reflect it |
| decide what an extension that has never been exercised should show: *configured* is not *working*, but neither is it *broken* |

The badge does not need to become a health monitor. It needs to stop saying
one thing when it knows another. A third state — configured, not yet
exercised — is probably the whole fix.

### What was built

Four states where there were two, and the missing one is `idle`:

| state | dot | means |
|---|---|---|
| `off` | grey | not enabled, or no provider configured |
| `idle` | yellow | configured, and nothing has asked it anything since the agent started |
| `ok` | green | the last thing asked of it was carried out |
| `error` | red | the last thing asked of it failed |

`idle` is the honest default and the whole point: a gateway nobody has
messaged since the restart is neither proven working nor broken, and the old
badge asserted the first.

**The state lives on the `Extension` base class, not in the gateway.** The
severed constructor was one possible cause; anything raising inside `handle()`
was hidden the same way, and `ExtensionRegistry.broadcast()` already catches
every one of those in a single place. It marks the extension there, so this
covers extensions that have not been written yet.

**The provider path needed marking separately.** `_ask_ai` catches its own
exception and returns `""`, the sender gets silence instead of a stack trace,
and `handle()` returns None. That is a second route to exactly the §F failure
and a likelier one than a severed constructor — a dead API key produces it.

**A limiter refusing is `ok`, not `error`,** and `tools/check_health.py`
asserts it. A badge that cries wolf when a rate limiter does its job gets
ignored, and an ignored badge is the state this started in.

`active.ai` stays a plain bool. It means *configured*, four other readers
depend on exactly that, and widening it would change what they think they are
being told. The new claim went in its own `health` block beside it.

The failure reason is admin-only — it is written by whatever threw and an
HTTP client's message can carry the request URL. The state itself is public:
somebody messaging this gateway is entitled to know it is broken.

**Related:** the fault itself was self-inflicted (a constructor's tail severed
by an insertion, v3.2.52) and now has a guard: `tools/check_unreachable.py`.
That prevents this particular cause. It does nothing about the reporting,
which would have hidden any other cause just as well.
