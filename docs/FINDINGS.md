# Findings log

A running record of what the software got wrong, how it was found, and what it
earned. Kept because the same lesson arrived twice from different directions
before anyone wrote it down.

Entries are appended, never rewritten. A finding that turns out to be mistaken
gets a correction line, not a deletion — see F-2026-08-12-07 for why.

---

## How a finding gets made

Most of these came from one method, which is worth stating because it works
better than reading the code:

1. Export the evidence bundle for something interesting — a silence cell, a
   propagation link — using the ⬇ / 📋 actions on its popup.
2. Paste it into an AI that has never seen this project.
3. Read the answer looking for **one** thing: where did it go wrong?
4. Ask the only question that matters:

   > Is this the model's fault, or the file's fault?

A model that reasons badly from good data is the model's problem, and there is
nothing to do. A model that invents something because the file did not tell it
is **the file's problem**, and that is a product improvement waiting to be
written down.

Two refinements learned the hard way:

- **Vary the model, and prefer one that is not related to the model that wrote
  `assessment.note`.** DeepSeek read a note written by deepseek-v4-flash and
  repeated its unverified claim. Gemini, unrelated, invented its own errors
  instead of inheriting ours — less flattering, more informative.
- **Run it blind first.** Delete the `assessment` block before pasting, so the
  model reaches its own conclusion before seeing ours. Then show it the note
  and see whether it moves. If it moves toward a note that was wrong, the note
  is anchoring readers rather than informing them, and you have just measured
  the damage. On a silence bundle `cell.cause` is a second, quieter conclusion
  — blank that too for a strict blind pass. Keep `detection`: parameters are
  not conclusions.

### What a good reading looks like

The third test (ChatGPT, F-09) invented nothing, did the threshold arithmetic
by hand, noticed that a σ of 285 km against a mean of 66 km makes a baseline
incoherent rather than merely unestablished, and put its confidence on a
*negative* claim — 97% that this was **not** demonstrably an opening.

Compare the second test, which put 73% on a *positive* claim and manufactured
the support for it. The difference is not intelligence, it is which direction
the confidence points when the evidence is thin. A reading that gets more
certain as the data gets thinner is the signature to watch for, in any model
and in any of us.

Note also that a clean reading still produced two findings. It did not find a
mistake; it found the questions the file could not answer, which is the more
useful failure.

---

## Open

> **F-01, F-11, F-13 and F-14a closed in v3.2.12** — package A of
> [NEXT.md](NEXT.md). They are left here rather than moved to Closed, because
> the reasoning across the four is what made the order obvious and it reads
> better together. Live afterwards: two cells took the new `shared_gate` cause,
> both gated by T2 backbone servers, which never appear as stations and so can
> never be confirmed silent. Both would previously have alerted as regional
> outages.

### F-2026-08-12-01 — the AI note asserts simultaneity it never checked  ✅ v3.2.12
**Source:** DeepSeek, silence cell JN28 (France) · **Verdict:** our fault

The generated note read *"Multiple igates and a digi went silent
**simultaneously**, suggesting a regional infrastructure or power outage."* The
per-station figures in the same bundle:

| station | silent for |
|---|---|
| F4LCL-13 | 42 min |
| F4MES-R | 3.4 h |
| F4MES-B | 3.4 h |
| F4BNZ-9 | 4.2 h |
| F4DYK | 11.4 h |

A power cut produces near-simultaneous onset. A spread from 42 minutes to 11
hours is the opposite signature. DeepSeek repeated "aynı anda" in its headline
while printing that table itself — it anchored on our word instead of its own
arithmetic.

**Earns:** the note should state the measured spread instead of claiming
simultaneity, and the spread belongs in the bundle as its own field
(`onset_spread_s`, or earliest/latest onset) so no reader can miss it.

### F-2026-08-12-02 — an unestablished gate baseline invites the opposite reading
**Source:** DeepSeek, propagation link HB9EM-10 → DJ8KL-2 · **Verdict:** our fault

The bundle reported `samples: 4, established: false, mean_km: 924.7,
sigma_km: 127.6`. DeepSeek reasoned from the mean anyway and concluded the gate
was built for long distances, so 701 km was normal for it — and raised its
confidence on that basis.

Both halves are wrong. With EMA alpha 0.05, four samples leave the mean
essentially at the first distance ever seen; it is not an average range. And if
701 km really were normal for that gate, that argues the link is *un*remarkable
— the opposite of what it was used for. The link was flagged precisely because
the gate has no usable baseline, so the absolute floor decided alone.

**Earns:** when `established` is false, say plainly that mean and sigma are not
meaningful yet and that the absolute floor made the decision. Handing over
numbers with only a quiet flag beside them is an invitation to misread.

**Addendum — `established: true` is misleading too.** A later reading
(KC7YRA-9, gate at 5 samples, mean 2041.6 km) makes the arithmetic plain: the
EMA is seeded with the first distance ever seen and moves at alpha 0.05, so
after five samples the "mean" is still essentially that first packet. Alpha
0.05 needs roughly 20 samples to travel two thirds of the way to a new level
and about 60 to settle — while `gate_min_samples` is **20**.

So a gate crosses into `established: true` at exactly the point its mean is
only two thirds of the way to being a mean. The flag reads as "this baseline
can be trusted" and the number underneath is still dominated by early
observations. That is the same defect as the unestablished case wearing a
reassuring label, and it compounds F-21: an early outlier both inflates σ and
persists in the mean long after the gate is declared established.

Whatever replaces the statistic should have its convergence and its
"established" threshold agree with each other.

### F-2026-08-13-15 — the copy button fails because the event loop is blocked, not because of the clipboard
**Source:** operator, propagation and silence popups on the live map · **Verdict:** our fault
**Closed: v3.2.10.** `silence_cells()` now runs in an executor behind a shared
cache whose window scales with the measured build, and the bundle is fetched
when the popup opens so the click never waits on the network. Measured on the
live server afterwards: ten calls through Apache, worst 1.3 s, most about
0.15 s, **none over two seconds**; `/api/silence` went from stalling the loop
for roughly half a second to 0.10–0.13 s. Items 1 and 2 below are done; item 3,
feedback inside the button, is not.

The button appeared to do nothing and show nothing. Both halves were wrong
diagnoses of mine; the Apache access log settled it.

**The requests arrive and succeed:**

```
23:39:13  GET /api/silence/evidence?cell=OM73   200  5256 bytes
23:39:57  GET /api/silence/evidence?cell=OM73   200  5257 bytes
23:40:26  seven identical requests in one second, all 200
```

Seven clicks in a second is an operator pressing a button that is not
answering. The data reached the browser every time.

**But the endpoint is intermittently very slow.** Three consecutive calls
through Apache:

```
attempt 1: HTTP 000, timed out at 40 s
attempt 2: HTTP 200, 6.2 s
attempt 3: HTTP 200, 0.6 s
```

**Why.** `silence_cells()` costs **0.3–0.9 s** on the live registry — measured
at 165,730 stations producing 2,146 cells — and it is called **synchronously on
the event loop** in three places:

| line | caller |
|---|---|
| 685 | the monitor loop |
| 1823 | `/api/silence` — the map's regular poll |
| 1887 | `/api/silence/evidence` — the export |

So every map poll stops the loop for about half a second. Add `/api/stations`
at 1.3 MB (four times in one second in the same log) and `/api/prop`, and the
loop saturates. Individual requests then take seconds, or hang.

**This is v3.1.2 repeating.** That release fixed `/api/stations` with a cache
and an executor and left `silence_cells()` synchronous; v3.2.0 then copied the
synchronous call into the evidence endpoint.

**And that is what breaks the clipboard.** Chrome closes the user-activation
window if the promise handed to `clipboard.write` resolves too late. A fetch
that takes six seconds loses it, the `writeText` fallback loses it for the same
reason, and all that survives is a failure message at the very bottom of the
page — measured at 400+ px below the popup, dark on dark, for 2.2 seconds. The
operator reported "no warning" twice and was right in every way that matters.

**Fix, in order:**

1. **Move `silence_cells()` off the event loop and behind a short shared
   cache.** The map poll and the export compute the identical thing seconds
   apart. Same treatment `/api/stations` got in v3.1.2, adaptive window
   included. This is the actual defect and it degrades the map, the station
   list and everything else that shares the loop.
2. **Fetch the bundle when the popup opens**, so the click writes data already
   in hand and depends on no network at all.
3. **Move the feedback into the button** — "Copying…" then "Copied ✓" or the
   failure, where the eye already is. No message at the other end of the page
   can be relied on.

**Method note:** three rounds of this were diagnosed from the client side, and
all three were wrong. The access log answered it in one read. When a browser
symptom resists explanation, ask the server what it saw.

### F-2026-08-13-21 — one outlier blinds a gate: `mean + 4σ` defeats itself
**Source:** external reading, propagation link EA5URX-7 → EA5CKO-10 · **Verdict:** our fault

```
gate_baseline : mean 274.6 km,  sigma 839.2 km,  threshold 3631.5 km
link          : 3369.6 km
```

σ is **three times the mean**, and the threshold that falls out of
`max(3*mean, mean + 4*sigma)` is 274.6 + 3356.8 = 3631.4 km. So for this gate
nothing under 3,631 km can ever be flagged — not even a link at twelve times
its own mean. The reader put it exactly right: *practically extraordinary, yes;
anomalous by this rule, no.*

The mechanism is worse than the caveat we already ship. That caveat says a
permanently unusual gate "slowly becomes its own normal and stops being
flagged". This is not slow. With EMA variance at alpha 0.05, a single large
outlier lifts σ far enough to push the threshold up by thousands of kilometres
**immediately**, and every genuine opening the gate sees afterwards falls under
it. The rule that is supposed to find outliers is disarmed by the first one it
meets.

That the link is in the bundle at all means it was flagged on some other basis
— the absolute floor while the gate was still unestablished, or a baseline
that has since moved. Which one is unanswerable today, and that is **F-16**:
the numbers shown are not the numbers that decided. The two findings should be
fixed together, because F-16's recorded-at-flag-time values are also what would
let anyone measure how often this blinding happens.

**Earns:** a distance baseline needs a statistic that one outlier cannot
capture. Options worth measuring before choosing — median with MAD instead of
mean with σ, a cap on how far σ may exceed the mean, or working in log
distance, where the spread of RF path lengths is better behaved. All are
detection changes and none should be picked without the data F-16 unlocks.

**Also, a second instance of F-18.** `EA5URX-7` carries a Spanish prefix while
reporting a mid-Atlantic position, gated to eastern Spain. The reader gave the
physical path 55% — appropriately low, since 3,369 km of terrestrial VHF is
not a thing. A stale or wrong position explains it far more comfortably, and a
prefix-versus-position field would have said so outright.

### F-2026-08-13-20 — the detector counts callsigns, not sites
**Source:** ChatGPT, Gemini and DeepSeek independently, silence cell LN04 · **Verdict:** our fault

All three noticed the same thing, unprompted, and it is a detection defect
rather than a presentation one:

```
R6YBU     44.61267, 40.06567
R6YBU-D   44.61267, 40.06567   gate_of -> R6YBU
R6YBU-Y   44.61267, 40.06567   gate_of -> R6YBU
R6HABA-10 (elsewhere in the cell, different untracked gate)
```

Three of the four "silent stations" are one physical site with three SSIDs.
ChatGPT: *"those four are not four independent radio sites"*. So "4 of 5
silent, ratio 0.8" is really **two sites**, and `min_silent = 3` was satisfied
by a single operator's equipment.

This matters beyond one cell. The threshold exists to stop one igate or one
power strip raising a regional alarm — and a multi-SSID site walks straight
through it. In a small cell it also inflates the ratio enough to clear 0.5 on
its own. **It is very likely a large part of F-17**: cells that alert forever
because one chronically quiet site is counted three times.

**Earns:** count *sites*, not callsigns. Deduplicate by position — identical or
near-identical coordinates are one installation — for both `silent` and
`baseline`, and say in the bundle how many distinct sites the numbers
represent. Position rather than base callsign, because one operator may
legitimately run a home igate and a mobile in the same cell, and those are two
real sensors.

**Not a same-day change.** This alters what the detector counts, so it needs
its own measurement first, and the measurement is cheap: how many alerting
cells shrink below `min_silent` once co-located callsigns collapse to one? That
number decides whether this is a tidy-up or the main story behind F-17. Run it
before writing anything.

**A second observation from a later reading of the same cell**, and it may be a
finding of its own. `R6YBU-D` and `R6YBU-Y` are absent in **305 of 305**
snapshots — not merely often, but *every single time a snapshot was taken*.
Yet they qualify for the baseline, which requires at least five packets and a
sighting inside the last 24 hours.

A station that has never once been present at snapshot time is not a sensor;
it is noise with standing. Either it beacons so rarely that its smoothed
interval misrepresents it, or it beacons in bursts that the sampling always
misses. Either way, counting it in `baseline` inflates the denominator and
counting it in `silent` inflates the numerator, at the same time. Worth
measuring alongside the co-location question: how many baseline members have
never appeared as present in any stored snapshot?

**Also recorded: v3.2.12 is working in production.** The gate attribution let
all three models reach a specific, correct answer — a single site's igate down
for 19.5 hours — where the same shape of cell previously read as a regional
outage. And the note itself now carries the history: *"[igate_failure/high] All
silent stations share a single silent igate, and their chronic absence across
all snapshots indicates the igate is persistently down"*. That sentence is F-11
and F-13 working together in a real notification.

### F-2026-08-13-19 — repeated clicks stack, and a stale request still fires
**Source:** operator, propagation popup · **Verdict:** our fault
**Severity raised the same day: this can wedge the page, not merely annoy.**

Second report, cell LN04: copies and downloads all failed, and then *the page
would not even reload*. Checked from the server at that point — service active,
load 0.62, `/api/info` 23 ms, `/` 4 ms, `/api/silence/evidence?cell=LN04` 575 ms
and HTTP 200, with the operator's own LN04 requests logged as 200. The server
was fine; the tab was not.

Stacked clicks leave several unresolved promises handed to
`navigator.clipboard.write`, and a browser holding those can stop responding to
the page — including a reload. So this is not cosmetic queueing: it is a path
from "clicked twice" to "the interface is unusable".

**And worse than first written: closing the tab did not clear it. Restarting
Chrome did.**

That places the wedge above the page. My first guess was the **service worker**
— per origin, outlives the tab, in the path of every shell request.

**That guess was wrong, and the operator disproved it during an actual
freeze.** `chrome://serviceworker-internals`, captured mid-wedge, for both
registrations:

```
Installation Status : ACTIVATED
Running Status      : STOPPED
Renderer process ID : 0
```

`STOPPED` is the normal idle state. A worker holding something would be
`RUNNING` with a live renderer process. The service worker is not the culprit.

**Better hypothesis, and it fits every observation:** Chrome keeps one HTTP/2
session per origin and holds it open for reuse across tabs. Requests that are
never settled *and never aborted* occupy concurrent streams on that session.
Fill them and every new request to that origin queues client-side — including a
page load, including from a fresh tab — while other sites remain fine because
the pool is per origin.

**Corrected again: it also clears on its own.** A later freeze recovered with
no tab closed and no browser restart. So the earlier "only a browser restart
fixed it" was the restart coinciding with the drain, or short-cutting it. That
fits stream exhaustion better than anything permanent: the hung requests
eventually time out, their streams are released, and the origin becomes usable
again. The lockout is temporary — which lowers the alarm without changing the
verdict, because a monitoring page that locks the operator out for minutes at a
time is still not acceptable.

**Confirmed: the freeze lasted two to three minutes** — the time the operator
spent opening `serviceworker-internals` and reporting it — and the page was
working again on return. That is the drain of ordinary request timeouts, and it
completes the picture: nothing is permanently stuck, a batch of un-aborted
requests saturates the origin's connection and the browser recovers once they
expire. Diagnosis closed; the fix stands as the guard plus `AbortController`.

It also explains the thing that puzzled me: during the freeze the server was
measurably healthy and the access log quiet, because the requests **were never
being sent**. That is directly checkable next time at no cost: if the Apache
log shows nothing from the operator's address while the page is frozen, the
queueing is client-side and this is confirmed.

**This changes the fix.** A sequence token that ignores a stale result is not
enough — ignoring a response leaves its stream open. The request has to be
genuinely cancelled with an `AbortController`, so the stream is released. The
in-flight guard prevents the pile-up; the abort clears what is already there.

The consequence stands regardless of which component holds the lock: **a
monitoring page whose recovery step is "restart your browser" is not
acceptable**, and this is now the first thing to fix, ahead of everything.

It also changes the shape of the fix. An in-flight guard in the page is
necessary but may not be sufficient: the guard must stop the situation
arising, because there is no cheap recovery once it has. Worth reviewing at the
same time whether the service worker's navigate handler can be left holding a
promise that never settles — its fallback races a 6 s timeout and then returns
`net`, which is exactly a promise that may never settle.

Reported: repeated copy attempts on one line, plus one download, and then the
last attempt copied successfully *and* performed the earlier download at the
same moment.

Nothing is cancelled or superseded. Every click starts work that will complete
eventually, and each completion performs its side effect regardless of how
stale it has become — so a slow moment queues them and they all land together.
The prefetch helps the common case and does nothing for this one, because the
single prefetch slot is consumed by the first click and every later click
issues its own request.

**Earns, one change closing two things:**

- an in-flight guard per action, so a second click while one is running does
  not start another;
- a sequence token, so only the newest request's completion is honoured and a
  stale one quietly does nothing;
- the button reporting its own state — "Copying…" then the outcome — which is
  **F-15 item 3**, still open, and which makes the guard visible instead of
  mysterious. A disabled-looking button explains itself; a click that does
  nothing does not.

### F-2026-08-13-18 — the callsign says one country, the position says another
**Source:** Gemini (inferred), propagation link HB9UFL-8 → OH7LZB-12 · **Verdict:** a field we could add

Three models read the same link. Two concluded the RF path was "plausible but
unverifiable"; one went further and noticed something checkable:

> The callsign prefix `HB9` belongs to Switzerland. However, the self-reported
> sender coordinates (55.73° N, 10.05° E) place `HB9UFL-8` in Denmark.

The gate is in central Finland. A 1,265 km terrestrial VHF path is
extraordinary; a misconfigured or stale position is ordinary. Every propagation
bundle carries the caveat that a wrong position produces a wrong distance and
the station will not know it — and here was a way to actually test it, which we
did not offer.

**Earns:** derive the country from the callsign prefix (ITU allocations are a
fixed table) and from the reported position, and state both. When they disagree,
say so plainly in the bundle.

**Important limit, and it must ship with the field:** a mismatch is not proof of
error. Amateurs legitimately operate portable and mobile abroad, and that is
exactly the sort of nuance an outside reader will not supply for itself. The
field should read as "prefix allocated to Switzerland, position in Denmark —
consistent with portable operation abroad, or with a stale position", not as an
accusation. Getting that wording wrong would repeat F-14: a fact stated without
closing the inference it invites.

### F-2026-08-13-17 — an alert should mean a change; ours means a state
**Source:** ChatGPT, Gemini and DeepSeek independently, silence cell OM72 · **Verdict:** our fault
**This outranks the rest of package B. It is F-04 arriving with its answer attached.**

Three unrelated models, given the same bundle under the new three-question
prompt, reached the same verdict without being led there. ChatGPT put it most
sharply:

> the strongest signal in the dataset is actually a persistent
> detector-selection bias toward chronically quiet stations

OM72 has **494 stored snapshots and all 494 are alerting**. The cell has been
in alert state for its entire recorded history. The same calls recur —
BH6ALJ-6 in 429 of them, BH6AJG-15 in 423, BG3OTT-11 in 421 — with onsets
scattered across tens of hours and no shared gate.

Our `alert` flag answers "does this cell currently satisfy min_silent and
min_ratio". It does not answer "has anything changed", and those are different
questions. A cell whose normal condition satisfies the rule alerts forever, and
the operator is notified about a state rather than an event. The `context`
block added in v3.2.12 lets a reader *notice* this — all three quoted it — but
noticing is not the same as the detector being right.

This is the third watch scenario written into [NEXT.md](NEXT.md), and it
arrived within a day: not "shared_gate climbing" but "cells still alerting
forever, and the alert itself is the artefact".

**Replicated, then measured.** A second cell, OL44, produced the same verdict
from the same three models — 211 of 211 snapshots alerting, four chronically
quiet stations across three untracked gates, no common onset. Six readings,
two cells, unanimous. So it was worth sizing:

```
alerting cells right now                    : 16
  alerting in EVERY stored snapshot         : 16   (100%)
  mixed history                             :  0
  no stored history yet                     :  0

across all 626 cells ever recorded          : 396 always-alerting (63%)
```

Not one cell alerting at that moment represented a change. The alert stream, as
it stands, does not report events at all — it reports membership of the set of
chronically quiet cells, continuously. That is a stronger statement than the
models made, and it is measured rather than inferred.

It also settles the option choice below. Option 1 would suppress *every*
current alert, which is itself the finding stated a different way. Option 3 is
plainly the correct long-term answer, but 63% of all recorded cells are
permanently alerting, so adopting it silences most of the map — a genuine
product decision about what this feature is for, not a bug fix.

**Earns, and this needs the user's judgement before any code:** an alert should
require a *change* — a cell entering the state, or worsening materially — not
merely being in it. Options, in rough order of intrusiveness:

1. Keep detection exactly as it is, and suppress *notification* for a cell that
   has been alerting continuously for N snapshots. Cheapest, reversible, and
   changes nothing about what the map shows.
2. Mark chronic cells in the payload (`chronic: true` plus how long) so the
   map, the alert list and the note can all say "ongoing, not new".
3. Change what `alert` means. Most correct, most disruptive — it touches the
   map, the history table's meaning and every stored snapshot's comparability.

Option 1 or 2 first. Option 3 is a detection change and would need its own
evidence, which is the mistake this project has already paid for once.

**Also recorded: the v3.2.13 text changes worked.** All three models answered
the three questions separately and gave *decreasing* confidence as the question
narrowed — the shape the split was meant to produce. And none repeated the
rain-shower inference; DeepSeek, which made exactly that mistake two days
earlier, did not mention weather at all. A caveat that closes the inference
behaves differently from one that names the source.

### F-2026-08-13-16 — the gate baseline in the bundle is not the one the decision was made against
**Source:** ChatGPT, propagation link IW4EGP-2 → IV3HQC-10 · **Verdict:** our fault
**Fix this with F-03: they need the same field.**

```
gate_baseline : samples 28, established true, mean 727.3, sigma 679.6,
                threshold 3445.8 km
link          : 870.5 km
```

The reader's verdict: *"the link is not even anomalous relative to this gate's
own baseline"* — and it is right. 870 km is nowhere near a 3446 km threshold.

So why was it flagged? Because the numbers shown are the baseline **after** the
link, and after the twenty-seven others that followed it. The decision used the
pre-update baseline — the code says so explicitly, and folds the outlier in
only afterwards so it cannot mask itself — but that value is never stored, so
the bundle reports today's.

The result is evidence that contradicts itself. A careful reader concludes the
link should not have been flagged, and is correct about the numbers in front of
them while being wrong about what happened. Our own caveat describes the drift
and the numbers are still presented as though they were the grounds.

**Earns:** record the gate's `samples`, `mean`, `sigma` and threshold **as they
stood at flag time**, on the link, and show both in the bundle — judged
against, and as it stands now. The gap between them is itself the interesting
part: it is the caveat made visible instead of merely asserted.

**Note the overlap.** F-03 is blocked on exactly this field: the calibration
question is how many anomalies came from gates with no usable baseline, which
cannot be counted without the sample count at flag time. One change closes
both, and neither is urgent enough to rush.

### F-2026-08-13-14 — a caveat that is read and then reasoned past is not strong enough  (distribution field ✅ v3.2.12; caveat wording still open)
**Source:** three models on silence cell OM73 (Henan) · **Verdict:** our fault, cheap

Same bundle, three readings. ChatGPT (~95%) and Gemini (85–90%) both opened
with `cell_history` — **567 of 567 snapshots alerting** across roughly two
weeks, with `BH6AJW-8` alone silent in 511 of them — and correctly called it
chronic non-visibility. DeepSeek (82%) said severe weather, and never mentioned
`cell_history` at all. A storm does not last a fortnight.

Two things it got wrong, and they are different in kind.

**The one to fix.** Four of the five silent stations carry the `rain-shower`
symbol. DeepSeek quoted our caveat that the type comes from the operator's
symbol choice, and then reasoned past it: *"it is still a meaningful signal —
these operators have deliberately set their equipment to report rain, strongly
implying that precipitation is actively occurring."*

It does not. The symbol is a **static configuration**, chosen once when the
station was set up. It does not change with the weather, and a rain-cloud icon
says nothing about whether it is raining now. Our caveat says where the field
comes from but never says the field is *fixed*, and that gap is exactly the
one a reader walks through.

**Earns:** say it outright — *"the symbol is a fixed setting chosen when the
station was configured; it does not change with conditions and reports nothing
about the current weather."* A caveat has to close the inference, not just name
the source.

**The one to leave alone.** It also built a west-to-east storm track from the
onset times. Checked against the data, that trend is *partly real* — four of
five fit, one steps westward — and one duration was misread (BD6ITP-11 is 6.6 h
silent, not the 4.1 h quoted). But the pattern being real does not matter here,
because the fourteen-day history makes any single-event explanation impossible.
The failure is not seeing a pattern; it is not looking at the field that made
the pattern irrelevant.

**Also earns, separately:** the reader should not have to scan 567 rows to
learn that this cell always looks like this. In this bundle `peak` equals the
*current* state — 5 of 8, ratio 0.62 — and every snapshot is alerting. One
field placing the current ratio inside the cell's own distribution would say
"this is unremarkable for this cell" in a single number.

**Worth recording as validation:** `cell_history` was added in v3.2.5 for
exactly this. The two readers who used it were right; the one who skipped it
was wrong. The field is doing its job for readers who read it, which is all a
field can do.

### F-2026-08-13-13 — the decisive fact is missing from the bundle, and the classifier reads its absence as an outage  ✅ v3.2.12
**Source:** ChatGPT, silence cell KO84 (Tula/Kaluga) · **Verdict:** our fault
**This is the one to fix first.**

Eight stations, up to 100 km apart, last heard within **nine seconds** of each
other. Both external readers inferred "a shared dependency" from that timing.
They were right, and the server knew the answer exactly:

```
CALL        LAST GATE     LAST SEEN
R3P-1       R3XBI         20:40:11
R3P-2       R3XBI         20:40:11
R3XBI-11    R3XBI         20:40:03
R3XBI-12    R3XBI         20:40:04
R3XBI-13    R3XBI         20:40:05
R3XBI-9     R3XBI         20:40:02
RC3XI-1     R3XBI         20:40:06
RK3X-1      R3XBI         20:40:07

distinct gates among the eight: {'R3XBI': 8}
gate R3XBI: NOT TRACKED in the registry
```

All eight arrive through one igate. And the same operator's `R3XBI-10` was
**still on the air** 444 seconds earlier through a different gate
(`T2CSNGRAD`). One path died; the region did not. A single row of data
falsifies the power-outage reading, and it is not in the bundle.

**Then the classifier makes it worse.** The igate discriminator asks:

```python
if gate_active(only_gate) is False:
    cause = "igate"
```

`gate_active()` returns `None` when the gate is not in the registry, and
`None is False` is false — so "I cannot confirm the gate is down" falls through
to `cause: "outage"`, the more alarming of the two. An untracked igate is not
an edge case: most igates never beacon their own position, so the common case
lands in the wrong bucket.

Four layers each made it worse than the last:

1. the bundle omits the gate attribution — the fact that settles it
2. the classifier cannot prove the gate failed, so it says `outage`
3. the AI note promotes that to *"regional power or infrastructure outage"* at
   **high** confidence
4. that note is what goes out over Telegram and email as an alert

And the cell has looked like this for about two weeks (F-11), so the operator
may have been alerted repeatedly to a regional power failure that is one
igate's internet connection.

**Earns:**
- put `gate_of` in the bundle — which stations came through which gate, and
  whether each gate is tracked and when it was last heard;
- give the untracked case its own cause instead of `outage`. All silent
  stations sharing one gate is strong evidence of a shared-path failure
  whether or not that gate can be seen; "one shared gate, not trackable" is
  both more accurate and less alarming than "regional outage".

### F-2026-08-13-11 — the AI note is written without the cell's history  ✅ v3.2.12
**Source:** ChatGPT, KO84 · **Verdict:** our fault

The note read *"[power_outage/high] Multiple igates and stations in the same
grid cell went silent simultaneously, suggesting a regional power or
infrastructure outage."* The same bundle's `cell_history` shows the same eight
callsigns in 13 of 13 snapshots spanning roughly two weeks.

`_assess_silence()` builds its prompt from the current frame only — cell,
counts, ratio, cause, silent callsigns, minutes since, cell context and quake
context. No history. So a chronic condition is diagnosed as a fresh event every
time it is assessed, and at **high** confidence.

Note the contrast with F-01: there, "simultaneously" was wrong because the
onsets were spread over 11 hours. Here the word is *right* — nine seconds — and
the conclusion is still wrong, because the missing axis is the other end of
time. Both fixes are the same shape: let the note see what it is asserting
about.

**Also:** the note contradicts the file it travels in. The caveats say *"No
APRS signal is a weak welfare signal, not a confirmed emergency"*, while the
note asserts a regional power outage at high confidence. A reader has to
decide which of our own two voices to believe.

**Earns:** pass the history summary into the assessment prompt, and require the
note to describe what it measured rather than name a cause it cannot see. The
distinction ChatGPT drew is the one to adopt: *the stations are unreachable* is
observed; *the power is out* is a hypothesis.

### F-2026-08-13-12 — a blind pass leaves a fingerprint
**Source:** running the two-pass method · **Verdict:** our fault, cheap

The method says to blank `assessment.note` before the first pass. Blanking only
the note leaves `"provider": "deepseek"` beside it, which still tells the
reader an assessment existed, was withheld, and whose it was. My instruction
was incomplete, and following it produced a bundle that looked — to me, for
several minutes — like a bug in our own code.

**Earns:** a `?blind=1` parameter that omits the whole `assessment` block
server-side, and a "copy blind" option beside the existing copy action, so the
pass never depends on hand-editing JSON. Until then: blank the entire block,
not just the note.

### F-2026-08-12-09 — `opening: null` says "not part of an opening" when it means "I did not look far enough back"
**Source:** ChatGPT, propagation link EA3GKP-10 → CQ0PSI-3 · **Verdict:** our fault

The reading was clean — no invention, correct arithmetic, and it refused to
call an opening on one sender. Its closing line asked for exactly the thing
that would change its mind: *another independent sender in the same field
within 30 minutes*.

That data existed and the bundle did not carry it.

- An IM opening **was** recorded at 20:25 with senders `EA3GKP` and `ED8YAC` —
  the same sender as the exported link.
- A stored event containing that exact `EA3GKP-10 → CQ0PSI-3` link exists at
  ts 1786562388. The exported link is ts 1786569244, **1.9 hours later**.
  `find_prop_event` searches ±1 hour, missed it, and reported `opening: null`.
- At the time of export, field IM held **9 anomalous links from 5 distinct
  senders** in the preceding 30 minutes. The opening was still running.

The cause is structural: one event row is written per episode, because
`_prop_active` suppresses re-alerting — but links keep arriving for hours
afterwards. Every link after the first hour of an episode reports "no opening".

And the field is ambiguous even when it works. `opening: null` currently means
"no recorded event containing this exact link within ±1 h", which a reader
takes as "this was not part of an opening". Those are different claims.

**Earns, as one change to the propagation bundle:**

1. **Live field context**, present whether or not a stored event matched: the
   other anomalous links in the same Maidenhead field within the opening
   window, and the count of distinct senders. For this link that would have
   read "9 links, 5 senders" and inverted the reader's conclusion.
2. **Repeat observations of the same sender→gate pair.** Measured on the live
   feed: 5 of 46 pairs appear more than once, at *identical* distances, spread
   over 5–9 minutes. Two packets making the same path is direct evidence
   against a one-off GPS fault — the exact doubt the caveats raise and then
   leave unanswered.
3. **Three states instead of one**: a recorded event exists / the rule is met
   right now but no event was written / genuinely a single sender.

Belongs in the same batch as F-03: both need the same part of the propagation
data, and neither should be rushed.

**A live instance to check when this is worked.** Two consecutive readings
covered the same gate, `VE7EPT-5`, reached by **two different senders** —
`W7BSB-1` at 1080.5 km and `NA7Q-1` at 997.8 km. Both were flagged anomalous;
both reported `opening: null`. Two distinct senders is exactly what the opening
rule asks for, so either their link midpoints fell in different Maidenhead
fields (the rule genuinely unmet, and the bundle should say which field each
one landed in), or this is F-09 again — an opening that exists and is not being
found. Worth resolving with a real pair rather than a hypothetical.

**A smaller oddity, noted in passing.** The gate reported `samples: 6` and
`mean 2043.4` in *both* readings, unchanged, despite a second link having been
gated between them. Either the two exports were taken close enough together
that the second link had not yet been folded in, or the baseline is not
advancing the way the code suggests. Cheap to settle once F-16 records the
values at flag time, and worth a glance then.

### F-2026-08-12-10 — the export prompt asks one question where there are three
**Source:** ChatGPT, same link · **Verdict:** our fault, cheap

The prompt shipped in `prop_prompt` asks whether the link "indicates a genuine
propagation opening and how confident you are" — one verdict. ChatGPT split it
on its own into three, and the three answers differed:

| question | its answer |
|---|---|
| is the link anomalous for this gate? | strong |
| is it an opening? | insufficient |
| was the RF path physically real? | uncertain — positions are unverified |

Collapsing those into one number loses the part an operator can act on. The
same applies to the silence prompt: *is this cluster real* and *is the cause
what the note says* are separate questions.

**Earns:** ask for the three separately in the prompt text. No code beyond the
i18n strings.

### F-2026-08-12-03 — propagation thresholds have never been calibrated
**Source:** carried from the 2026-07 backlog · **Verdict:** open work, data now ready

`PROP_MIN_KM`, `PROP_MIN_SAMPLES = 20` and the `max(3*mean, mean+4*sigma)` rule
were set by judgement, with a note to calibrate once real data existed. It
exists now: 7278 links measured, 71 anomalous, 2476 gates with baselines, and a
full distance histogram.

The question to answer with it: **how many of the 71 anomalies came from gates
below the 20-sample threshold?** With 2476 gates, most cannot have 20 samples,
so the absolute-floor branch may be producing the bulk of the output. F-02 is
the same gap seen from the reader's side.

**A strong hint arrived before the measurement.** Four consecutive propagation
bundles read by outside models showed gate sample counts of **4, 5, 6 and 12**
— every one below the threshold of 20, every one `established: false`. In all
four, what flagged the link was the absolute floor, not the statistical test.
The models said so themselves each time: *"the anomaly classification comes
from insufficient baseline data, not from exceeding the gate's normal distance
distribution."*

Four is not a measurement, but it points hard at the answer being "most of
them", which would mean the per-gate statistic is decorative in practice and
`PROP_MIN_KM` is doing the real work. If that holds, the honest options are to
lower `gate_min_samples` to something a gate can actually reach, or to stop
pretending the statistical branch is the primary rule.

**Blocked on one missing field.** Gate baselines live in memory only, and
nothing is written down when a link is flagged, so the question cannot be
answered from what is stored today — only the histogram, the totals and the
recorded openings survive. The preparation is to record the gate's `samples`
and `established` on each anomalous link at the moment it is flagged. That
changes no behaviour; it only makes the count possible. Then wait a few days
and the answer falls out on its own.

### F-2026-08-12-04 — silence thresholds have never been calibrated either
**Source:** security audit, 2026-08-12 · **Verdict:** open work, data now ready

`min_silent = 3`, `min_ratio = 0.5` are untouched since they were written. In a
live sample, 11 of 41 alerting cells were 3–4 station cells, where "3 of 3
silent" can be one igate or one power strip. There are now 14 days of
`silence_history` to measure against.

---

## Closed

### F-2026-08-12-05 — a bundle with no history invites an invented history
**Source:** Gemini, silence cell FJ13 (Colombia) · **Verdict:** our fault
**Closed:** v3.2.5

Told after the fact that the station was the last one still down from a cluster
outage, Gemini abandoned a correct answer and manufactured support for the new
one: that the other six had recovered, that a quake had struck and the USGS feed
was lagging, that a mountain-top site had exhausted its batteries. None of it
was in the file. Its confidence rose from 90% to 85% for a conclusion with less
evidence behind it.

The operator's framing was right — FJ13 did reach 7 of 8 stations silent, and
that callsign appears in all 37 stored snapshots. The reader could not know,
because the bundle was a single frame. A file that cannot answer the first
question anyone asks invites the reader to answer it themselves.

**Fix:** `cell_history` — snapshot counts, the peak silent/baseline ever
reached, a recent series, and how often each callsign was named silent.
Confirmed working: the next external reader used it unprompted to spot two
gateways that were silent in 371 of 377 snapshots and discounted them.

### F-2026-08-12-06 — station "type" reads as fact when it is a symbol choice
**Source:** Gemini and DeepSeek both · **Verdict:** our fault
**Closed:** v3.2.7

`type: "rain-shower"` sent the first reading of a D-Star node toward "routine
automated weather station". The field is derived from the APRS symbol the
operator picked, not from the equipment.

**Fix:** stated in the caveats of both the silence and station bundles.

### F-2026-08-12-08 — a test that stubs the function under test proves nothing
**Source:** operator, propagation popup on the live map · **Verdict:** our fault
**Closed:** v3.2.9

"Copy as AI prompt" put nothing on the clipboard and showed no warning. The
endpoint was healthy — the same link returned 200 with a full bundle.

Chrome resolves `navigator.clipboard.write` even when the promise inside
`ClipboardItem` rejects. That resolution was being read as proof the copy had
happened, so a failed fetch produced *"Evidence copied"* with the clipboard
untouched — inviting a paste of whatever was there before. The same shape as
F-2026-08-12 v3.2.1: a failed copy passing as a successful one, arriving
through a different door.

The reason it survived a test pass is the part worth keeping. The v3.2.7 test
did this:

```js
window.propEvidence = function(c,g,t,p){ called = {...} };
links[1].click();
```

It stubbed the very function it was testing. It proved the button was wired to
*something* and nothing whatsoever about what the button does. Only the success
path was ever exercised end to end; the four failure branches had never run.

**Rule:** never stub the unit under test. Stub its boundaries — fetch, the
clipboard — and let the real code run. Enumerate the failure branches
explicitly: server error, network failure, permission refusal, synchronous
throw, success. All five are checked now, across the three exports that share
the exporter.

### F-2026-08-12-07 — a pip resolver error lists the constraints of versions it rejected
**Source:** building the 32-bit Windows release · **Verdict:** my own error, published
**Closed:** corrected in the v3.2.4 release notes, `requirements-build-win32.txt` and here

A pip backtracking log was read as the current dependency cap and written into
release notes as fact: that every `atproto` release requires
`cryptography<46`. It does not — 0.0.69 requires `>=41.0.7,<47`. The `<46` lines
came from *older* atproto versions pip was searching through because
cryptography 48 has no 32-bit Windows wheel.

**Rule:** check `importlib.metadata.requires()` or the PyPI `requires_dist` of
the *installed* version before quoting a constraint. A resolver error describes
the search, not the answer.

The published release notes carry a visible correction rather than a silent
edit, because quietly fixing it would hide that the wrong version was out
there.

---

## Not findings

Kept here so they stop being re-discovered:

- **Noise at a wide-net detector is not a bug.** Quake correlation deliberately
  reports anything within 500 km and 24 h and leaves the judging to a reader.
  Nine unrelated matches in one day is that design working. The defect was the
  map popup showing a magnitude and a distance with no time offset — the
  presentation layer, not the threshold.
- **A single long link is not an opening**, and no amount of plausibility
  changes that. Two distinct senders in one field is the finding.
