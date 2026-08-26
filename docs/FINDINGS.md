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

> **F-34, F-35 and F-36 are one chain, found in one sitting.** The operator
> reported two symptoms: "copy still doesn't work" and "the American stations
> in Mongolia are still there". The second was already F-33, and is verified
> below. The first had nothing to do with the clipboard, and nothing to do with
> any of the three hypotheses NEXT.md was still carrying about the endpoint's
> speed. The feed had been deaf for twelve minutes, and every layer above it
> reported that as *nothing is silent anywhere*.

### F-2026-08-15-46 — F-03 answered, on a population that could finally accumulate
**Source:** the re-measurement F-43 said was impossible until baselines persisted · **Verdict:** measurement

Gate baselines survive a restart since v3.2.34. Twenty hours later **2,373 of
4,401 persisted gates (53.9%) have crossed the 20 samples** their own threshold
requires, the largest at 864. Before persistence that count was zero, always,
because every release reset it. F-03 could not be asked; now it can.

**Sample:** 200 live anomalous links, every one carrying its flag-time baseline
(F-16), against 169,335 measured links and 5,272 gates with baselines.

| | |
|---|---|
| flagged by the gate's **own** threshold (established) | **48 (24%)** |
| flagged by the **300 km floor alone** (young gate) | **152 (76%)** |

**The established 48 are real outliers by construction** — min 3.1×, median
6.7×, max 255.3× their own gate's figure.

**Of the 152 young-gate flags, 20 (13%) would still clear 3× if their gate were
established. 132 (87%) would not.** So the absolute-floor branch is 87% noise,
and it accounts for 66% of everything the detector flags.

**The earlier figure was 86%, and it was right by accident.** F-43 recorded that
measurement as invalid because every gate was young — and it was invalid, as a
statement about the detector. What it actually measured, the noise rate *within*
young gates, survives almost unchanged. The conclusion drawn from it — "the
detector is 86% noise" — was wrong then and is wrong now: a quarter of flags come
from gates held to their own standard.

### Crossed with position corroboration, which changes what the tail means

| | both consistent | contradicted |
|---|---|---|
| established-gate flags (48) | 62% | **17%** |
| young-gate flags (152) | 89% | **2%** |

**The strongest anomalies are eight times more likely to carry a position that
contradicts its own callsign.** That is the shape you would expect if wrong
positions manufacture large apparent distances, and it puts a number on it.

Five of the ten most extreme ratios are `contradicted`.

**One station accounts for four of them.** `DL5RBZ-9`, a German callsign,
reported **57.97 N, 37.08 E** — near Tver, Russia — at flag time, and produced
four ~1,900 km links to three Bavarian gates 23 km apart from each other. The
registry now holds it in Bavaria and consistent. A station does not move 1,900
km between beacons.

**Getting there took three attempts and two of them were wrong**, which is worth
recording:

1. The cross-tab said `contradicted`, so I wrote that the sender had a bad
   position — true, but unsupported at that point.
2. I checked the registry, found `DL5RBZ-9` consistent in Bavaria, and concluded
   the *gates* were at fault. Wrong.
3. Only the link's own stored coordinates settled it. The registry has moved on;
   the link kept what was true when the flag was raised.

That is F-16 justifying itself a second time. Without flag-time coordinates on
the link this station would have looked innocent and its four anomalies
unexplainable.

**Acted on, v3.2.45 and v3.2.46**, both the operator's choice:

- Floor-only links are drawn as the weaker claim they are — faint, thin, with a
  legend line and a popup that says which test judged them. Detection unchanged.
- Links whose own position contradicts their own callsign are dropped **before**
  the opening grouping, because the group is the midpoint of the two positions:
  a wrong position does not weaken the evidence, it files the link in a field
  neither station has ever been in. Only a positive contradiction removes a
  link; `unknown` stays, or a thin patch in the prefix table would silence real
  openings.

Tested against the case above: `DL5RBZ-9` reporting from Russia no longer
combines with an honest second sender to manufacture an opening, and the
exclusion is logged with its reason. Two honest senders still produce one; an
unrecognised prefix still produces one.

### F-2026-08-15-45 — the corroboration field found a fault on its first run
**Source:** verifying F-44 against live links · **Verdict:** our fault · **Open, small**

The first live batch of `position_corroboration` returned one `contradicted`:
`OE9XVI-6`, an Austrian callsign for Vorarlberg, reporting from **50.88 N,
12.13 E** — Saxony, 360 km north. The Austria box was checked first and is
correct; the position really is in Germany.

The record explains itself:

```
comment: {'source': 'DB0SLF', 'destination': 'OE9XVI-6', 'path': ['AP...
```

A third-party packet. `DB0SLF` is the station that actually holds that
position, and it was filed under the outer callsign.

**Scale, measured before calling it urgent:** 172,301 stations carry a comment,
85 of those carry a parsed dict rather than an info field, and 59 of the 85 have
an inner `source` that differs from the callsign it was stored under. Thirty
records in a hundred thousand — real, and not an emergency.

```
DB0SDA    <- ON3HJM-7      PY2KO-10  <- PU2NVX
OE9XVI-6  <- DB0SLF        EA1HJA    <- EB1LA-1
NE1CU-10  <- W1DMR-11      IQ3FX-11  <- IV3CTT-10
```

**The point worth keeping is not the bug.** It is that a field built to answer
one question — is this RF path real — surfaced a different fault nobody was
looking for, on its first pass over live data, because it was the first thing
to ask whether a position and a callsign agreed. Every one of these 59 records
has been quietly wrong for as long as the registry has existed.

### F-2026-08-15-44 — the third question had no evidence, and that was the file's fault
**Source:** six outside readings agreeing on the same non-answer · **Verdict:** our fault · **Closed: v3.2.44**

Six readings of propagation bundles were asked whether the RF path was
physically real. All six said the same thing at about the same confidence:
unverified, ~95%, because both coordinates are self-reported and nothing
corroborates them.

That answer is correct. It is also the file's fault: the one independent fact
available was never offered. A callsign prefix is allocated by country, and a
station's own transmitted position either falls inside that allocation or does
not.

`position_corroboration` now states it for both ends, and states the two
directions **differently**, because they are not symmetric:

| | |
|---|---|
| consistent | weak. It rules out coordinates invented at random. It does not rule out an error inside the right country, which is most errors |
| inconsistent | ambiguous. A wrong position and an operator transmitting away from home look identical from here |
| `0,0` | not ambiguous at all — an unset GPS, and any distance computed from it is meaningless |

**The first version of this was wrong and measuring caught it.** Applied to
147,307 positioned stations it reported **18% of the world as misplaced**. The
cause: it treated any identifier starting with a known prefix as a callsign, so
`TABOR`, `TAPIOLA` and `TAOSKI` were judged as Turkish stations. They are APRS
object names.

With a callsign-shape filter first — 1-2 characters, a digit, 1-4 letters — the
numbers become believable:

| | |
|---|---|
| positioned stations | 147,307 |
| actually callsign-shaped | 94,354 (64%) |
| the table recognises | 91,137 (96.6% of those) |
| consistent | 85,820 (94.2%) |
| **inconsistent** | **5,317 (5.8%)** |

A believable population of errors and travellers, and spot checks inside it
found two stations at exactly `0,0` and several at round-number defaults.

**Rule, and it is the same one as F-33:** before judging an identifier, check
it is the kind of thing you think it is. Two thirds of what this registry calls
a "callsign" is not one.

### F-2026-08-15-43 — I measured the detector and reported my own deploy cadence
**Source:** six outside readings, then the arithmetic that should have come first · **Verdict:** my error, and a real defect underneath it

Hours after reporting it, this correction matters more than the finding it
corrects.

**What I claimed.** That the propagation detector's absolute-floor branch is
78–86 % noise: of 83 flagged links, all came from gates below the 20-sample
threshold, 86 % would have fallen below an established gate's bar, 78 % did not
reach twice their own gate's figure.

**The measurements are right. The conclusion drawn from them is not.**

```
gate sample counts, 3.5 minutes after a restart
   1 sample : 10 gates
   2 samples:  8 gates
   3 samples:  1 gate
   highest  :  3        required: 20        gates at 20: 0
```

`_gate_stats` is **memory only** — nothing writes it to disk, nothing reads it
back. Every restart wipes every gate baseline. **I deployed eight times on
2026-08-14.** So gates were not young because the feed is young; they were
young because I kept resetting them, and then I measured the result and blamed
the detector.

**The real defect is larger than the one I reported.** If baselines never
survive a restart, and the service restarts on every release and is checked
hourly by the updater, then `PROP_MIN_SAMPLES = 20` may almost never engage in
production. The detector would be running permanently in floor-only mode — not
because the rule is wrong, but because the state it needs cannot accumulate.
Station records, cadence history and lifetime uptime all persist. Gate
baselines, the input to every propagation judgement, do not.

**The demonstration, unintentionally exact.** The same link, `EA6CA-3 →
ED6ZAB-4`, exported an hour apart:

| | samples | ema_km | ratio | would flag if established |
|---|---|---|---|---|
| before my deploys | 2 | 55.7 | **11.88×** | **yes** |
| after | 1 | 661.7 | **1.00×** | no |

Two confident, opposite readings of the same physical link. Both correct about
the file they were handed. The file changed because I restarted the process,
and the second baseline was re-seeded by the very link being judged.

**Rule:** before concluding anything from a distribution, check how long the
process producing it has been running. Uptime is a variable in every in-memory
statistic, and it was under my own control the whole time.

### F-2026-08-15-42 — five readings, one sentence, seventeen times the evidence
**Source:** operator, running the export-and-read method five times · **Verdict:** our fault · **Closed: v3.2.33**

Five propagation bundles went to an outside model. All five came back with the
same sentence at the same confidence: *"detector-anomalous, but a true
gate-specific anomaly is not established"*, 95 %.

One of those links was **0.69×** its own gate's figure — shorter than what the
gate normally hears. Another was **11.88×**, among the strongest outliers on
the feed. A seventeen-fold spread in the underlying evidence moved the verdict
not at all.

Both numbers were in the file. They were never in the same sentence, and
`established: false` did the rest: every reader took it as *nothing is known*
and stopped there. Four of four, then five of five, declined to divide one
number by the other.

**If a fact requires the reader to do arithmetic, it will not be read.** That
is the finding, and it is not about models — it is what a bundle is for.

`vs_gate_baseline` now states the relation outright: the ratio, the threshold
an established gate would face, and whether this link clears it.

**Confirmed by the sixth reading**, same model, same link, new field: the
verdict flipped to *"No, in the substantive gate-relative sense"*, with the
model noting the new evidence had materially changed its interpretation. The
prediction was made before the export and held.

**And F-24's cost, now visible.** Removing `mean_km` and `sigma_km` stopped
readers over-trusting a young baseline; it started them treating it as no
evidence at all. Weak evidence is not no evidence, and the caveat says so now.

> **F-38 through F-41 are one evening, and F-38 is the spine of it.** Three
> symptoms had been chased separately for weeks — a copy button that failed, a
> page that "died" and would not refresh, and an endpoint with an unexplained
> slow tail. They were the same fault. The operator said so before I measured
> it: *"the system rarely spikes but I hit the clipboard problem almost every
> time"*, which is a statement that server load is not the variable. It was
> right, and I went on measuring load for another hour.

### F-2026-08-14-41 — a backbone server is not a gate
**Source:** operator, looking at the map: *"is it a coincidence that the red and grey boxes are mostly side by side and land on China?"* · **Verdict:** our fault · **Closed: v3.2.31**

It is not a coincidence, and the test that settles it is cells per station
rather than cells.

| | stations | share | cells | share | over-represented |
|---|---|---|---|---|---|
| **China** | 10,427 | 6.1 % | **27** | **77.1 %** | **12.7×** |
| United States | 36,472 | 21.3 % | 1 | 2.9 % | 0.1× |
| everywhere else | 97,458 | 56.8 % | 5 | 14.3 % | 0.3× |

Density would put that last column at 1.0. So the question becomes what those
cells have in common, and the gate list answers it in one line:

```
T2HK 39 · T2YANTAI 30 · T2CS 23 · T2FZ 22 · T2NANJING 14 · T2JKTP 6 · T2TAIWAN 5
```

Every one an APRS-IS core server. Not one local igate among 27 cells.

**A station gated by `T2HK` was never heard by anybody's igate** — it opened its
own internet connection to the backbone, which is what a phone app or a
connected tracker does. Its silence is an internet or app dropout. All 27 cells
read `cause: outage`, a claim about a region's power and radio infrastructure,
with nothing whatever under it.

**And the detector could not see this, because the rotating pool disguised it.**
`rotate.aprs2.net` hands out a different T2 server on each reconnect, so four
internet clients in one grid name four different gates. `independent_gates`
averaged 4.2 on these cells. Four names, one backbone, zero independent
observations. `shared_gate` never fired because it looks for *one* gate.

**Fixed:** backbone gates (`T2*`) and self-gated stations are counted apart from
real ones; a cell with no independent local gate takes cause `backbone`, its own
colour, and no alert. Live: **23 of 36 cells reclassified, alerting 20 → 8**, and
every one of the 8 survivors has `independent_gates > 0`.

Two of the reclassified cells (`OL14`, `OL05`) fell out on **self-gating**
rather than backbone — Chinese Pi-Star hotspots, the same shape as NM58 half a
world away. The rule written that morning for F-25 caught them without being
aimed at them.

**This is F-25 one level up.** After "a callsign is not a witness", "a backbone
server is not a gate". Worth asking what the next level is.

### F-2026-08-14-40 — the service worker served old code, and no reload could escape it
**Source:** operator — *"F5 again, still 3.2.27, you're wrong again"* · **Verdict:** our fault · **Closed: v3.2.30**

The shell handler raced the network against a six-second timeout and served its
cached copy when the network lost. Six seconds is not "the server is broken", it
is "the operator is on a home connection".

Measured through the live site while the operator was stuck:

```
server answered /            0.012 s
Apache logged                200  55364 bytes delivered
Apache also logged           200  0 bytes      <- a zero-byte 200
page went on running         the previous release
```

**That `200 0` is the smoking gun**, and it is the worker's own abort: on losing
the race it calls `ctl.abort()` and answers from cache, which Apache records as
a 200 that delivered nothing.

**Why every escape failed.** A hard reload does not bypass a service worker.
Clearing site data does remove it — and then the next page load runs
`navigator.serviceWorker.register('/sw.js')` and puts it straight back. The
operator was told to clear and reload repeatedly; no sequence of those two
actions could ever have won, and that was knowable from the code before it was
asked of them.

**Fixed by removing the feature.** `sw.js` is now a kill switch — clears its
caches, unregisters itself, reloads open tabs — and the `register()` call is
gone from the page. Both halves are required: with the kill switch alone, every
load would install it, be unhooked by it, reload, and install it again.

An admin page for a live radio feed has nothing useful to show offline. Across
its whole life the offline shell delivered exactly one thing reliably: stale
code, twice tested against as if it were the current release.

### F-2026-08-14-39 — the copy was never a clipboard problem, it was a deadline
**Source:** operator, out of patience: *"how confident are you? most of my week went to this"* · **Verdict:** our fault · **Closed: v3.2.27**

Five releases had treated this as a clipboard problem. Measured on real clicks
in a Chromium build, one click per row:

| | API called first | activation after | `execCommand` |
|---|---|---|---|
| execCommand alone | — | live | **true** |
| API resolved → exec | resolved | live | **true** |
| +2 s delay → exec | — | live | **true** |
| **+6 s delay → exec** | — | **expired** | **false** |
| **API REJECTED → exec** | rejected | **live** | **true** |
| API rejected + 6 s | rejected | **expired** | **false** |

The fifth row killed my own hypothesis, which was that the refused API call
consumed the activation. It does not. **Only elapsed time does**, and the window
is about five seconds.

Against an endpoint measured between **0.101 s warm and 7.85 s cold**. So every
copy was a race against a five-second clock, lost *silently* — `execCommand`
returns `false` and says nothing. The popup prefetch usually won it; the
prefetch is single-use, so a second copy from the same popup refetched and
usually lost. "Almost every time" was the operator clicking twice.

**Fixed by taking the clipboard off the critical path.** The bundle is fetched
first and opens in a box with the text already selected; the copy is the
operator's own second gesture, with the data in hand. Verified against a bundle
deliberately delayed to 8 s — the case that previously failed every time:
activation expired, box open, text loaded and fully selected.

**The lesson is about the shape of the bug, not the API.** A failure that
depends on how long the network took will look intermittent, will resist every
client-side fix, and will pass every test run against a warm cache.

### F-2026-08-14-38 — a megabyte to draw thirty-two rectangles
**Source:** the Apache access log, after three wrong client-side diagnoses · **Verdict:** our fault · **Closed: v3.2.28 and v3.2.29**

The log answered in one read what a day of browser theories had not:

```
/api/silence   1,128,636 bytes   repeatedly, seconds apart
/api/stations  1,305,698 bytes   repeatedly
/api/config        3,266 bytes   queued behind them
```

`/api/silence` carried **2,135 cells; the page drew 32**. It has always
discarded the rest on arrival — it draws on `threshold_met && bounds` and lists
on `alert`, and nothing else in the page reads a cell. **98.5 % of a megabyte,
thrown away on receipt, on a poll that repeats every few seconds.**

`/api/stations` was a quarter empty keys: `city` and `district` empty on 100 %
of rows, `self_beacon` false on 100 % (80 KB), `ai_org` empty on 97 %,
`symbol_overlay` on 62 %, `freq_mhz` absent on 65 %.

| | before | after |
|---|---|---|
| `/api/silence` | 1,128,636 | **30,435** (37×) |
| `/api/stations` | 1,305,109 | **939,134** |
| per poll cycle | 2.43 MB | **0.96 MB** |

**And this is where the other two findings come from.** Those megabytes shared
one HTTP/2 connection with everything else: the 3 KB settings request queued
behind them (F-40's empty settings panel), the shell request lost the service
worker's six-second race (F-40), and the evidence endpoint's cold path stretched
past the clipboard's five-second window (F-39). One cause, three symptoms, three
separate hunts.

**Method note, and it is the same one as F-15.** Three rounds of this were
diagnosed from the browser and all three were wrong; the access log settled it
immediately. It is now recorded twice. *When a browser symptom resists
explanation, read the server log first — not third.*

**Second method note, and the more uncomfortable one.** The operator supplied
the decisive constraint hours earlier — *the system rarely spikes but the
clipboard almost always fails* — which rules out load as the variable and
points at something constant. I measured load, agreed the system was fine, and
carried on looking at load. A user's observation about their own usage is
evidence, and it deserves the same weight as a number I produced myself.

### F-2026-08-14-37 — a caveat cut in half, and nothing was checking
**Source:** reading an exported KM59 bundle · **Verdict:** our fault · **Closed: v3.2.26**

The v3.2.25 edit inserted two new caveats in front of a **continuation line** of
the `suspect_position` caveat instead of in front of a list element. Python
concatenates adjacent string literals, so it compiled, ran, deployed and shipped
in the Windows release without a murmur. Every exported bundle then carried:

```
"...this is the sender's error and not a decoding cell.silent counts
 CALLSIGNS, which are not witnesses. ..."
```

and, further down the array, the severed tail as a caveat in its own right:

```
"one, but if this number approaches 'silent' then the cell is not describing
 the region it is drawn on..."
```

So the one caveat explaining when a cell is **not** describing its own region
lost the clause that said so, and the fragment carrying that clause lost the
subject it referred to. The bundle is a document sent to strangers, and this
one had a paragraph cut in half.

**Two things worth keeping from it.**

*It was found by reading the output, not the code.* Three sessions had touched
this file that day. The defect surfaced the moment a bundle was actually read
end to end — which is the whole argument for the export-and-read method, now
demonstrated against our own work rather than a model's.

*Nothing could have caught it.* Adjacent string literals are valid Python, the
JSON was well-formed, the endpoint returned 200, and every test asked about
fields rather than prose. So v3.2.26 also adds the missing check: each caveat
must end in a full stop and must not begin in lower case unless it opens with a
known field name. That rule fails on the v3.2.25 output and passes on v3.2.26,
which is the only kind of test worth adding after the fact.

### F-2026-08-14-36 — the adaptive cache window has a floor, and the floor defeats it
**Source:** measured on the server while chasing the copy failure · **Verdict:** our fault

`silence_cells_cached()` holds its result for `max(2.0, build_s * 4)`. Its own
docstring says why the multiplier is there: *"a rebuild that takes longer than
its own TTL can never finish before the next caller starts another one."* The
floor puts that case straight back.

The window is set from the **last** build. A fast build grants a 2.0 s window;
the next build takes longer than that and has already outlived the window it
was given. Measured live, `/api/silence` once a second for 100 seconds:

| | |
|---|---|
| stations carrying a position | 145,135 |
| cells produced | 2,130 |
| answered from cache | 0.07–0.30 s |
| answered by a rebuild | 0.6–2.4 s |
| share that rebuilt | roughly one request in five |

So the walk over 145 k stations is, in practice, continuous.

**This answers the slowness NEXT.md was still carrying** — 1.7 s once, past 20 s
once. It was neither the `COUNT(DISTINCT ts)` nor the unindexed `cell` scans;
requests are queueing behind a rebuild that never stops for long. Third
hypothesis, and the first one that was measured on the server instead of
reasoned about in a harness. The `(cell, ts)` index shipped in v3.2.23 remains
free and remains beside the point.

**Second, smaller, and not biting yet.** An empty result is never cached: the
guard reads `if cells and now - built_at < …`, and `[]` is falsy, so every
caller during an empty stretch starts its own rebuild. Harmless today only
because the sole route to an empty result is the deaf guard below, which
returns in microseconds. It stops being harmless the moment an empty result
costs a full walk.

**Fix:** raise the floor — ten seconds is far more than the map needs — and
cache an empty result like any other.

**Measured after v3.2.24 shipped, and it is a partial result.** Same probe,
same server, 90 samples at 1 Hz against 2,125 cells:

| | before (v3.2.23) | after (v3.2.24) |
|---|---|---|
| median | ~0.15 s | **0.101 s** |
| p90 | — | **0.265 s** |
| over 0.5 s | ~1 in 5 | **7 in 90** |
| max | 2.4 s | **7.85 s** |

The frequency of the walk fell by roughly the factor the floor predicts, and
the common case is now firmly sub-quarter-second. **The tail did not go away**,
and one sample at 7.85 s is worse than anything seen before the change.

It was the *first* sample of two consecutive probes, which looked like a
cold-cache cost — and then it refused to reproduce: a deliberate 150 s idle
followed by a cold request measured 2.0 s, and the rebuild after it 0.086 s.
The server has other pollers (both map views) keeping the cache warm, so the
state at the moment of any given request is not controllable from outside.

**Recorded as open, not chased.** What is established is that the walk now runs
about a fifth as often; what is not established is what makes an occasional
rebuild cost eight seconds instead of one. That is a fourth hypothesis waiting
to be formed, and this endpoint has already retired three.

### F-2026-08-14-35 — the deaf guard is right, and invisible
**Source:** operator, "copy still doesn't work" · **Verdict:** our fault

`silence_cells()` opens by refusing to judge (`station_db.py:1370`):

```python
if self.last_ingest_ts and (now - self.last_ingest_ts) > 600:
    return []
```

That refusal is correct and should stay. If we have heard nothing for ten
minutes, everyone looks silent and none of it is true.

But `[]` is the same value as *nothing is silent anywhere in the world*, and
three consumers read it that way. At 09:17:12 on 2026-08-14, within one second:

| consumer | what it did |
|---|---|
| `/api/silence` → map | dropped all 2,130 cells |
| monitor loop | logged **28** `[silence] cleared` and **2** `[prop] cleared` |
| monitor loop | logged **5** `[silence] back on the air` — `BD1EOE-7`, `LU1HVK-R`, `BI7ALG-7`, `ARSTRA`, `HELIO` |
| `/api/silence/evidence?cell=NM58` | **404** `"no current silence data for NM58"` |

Nothing had ended. Nobody came back on the air. The feed came back.

**That 404 is the copy failure the operator reported.** Measured inside the
window: `/api/silence` answered `{"cells": []}` in 0.005 s; sixty seconds later,
2,130 cells in 7.09 s. The button did exactly what it was written to do — it
showed the server's message — and the server's message blamed the cell.

Worth being exact about what is wrong. The guard is not too aggressive, the
threshold is not too low, and the button is not broken. **The defect is that a
refusal to answer is encoded as an answer.** Three layers then reported that
answer to the operator as fact, and two of them phrased it as good news.

**Fix:** deaf is a state, not an empty list. While deaf, nothing is cleared,
nothing comes back on the air, the map says why it has no cells, and the
evidence endpoint says we cannot see rather than that the cell does not exist.

**Three mass clears remain unexplained.** Over the same 13 hours there were four
moments where five or more cells cleared in the same second, and only one had a
feed gap behind it:

| when | cells cleared | feed gap in the preceding 30 min |
|---|---|---|
| 2026-08-13 23:49:55 | 25 | none |
| 2026-08-14 08:04:22 | 14 | none |
| 2026-08-14 08:21:17 | 18 | none |
| 2026-08-14 09:17:12 | 28 | 729 s, ending 5 s earlier |

The service restarted at least three times across that window (PIDs 560568 →
599811 → 601269 → 603601) and the first three cluster near those restarts — but
a restart cannot produce this, because `_silence_active` lives in memory and a
fresh process has nothing to clear. A candidate without an explanation, left
alone on purpose: two earlier hypotheses about this endpoint cost a release
each.

### F-2026-08-14-34 — the feed can stop for twelve minutes without a single log line
**Source:** looking for what made the feed deaf · **Verdict:** our fault

`aprs_connection.py:172` reads the APRS-IS stream with `await reader.readline()`
and no timeout. A TCP connection that half-dies — the peer stops sending but
never sends FIN — parks there indefinitely. There is no read watchdog, and
nothing logs the wait.

Measured across 13 hours of journal and 3,773,541 logged packets, exactly three
gaps over 90 s:

| gap | when |
|---|---|
| 94 s | 2026-08-13 21:31:52 |
| **729 s** | **2026-08-14 09:05:08 → 09:17:17** |
| 95 s | 2026-08-14 09:24:05 |

Everything the process said during those twelve minutes:

```
09:05:18  [telegram] poll error: TimeoutError: The read operation timed out
09:12:12  [station-ai] DeepSeek peak-pricing window — deferring batch
09:14:58  [telegram] poll error: TimeoutError: The read operation timed out
```

Not one line about APRS-IS. The feed is the one input the whole product depends
on, and it is the only one with no liveness check on it.

Only the 729 s gap crossed the 600 s deaf threshold, which is why this became
visible at all. The two 95 s gaps passed unnoticed and unlogged, and would have
gone on doing so.

**Fix:** a read deadline on `readline()`, a log line when it fires, and a
reconnect after it.

> **Decided 2026-08-14, deferred to the next working window.** F-34, F-35 and
> F-36 are accepted as written and ship together — separately they are half a
> fix, and F-35 alone would make a silent stall merely quieter. F-33's second
> error gets a **`suspect_position` count carried on the cell** rather than a
> deletion: a station on the wrong continent should be visible as a doubt, not
> removed from a count the operator is reading. F-25 — counting sites and gates
> instead of callsigns — stays under consideration.

### F-2026-08-14-33 — NM58: a cell that exists only because of two counting errors
**Source:** operator, "the box is near Mongolia and the callsigns are American" · **Verdict:** ours to count, not ours to parse

A grey chronic cell in western China, 4 of 4 silent, holding `KC9SIO-B`,
`KC9SIO-D`, `KC9SIO-N`, `N3ARY-N`. Verified against live data:

```
KC9SIO-B  38.76N  90.799E   gateway   gated by KC9SIO-BS
KC9SIO-D  38.80N  90.799E   gateway   gated by KC9SIO-DS
KC9SIO-N  38.80N  90.799E   gateway   gated by KC9SIO-NS
N3ARY-N   38.48N  90.42E    gateway   gated by N3ARY-NS
```

**Two independent errors stack to produce this cell.**

*One — four entries, two owners.* Three of them are SSIDs of a single base
callsign, each gated by its own `-S` server: D-Star gateway modules, not four
radios. Collapsed to owners the cell is **2 of 4**, below `min_silent = 3`, and
would never appear at all. This is F-25 with a concrete live case, and it is
ours to fix.

*Two — the longitude sign.* KC9SIO is an Illinois callsign and N3ARY is US
east-coast; 38.6 N / 90.2 **W** is St. Louis. These gateways beacon **+90.8**
where they mean **−90.8**, a missing minus in the gateway's configuration,
which lands them in western China.

**That second one is NOT our bug**, and it was worth checking rather than
assuming. Both position paths were read: the uncompressed regex captures
`([EW])` and `_ddmm_to_decimal` negates on `S`/`W`; the compressed decoder uses
`lon = -180 + b91/190463`, where the sign is intrinsic to the formula. And the
decisive argument is not the code but the map: a parser that dropped the
hemisphere would mirror **every** western-hemisphere station, and the worldwide
distribution is plainly normal.

**This is also F-23 with its mechanism named.** "A gate whose links are mostly
anomalous is probably misplaced" now has a cause behind it: an operator omits
the minus, and every distance measured through that gate is wrong by half a
planet. Worth carrying into the F-22/F-23 package — a gate on the wrong
continent will manufacture openings from everything it hears.

**Verified against the wire, 2026-08-14.** The entry above reasoned the missing
minus out of the code and said so. It is now confirmed from the packets, with a
control. `comment` stores the info field verbatim (`packet_parser.py:744`), so
the raw beacon reads straight out of the registry:

| record | info field | result |
|---|---|---|
| `KC9SIO-B` hotspot | `!3845.58ND09047.94E&RNG0001/A=000010` | 90.799 **E** → NM58, western China |
| `KC9SIO-1` tracker | `/190018z3845.57N/09047.93W-PHG2051` | 90.799 **W** → EM48os, Missouri |

One operator, one site, the same coordinate to two decimal minutes, opposite
hemispheres. The parser is decoding exactly what was sent. **Not our bug —
confirmed now, rather than argued.**

**Scale.** US callsign, eastern longitude, *and* an MMDVM / D-Star / Pi-Star
signature in the beacon text: **178 stations across 92 grid squares**. Relaxing
the filter to callsign and hemisphere alone gives 610, but that sweep pulls in
objects and non-amateur identifiers, so 178 is the number to quote.

**Two details the original entry did not have.**

- The cell holds a *fourth* record, `KC9SIO B` with a space — the same hotspot
  re-beaconed as an APRS Object by `KC9SIO-GS`. It is already excluded by
  `is_object`, which is that exclusion doing its job.
- Every one of them is **self-gated**: `KC9SIO-B` arrives via `KC9SIO-BS`, `-D`
  via `-DS`, `-N` via `-NS`, `N3ARY-N` via `N3ARY-NS`. The gate is the station's
  own APRS-IS uplink, so `shared_gate` can never fire here — four beacons
  sharing one power supply present as four distinct gates. That is the sharpest
  form of F-25 so far: **a gate count does not measure independence when a
  station is its own gate.**

### F-2026-08-14-32 — `esc()` is a text-node escaper, and four sinks used it for attributes
**Source:** found while reading, chasing an unrelated question · **Verdict:** our fault · **Security**

`esc()` builds a text node and reads back `innerHTML`, so it escapes `& < >`
and **deliberately leaves quotes alone** — exactly right between tags, and
wrong inside an attribute, where one `"` closes the value and everything after
it is parsed as markup. Nothing in the name says which context it is for, so
call sites used it for both.

| sink | data | reachable by |
|---|---|---|
| `title="…"` on a message row | message text, packet-derived, unbounded | admin |
| `href="…"` on a station URL | URL from a beacon comment | admin + public |
| `title="…"` on a location cell | city/district | admin |
| inline `onclick` **and** the text, map popup | **Object name — no escaping at all** | admin + **public** |

**The last one is the sharp one.** `_RE_OBJECT` is `^;([^\*]{9})\*`: an APRS
Object name is nine characters of anything except `*`, and it **overwrites
`callsign`**. That value went into a JavaScript string built by concatenation —
the only place in the file that made code out of packet data. Nine characters
caps what fits, but the boundary was genuinely crossable, and it is reachable
from the public view by anyone who can put an object on APRS-IS.

That it was an oversight rather than a judgement is visible two hundred lines
away, where the same value is defended with
`String(r.callsign).replace(/'/g,'')`. The v3.2.3 audit closed the text-node
cases; the attribute cases survived because the helper looked like it covered
them.

**Fixed in v3.2.23.** A separate `escA()` for attributes, used at the three
`title`/`href` sites; and the popup no longer generates code at all — the
callsign travels in a `data-cs` attribute read by a delegated click, which also
survives Leaflet rebuilding the popup from a string.

**Verified against a real payload**, not a source read. With an object name of
`a"'<b>cde`: the value round-trips intact through the data attribute, renders
as text, produces no extra elements, leaves no `onclick` in the markup, runs no
script, and the detail click still receives the exact original string. The URL
and message-title sinks were each driven through their real functions with
`https://x" onmouseover="…` and the matching message text — attribute intact,
no handler injected, nothing executed. One further `title="'+ti+'"` was checked
and cleared: `ti` comes only from the i18n dictionary.

**The lesson is the name.** A helper that is correct for one context and
dangerous in another, with a name that mentions neither, will be misused — and
the misuse reads as careful code. `esc` / `escA` at least forces the choice to
be visible at the call site.

**Shipped alongside, and honestly a disappointment: the `(cell, ts)` index.**
`cell_silence_history()` runs four `WHERE cell = ?` queries per evidence
request and the primary key is `(ts, cell)`, so none of them could use it.
Adding the index was meant to explain an endpoint measured at 1.7 s live and
once over 20 s. Measured on 80 000 synthetic rows: **110.7 ms → 89.7 ms, 1.2×**,
with the plan confirming a covering index. Real, free, kept — and nowhere near
enough to account for what was seen live.

So **two hypotheses about that slowness have now been wrong**: first that my own
`COUNT(DISTINCT ts)` caused it (it can use the primary key, so no), then that
the unindexed per-cell scans did (1.2×). The cause is still unmeasured. The
remaining candidates are the registry walk behind `silence_cells_cached`
(0.3–0.9 s at 165k stations) and what happens on a cache miss when several
callers arrive at once — which is where the next measurement should start,
on the server rather than in a synthetic harness.

### F-2026-08-14-31 — chronic moves from "how often" to "the same faces"
**Source:** measurement requested by the operator · **Verdict:** improvement

Persistence never fired: measured across 38 live alerting cells the busiest
reached 0.63, nowhere near the 0.90 cut. Measuring the other axis — of the
times a cell alerted, how often was each station one of the missing — showed
why the question was wrong:

| cell | alerts in | same cast |
|---|---|---|
| FG46 | 7 % of runs | **0.99** |
| DM90 | 2 % of runs | **0.82** |
| DM34 | 5 % of runs | **0.87** |

A cell can alert almost never and still produce the identical set of silent
stations every single time. "How often does this cell alert" was never the
question; **"is this the same thing again"** is.

**Live distribution across the 38:** mean recurrence 0.80–1.00 in 14 cells,
0.60–0.79 in 16, 0.40–0.59 in 5, 0.20–0.39 in 3, none below 0.20. Seventeen
cells contained no unusual station at all; twenty-one contained at least one
below 0.35.

**Not degenerate, which was the worry.** Only 4 of the 38 had their whole cell
silent, so recurrence is not high by arithmetic. Partial cells still averaged
0.69.

**The minimum decides, not the mean** — and this is the part worth keeping.
GG57 averages 0.66, which reads as thoroughly habitual, and contains a station
at **0.06**: one that is almost never among the missing, silent now. The
average hides precisely the case that matters. So a cell is chronic when
**every** station currently silent is one it usually misses; one surprise is
enough to make it news.

**Shipped in v3.2.21**, threshold 0.35 (the operator's choice, from 0.35 vs
0.20 — 21 alerts survive rather than 12, and starting permissive is the safer
direction after being burned once by tuning on thin data):

- `recurrence` per silent station and `novel_stations` in the cell and the
  bundle, so the verdict can be checked rather than taken
- the popup names them: *"New here: BI1PZJ-3 — normally not among this cell's
  missing stations"*, which is the sentence an operator can act on
- the AI prompt gets the same, named, instead of inferring from how often the
  cell alerts
- `persistence` is still published — it is real, it just decides nothing now

**Cost:** history is read only for cells that met the threshold, a few dozen
rather than a few thousand, cached for a minute beside the persistence figures.

**And a smaller trap avoided on the way.** The first version published
`recurrence` for every cell, including the ones never queried — where it came
back as zeros, which reads as *"none of these stations is ever normally
missing"*, the strongest claim the field can make. Now it is omitted unless
the cell was actually measured. That is the fourth time in two days an
unqueried or tautological number nearly went out as a measurement; the pattern
is worth naming on its own: **a field that is absent is honest, a field that
is zero because nothing was asked is not.**
**Source:** operator, OM79 popup · **Verdict:** our fault

Reported: a popup reading **"Regional silence (possible outage)"** in red, with
the AI note underneath saying

> `[event_expired/high]` The cell has been alerting in **every snapshot**, and
> the silent stations are chronically absent, indicating this is normal state
> rather than a new outage.

The page contradicted itself — alarming colour, dismissive prose — and the
operator asked the right question: why do only cells with an AI note say
anything about being chronic, and why are they all still red?

**The AI was wrong, not the colour.** OM79 has alerted in **731 of 1761 runs —
42 %**. It is not chronic under any threshold.

It said so because `_cell_context_stats()` was fed `snapshots` and
`alerting_snapshots` from `cell_silence_history()`, and both counted the cell's
own stored rows. Only alerting cells are ever stored, so `alerting == snapshots`
was **true for every cell, always**, and the prompt asserted as fact:

> "this cell has been alerting in every stored snapshot — the current state is
> its normal, not a change"

Every cell's prompt carried that line. The model repeated it and stamped it
`/high`.

This is the third place the same construction artefact appeared — the evidence
bundle (F-26), the popup's persistence figure (fixed in v3.2.16), and now the
AI prompt. **This one was the worst of the three**, because it did not present
a number for a reader to weigh: it presented a conclusion, in prose, with a
confidence tag, to an operator who cannot see the query behind it.

**Fixed in v3.2.20.** `cell_silence_history()` now reports `snapshots` as the
number of snapshot **runs** since the cell was first seen, matching what the
cell list already does, and the prompt states the real ratio and draws the
right conclusion from it:

```
this cell has alerted in 400 of the 1000 snapshot runs taken since it was
first seen (40%). So it alerts intermittently, and has recovered in between
— do not describe it as permanently or chronically silent.
```

A genuinely permanent cell still reads as chronic; verified both directions.
Live notes are not persisted across a restart, so the deploy clears the stale
ones by itself.

**The lesson is about blast radius, not about the bug.** One wrong denominator
reached three surfaces, and the order in which they were found was the reverse
of the order in which they mattered: the JSON field first, the popup second,
and the sentence a person actually reads last. When a number turns out to be
meaningless, the question is not "where is it computed" but **"who repeats
it"** — and a model that has been handed a false premise will state it more
confidently than the field ever did.

### F-2026-08-14-29 — eight hours of data: `chronic` cannot fire, and the gate rule is right
**Source:** operator — "check what the alert definitions are worth now the data
has accumulated" · **Verdict:** measurement, two answers

**One: the chronic mechanism is inert.**

| | |
|---|---|
| cells meeting the threshold | 38 |
| cells reported as `alert` | **38** |
| cells reported as `chronic` | **0** |
| alerts caused by passing a cell's own peak | 0 |

Persistence across the 38: 23 below 0.25, 11 at 0.25–0.49, 3 at 0.50–0.74, and
one at 1.00 with only 21 snapshots — too young to qualify. The highest value on
a cell with real history is **0.725**, and among the long-lived cells
**0.625** (RE43: 1114 alerting of 1781 runs, ~12 days).

So nothing approaches the 0.90 cut, and `alert` is currently identical to
`threshold_met`. The redefinition shipped in v3.2.15 is, on this data, a no-op.
That is worth stating plainly rather than leaving as a quiet success.

Two readings are now consistent 8 hours apart: cells do not alert permanently,
they alert **intermittently**, topping out around 60–70 % of runs.

**Two, and this closes a question NEXT.md left open: the single-gate rule is
not too strict — shared gates are genuinely rare.**

Distinct gates behind each alerting cell's silent stations:

| distinct gates | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|
| cells | 1 | 5 | 13 | 11 | 3 | 2 | 2 |

Exactly **one** cell has all its silent stations behind a single gate, and it
is already labelled `shared_gate`. Relaxing the rule to "one gate carries the
overwhelming majority" would reclassify exactly one more (DM35, 80 %). Most
alerting cells have their silent stations spread over three or four gates,
which is not one path failing. **`outage` is doing honest work.**

NEXT.md had framed a near-zero `shared_gate` rate as evidence the rule was too
strict to matter. It is the opposite: the rate is low because the situation is
rare, and the branch fires exactly when it should.

**What to do about the 0.90 cut — the operator's call, with numbers now
attached.** Lowering it to 0.5 would demote three cells of 38 (RE43 0.625,
DM52 0.567, IM63 0.725). That may well be right: a cell alerting in 63 % of
1781 runs over twelve days is not reporting news. But two observations of one
night and one morning is still a thin basis, and the alternative — accepting
that `chronic` is dormant infrastructure that fires only on genuinely permanent
cells — costs nothing and misinforms no one.

**A better axis, recorded not built.** What the outside readings actually
objected to was never "this cell alerts often" — it was **the same callsigns,
every time**. A cell alerting 63 % of the time with the same three stations is
describing those three stations' habits, not a region. `silent_calls` is
already stored per snapshot, so "how many of the currently-silent callsigns
were also silent in most previous alerts of this cell" is computable today.
That is probably the measurement F-26 was reaching for, and persistence is a
proxy that happens not to discriminate. Belongs to F-04.

### F-2026-08-14-28 — the reload guard recorded intent, not outcome
**Source:** operator — "the VPS 3.2.17 in the Chrome window can't come back to
itself" · **Verdict:** our fault · **Confidence: plausible, not confirmed**

The version watch reloads a tab when the server reports a build newer than the
one the tab is running, with a guard against looping:

```js
if(sessionStorage.getItem('aprs.reloadedFor')===v)return;
sessionStorage.setItem('aprs.reloadedFor',v);   // written BEFORE the reload
location.reload();
```

The guard is keyed on the version it was *trying* to reach, and written before
knowing whether the reload arrived anywhere. So one failed attempt disables the
mechanism for the rest of the session.

**And there is a way for the attempt to fail that we built ourselves.** The
service worker answers a navigation from cache when the network loses a 6 s
race — which is exactly what a service restart looks like. A reload issued
during a deploy therefore comes back on the **old** build, with the guard
already set. The tab is then stranded on the old build until it is closed:
`sessionStorage` survives an ordinary reload, so reloading again cannot help,
which is precisely what "can't come back to itself" describes.

Three deploys inside fifteen minutes (v3.2.15, v3.2.16, v3.2.17) made that
window easy to land in, and the check also fires on `visibilitychange`, so
returning to the tab during a deploy is enough.

**Fixed in v3.2.18:**
- Bounded retries keyed on outcome: up to three attempts per version, spaced 90
  s apart. Enough to survive a restart, never enough to spin.
- The cached shell is deleted immediately before reloading, so the fallback has
  no old build left to answer with. `/api/info` answered moments earlier, so the
  network is known up; the cost if it drops inside that window is a slower load
  rather than a silently stale one, and the retries cover it.

**Verified** on the real function with only the reload counted: the first
attempt reloads and records `n:1`, an immediate second call is refused, a call
after the 90 s spacing reloads and records `n:2`, `n:3` stops entirely, and a
matching version touches nothing.

**The diagnosis was then checked, and it did not hold.** Three things came back
against it:

- `sessionStorage.getItem('aprs.reloadFor')` → `null`. I had also given the
  wrong key first: the old code wrote `aprs.reloadedFor`, so that was the one
  worth reading. It was `null` too.
- `window.BUILD` is injected correctly — the served page carries
  `window.BUILD="3.2.18"`, so the "the watch never ran" theory fails as well.
- The operator's own screenshot settles it: the legend in it contains
  "Long-standing, not a new event", an entry that only exists from v3.2.17. The
  tab **had** updated, and the page was live and counting.

So whatever "could not come back to itself" described, it was transient and had
resolved by the time the screen was captured — plausibly the two-to-three
minute HTTP/2 drain of F-19, or simply three service restarts inside fifteen
minutes. It is now unfalsifiable: `sessionStorage` is per tab and survives a
reload but not a close, and my own first advice was to hard-reload or reopen
the tab, which destroyed the only evidence that could have settled it.

**Two lessons, and the second is the expensive one.**

*Ask for the evidence before prescribing the cure.* The diagnostic line and the
fix went out in the same breath; the fix's side effect was to erase the data
that would have tested it.

*Three theories, none confirmed.* Stranded guard, missing `window.BUILD`, and
before those a service-worker theory the operator disproved. This is the same
pattern already recorded on F-19 — client-side reconstruction, confidently
argued, wrong — and it repeated here despite being written down. What actually
resolved F-19 was a server-side log; what actually resolved this was a
screenshot the operator had already sent.

**The fix ships anyway and is kept**, on its own merits: a guard that
suppresses retries based on intent rather than outcome is wrong regardless of
what stranded this particular tab. But it is a hardening, not a repair of a
confirmed fault, and the log should say so.

### F-2026-08-14-27 — the operator read the map better than the map read itself
**Source:** operator, live map · **Verdict:** our fault (three of them)

Two observations, and a question that turned out to be the sharpest of the
three: *"iGate failure and One shared gate are the same colour. And the grey
areas have no legend entry — you do realise that?"*

**1 — The legend listed two entries with identical swatches.** `igate` and
`shared_gate` were both `#f5c211`. That undoes exactly the distinction v3.2.12
existed to make: `igate` means the gate was *seen* to go quiet, `shared_gate`
means one gate carries every silent station and we cannot see it at all —
different evidence, different confidence. Worse than not distinguishing them:
the legend printed two separate lines with the same colour beside each, which
tells a reader the difference is real and then refuses to show it.
`shared_gate` is now orange `#ff7800`, on the map and in the alert list.

**2 — I shipped grey without a legend entry.** Chronic cells were drawn in
`#77767b` in v3.2.15 and nothing on the page said what grey meant. I was not
aware; the operator was. Added.

**3 — And looking for the legend found a regression I had shipped.** v3.2.15
changed the map to draw on `threshold_met` instead of `alert`, so chronic
cells would stay visible. But `load_silence_history()` reconstructs past
snapshots from the stored rows and emits only `alert` — no `threshold_met`. So
since v3.2.15 **every historical cell failed the filter and the timeline
replayed empty.** Fixed by emitting `threshold_met` from the stored column,
which is the raw threshold result and therefore exactly the right value;
`chronic` is reported false for a replayed instant rather than invented.

**The lesson is about where the check belongs.** Changing the field a renderer
filters on is not a local edit — it is a change to a contract, and the other
producer of those dicts is in a different file and a different language's worth
of distance away. The live view looked correct, which is why nobody caught it:
the regression was only in the replay, and the replay is the half nobody
watches while deploying.

Fixed in v3.2.17.

**And the fix had a tail, reported from the operator's own screen (v3.2.19).**
The legend sat at `bottom:50px` while the timeline occupied `bottom:8px` plus
about 54 px of its own height — the same band. The timeline is painted later,
so it covered the legend and cut the text in half. Adding a seventh entry did
not create the collision, it made it impossible to miss.

Both are now stacked in one bottom-anchored flex column, so neither can cover
the other and the legend drops to the map's edge when the timeline is hidden.
The legend also wraps instead of overflowing: seven entries no longer fit one
row on a laptop, and an eighth would not fit anywhere.

Measured at 1140 / 980 / 820 / 640 px: no overlap at any width, no overflow at
any width, the legend growing to two rows as it narrows, the timeline still
full width and still clickable, and the legend still transparent to clicks.

**Worth naming:** two absolutely-positioned overlays anchored to the same edge
have no relationship until one of them changes size, and then the one painted
later silently wins. A stacking context is the fix; measuring only the element
being changed is what misses it.

**Still open, and a deliberate trade-off rather than a bug:** the legend is
`display:none` below the mobile breakpoint. On a phone the map now has red,
orange, yellow and grey cells with nothing on screen saying what any of them
mean. That predates this work but the added colours make it matter more.

### F-2026-08-13-26 — a cell that has alerted in every snapshot it has is not alerting
**Source:** three silence readings, cells DN57 / EN03 / one more · **Verdict:** our fault

Three separate cells, three separate readings, one verdict — and the numbers
are what make it final:

```
DN57   198 / 198 snapshots alerting     3 silent / 6 baseline
EN03   860 / 860 snapshots alerting     4 silent / 5 baseline   (peak 9/9)
—      314 / 314 snapshots alerting     4 silent / 8 baseline
```

Every stored snapshot of all three has been in alert. The readings put
94–99 % on "artefact of station selection, not a new event", and the phrasing
of one of them is the finding itself: *the alert is essentially describing the
cell's long-standing monitoring state.*

**This is the evidence F-17 was waiting for, and it settles the measurement
half of it.** A cell alerting in 100 % of its history is not reporting an
event; the word `alert` is being spent on a permanent property of the cell.
The product decision — suppress, mark `chronic: true`, or redefine `alert` —
is still the user's, but it is no longer a decision without data. The ratio
that decides it is already stored: alerting snapshots over total snapshots, per
cell, and `cell_silence_history()` already returns it.

**Decided by the user: redefine `alert`.** I had recommended marking `chronic`
and leaving `alert` alone, and warned that redefining it would retroactively
change what the 860 stored snapshots mean. The user chose redefinition anyway,
and the objection turned out to be answerable rather than fatal — it was an
argument against redefining the *stored* value, not against redefining the
*reported* one.

**Closed: v3.2.15.** The split is the whole design:

- **`silence_history` still stores the raw threshold result.** The column keeps
  its original meaning, the 860 snapshots still say what they always said, and
  persistence stays recomputable. `record_silence_history()` calls
  `silence_cells()` with no history path precisely so it gets the raw value.
- **`alert`, as reported, is narrower**: the threshold is met AND either the
  cell is not chronic or it has gone past its own worst. Chronic is defined as
  alerting in ≥ 90 % of at least 12 snapshots spanning at least 24 h.
- **`threshold_met` carries the old meaning** so nothing is hidden, alongside
  `chronic`, `persistence`, `snapshots`, `alerting_snapshots` and `peak_silent`.

**Past its own worst still alerts.** That is the case plain suppression would
have hidden, and it is why option 1 was the wrong shape: a chronic cell going
from 4 silent to 10 is exactly when someone should be told.

**The map draws on `threshold_met`, not on `alert`.** Removing chronic cells
from the map would have been hiding the measurement rather than judging it, so
they stay — grey and fainter, with the popup saying "alerting in 860 of its 860
recorded snapshots". The alert panel, the notifications and the AI notes use
the narrow `alert`, which is where the noise and the cost actually were.

**Verified** against a synthetic history: a cell alerting in 900 of 900
snapshots is demoted while keeping its cause and shared-gate attribution; a
cell with five snapshots still alerts; the same chronic cell alerts again at 10
silent against a stored peak of 9; and with no history path the output is
byte-for-byte the old shape, which is what protects the stored column.

Persistence is read with one grouped query cached for a minute — it moves over
hundreds of snapshots, so rebuilding it per cell scan would be work for a
number that cannot have changed. If the history cannot be read, nothing is
chronic: an alert must never be narrowed away by a failure to read the very
evidence that would justify narrowing it.

**Corrected in v3.2.16, and the live deploy is what caught it.** The first run
on the VPS returned `persistence: 1.00` for all 39 threshold-met cells —
every single one, to two decimal places. A real measurement does not do that.

`record_silence_history()` stores **only cells that met the threshold** (line
1146; worldwide, storing every cell with one silent station produced 1000+ rows
per snapshot). So a cell's stored rows are all alerting rows, and
`SUM(alert)/COUNT(*)` is 1.0 for every cell **by construction**. It was not
measuring persistence at all, and the popup was telling the operator
"alerting in 857 of its 857 recorded snapshots" as though that meant something.

The honest denominator is how many snapshot **runs** happened since the cell
first appeared. Runs are shared — one pass writes the same `ts` for every cell
— so the distinct timestamps are the run log, and a cell's position in it is
one `bisect`. On the synthetic history the difference is the whole finding:

| cell | old | corrected | verdict |
|---|---|---|---|
| EN03, alerting in ~every run | 1.00 | **0.996** of 904 runs | chronic, correctly demoted |
| a cell alerting 20 times in a fortnight | 1.00 | **0.047** of 424 runs | **not** chronic — and the buggy version would have silenced it |

That second row is the damage the bug would have done: an intermittent cell —
the one thing a monitoring page must never suppress — read as fully persistent
and demoted. The regression test now covers it explicitly.

**Worth keeping as a rule.** Both the synthetic tests and the code review
passed this. What exposed it was a number from production that was too clean:
39 cells agreeing to two decimals is not a result, it is a tell. A ratio whose
numerator and denominator come from the same filtered set will always be 1.0,
and no amount of testing the arithmetic will show it — only asking what the
denominator actually counted.

**And then the corrected number dissolved F-26's own premise.** Measured
properly on the live VPS:

| persistence | cells (of 41 meeting the threshold) |
|---|---|
| below 0.40 | 29 |
| 0.40 – 0.74 | 10 |
| 0.95 – 1.00 | 2 — and both are younger than 24 h |

EN03, the cell three outside models called a chronic artefact on the strength
of "860 of 860 snapshots alerting", has alerted in **857 of 1787 runs — 48 %**.
It is intermittent, not permanent. Nothing currently qualifies as chronic, so
`alert` is back to 41 and the redefinition changes nothing in practice today.

**The readings were misled by our own export, and so was I.** "Alerting in
every stored snapshot" was true of every cell in the file and therefore said
nothing about any of them; all three models built their central claim on it,
at 94–99 % confidence, and I built a release on it. That is the export
actively misinforming a reader, which this project's own ordering puts above
everything else — and it reached the outside world before it reached us.

**Not retuning today.** The 0.9 threshold now has a real distribution behind
it and could plausibly move to 0.5, which would demote two or three cells. But
adjusting a rule on the same day its measurement was first believed is the
mistake already recorded against the quake radius, and one snapshot of one
evening is not a calibration. The numbers are the input to F-04; that is where
this belongs.

**What stands regardless:** the split between what is stored and what is
reported, `threshold_met` beside `alert`, the map drawing on the measurement
rather than the judgement, and a persistence figure that now means what its
name says. The mechanism is right even though its first premise was not.

### F-2026-08-13-25 — a shared gate that is alive still means the stations are not independent
**Source:** same three readings · **Verdict:** our fault
**Closed: v3.2.25**, as a qualifier rather than a denominator — the operator's
call, and the cheaper half of the right answer.

Cells now carry `sites` (distinct operators), `sites_colocated` (additionally
merged within 200 m), `independent_gates` and `self_gated`. A cell with fewer
than `min_silent` operators is demoted from `alert` to `threshold_met`: still
measured, still drawn, greyed like a chronic cell, with the reason in the
popup. No "past its own peak" escape hatch, unlike chronic — a cell that has
never held more than one operator does not become a regional outage by having
a worse day.

**Not the denominator, and the reason is cost.** Counting the *ratio* by site
would mean collapsing the baseline too, which means grouping every station in
the cell rather than the three-to-nine silent ones. The walk is already the
performance problem (F-36); the silent set is free, the baseline is not.

**The proximity count is reported and never applied.** A position cannot tell
a club site with two callsigns from two neighbours with separate power, and
collapsing the second case deletes a real independent witness. So it is
published for a reader and decides nothing.

**Predicted before deploying, then measured after.** The prediction was: eight
cells demote, `OL16` and `OM62` among them, and `PN36` **keeps** its alert
because it has three operators and only the unapplied proximity rule would
have caught it.

| | |
|---|---|
| demoted by `few_sites` | **8** — FG46, HH19, NM58, OI88, OL16, OM51, OM56, OM62 |
| any demoted cell still alerting | **none** |
| `PN36` | sites 3, colocated 2, **still alerting** — exactly the withheld case |
| cells with **no** independent gate at all | 3 — RE43, NM58, HH19 |
| cells proximity would collapse further | 6, one of them alerting |

Alerting went 11 → 10, not the 9 predicted, because the world moved between
the two samples: `OL16` and `OM62` dropped out as expected and a new cell,
`OM67` (14 silent stations, 14 operators), arrived. The rule did exactly what
was predicted on every cell present in both samples.

**NM58, the case that started this:** `sites` 1, `independent_gates` 0,
`self_gated` 3, `suspect_position` 3. Four separate reasons on record not to
call it a regional outage, where a fortnight ago it was one.

**What the next measurement is for.** Six cells would collapse further under
the proximity rule and one of them is alerting. That list, after a few days,
is the evidence for whether 200 m is the right radius and whether the rule
should ever be applied rather than printed.

In EN03 all four silent stations use gate `AE5PL-WX`, and two pairs are
effectively co-located — 43.78/-99.90 with 43.77/-99.88, and 43.69/-99.89 with
43.68/-99.89. The gate is **healthy**, last heard 720 s ago.

Because the gate is alive, `gate_active()` returns True and the cause falls
through to **`outage`** — our most alarming label — for what is plainly four
dependent observations behind one path. F-01's `shared_gate` cause only fires
when the shared gate is silent or untracked. The case where the gate is fine
and the dependency is still total has no label at all.

Two distinct things are being counted as independent and neither is:
- **co-located pairs** a hundred metres apart, which cannot fail separately;
- **one shared gate**, alive or not.

Checked while writing this: `is_object` **is** already excluded from silence
detection (station_db.py:1187), so these are not APRS Objects. What they are
instead is worth one query before any code — four co-located `…SVR`/`…SVS`
pairs arriving through a single gateway look like one upstream feed rather than
four radios, and if so the ratio's denominator is wrong at the source.

**Earns:** the bundle should carry, per cell, how many distinct sites and how
many distinct gates the silent set actually represents. Four stations at two
sites behind one gate is a different sentence from four stations going quiet.

### Provenance note for F-22 … F-24 — the readings were selected, not sampled
The four propagation readings behind F-22, F-23 and F-24 were **chosen by the
user**: every link they could find originating around GLENT, British Columbia,
put side by side so the correlation between them would be visible. There are
no others from that set.

This must be read two ways.

**It weakens nothing in the counts.** `samples: 6` and the anomaly figures come
from the gate's own counters; which links a human chose to export does not
change them. F-23 and F-24 stand.

**It is the stronger half.** Selecting by receiving area is exactly what F-22
proposes the code should do — group by the receiving gate instead of by the
midpoint's Maidenhead field. The user performed that grouping by hand, and it
immediately surfaced what four separate popups could not: one gate, several
unrelated distant senders, `opening: null` on every one. F-22 is therefore not
an untested proposal. It is a method that has been run once, manually, and
worked.

What must NOT be done with this set is treat the four readings as four
independent confirmations. They are one correlated observation of one area,
which is precisely why it was informative.

### F-2026-08-13-24 — `mean_km` and `sigma_km` are not a mean and a σ, and every reader has computed with them
**Source:** four propagation readings (VE7EPT-5 ×2, WA7GMX-8, KC7YRA-9) · **Verdict:** our fault

`WA7GMX-8` reported `samples: 6, mean 1466.2, sigma 0.0` on a 1466.2 km link.
The reading concluded, reasonably, that all six samples must be at the identical
distance. They need not be. From station_db.py:755:

```python
st = self._gate_stats[gate] = [0.0, dist, 0.0]   # first packet seeds mean, var = 0
st[1] = (1 - a) * mean + a * dist                # a = 0.05
```

The first packet **seeds** the mean and sets the variance to zero, and the EMA
then learns at α = 0.05. After six samples the first one still carries
0.95⁵ ≈ **77 %** of the weight. So `mean: 1466.2` does not say "this gate
normally hears 1466 km" — it says "**the first packet it happened to hear was
about 1466 km**". And `sigma: 0` does not say the samples agree; it says the
variance has barely moved off its zero seed.

We do ship `established: false`, and every reading noticed it and said the
baseline was immature. Then all four used the numbers anyway — computing
"only 34.4 km above the mean", inferring six identical measurements. That is
not a model failing to read a flag. **We labelled an EMA `mean_km` and
`sigma_km` and handed it to people whose job is to reason from statistics.**

**Earns, and it is small:** when `established` is false, do not emit `mean_km`
and `sigma_km` under those names. Emit the seed distance and the sample count,
say plainly that the figure is the first observation decayed at α = 0.05, and
let the absolute 300 km floor be the only stated basis for the decision —
which it already is, since the statistical test is skipped entirely below
`PROP_MIN_SAMPLES`.

Note this pairs with F-16: the baseline is in-memory and resets on restart, so
"6 samples" also means "6 since the last restart", not "6 ever".

**Closed: v3.2.15.** Below `PROP_MIN_SAMPLES` the bundle no longer contains a
`mean_km` or a `sigma_km` at all. The figure is still given, because it is the
only thing known about the gate, but under `ema_km` — a name that cannot be
mistaken for a statistic — alongside `ema_alpha`, a `first_sample_weight`, and
a note that says in plain words what it is and what not to do with it:

```json
"ema_km": 1466.2, "ema_alpha": 0.05, "first_sample_weight": 0.774,
"note": "... 77% of it is still that first observation — read it as
         'roughly what this gate first heard', not as this gate's normal,
         and do not compute how far a link sits above or below it.
         This link was judged by the 300 km floor alone."
```

Stating the weight was the useful part. "77 % of this number is one packet"
ends the question in a way "established: false" plainly did not — all four
readings saw that flag, said the baseline was immature, and then computed with
the numbers regardless.

An established gate is unchanged: it keeps `mean_km`, `sigma_km` and the real
threshold, because there it genuinely has them.

### F-2026-08-13-23 — a gate that is almost always anomalous is probably misplaced, not remarkable
**Source:** four consecutive readings, gate VE7EPT-5 · **Verdict:** our fault

The fourth reading of the same gate makes the arithmetic speak. `VE7EPT-5`
reports `samples: 6` in every one of them — six links ever measured — while
those four readings are themselves four anomalous links through it:

```
W7BSB-1   1080.5 km      NA7Q-1     997.8 km
KC7YRA-9  2131.9 km      KC7YRA-9  2077.8 km
```

**Four of its six links are anomalies.** That is not how a receiver behaves. A
real igate hears mostly nearby stations with a long thin tail; one where most
of what it ever measured cleared 300 km is not a remarkable receiver, it is a
suspect one.

*(Corrected after F-24: this entry first offered the 2043 km mean as further
evidence that the gate "always hears far". It is not evidence of that — the
mean is an EMA seeded on the gate's first packet. The anomaly count carries
this finding on its own; the mean carries nothing.)*

The simplest explanation is that **the gate's own position is wrong**. A
misplaced receiver manufactures a long distance for every station it hears,
systematically and repeatably — which also explains why the same sender
produces 2131.9 km and 2077.8 km on separate packets: the sender is moving
normally, the fixed error is at the other end.

Our caveat says positions are self-reported and unverified, but every reading
so far has taken that to mean the *sender's* position — including the models,
which reasoned about a sender GPS fault four times running. A wrong gate
position is worse: it corrupts every link that gate ever produces, and each one
arrives looking like an independent discovery.

**Earns, and it is cheap because the numbers already exist:** carry the gate's
anomalous fraction in the bundle — links measured, of which anomalous — and say
plainly what a high fraction means. A gate at four in six should read as a
warning about the gate, not as four findings. The same number is worth using
internally: a gate above some fraction is a candidate for exclusion rather than
a source of openings.

**Note how this interacts with F-22.** Grouping openings by receiving gate is
right, but a misplaced gate would then generate apparent openings from every
sender it hears. The two must ship together: group by gate, and disqualify
gates whose anomalous fraction says they are the problem.

### F-2026-08-13-22 — the opening rule groups by midpoint, so it misses the clearest openings
**Source:** three consecutive readings, gate VE7EPT-5 · **Verdict:** our fault

```
W7BSB-1   -> VE7EPT-5   1080.5 km   opening: null
NA7Q-1    -> VE7EPT-5    997.8 km   opening: null
KC7YRA-9  -> VE7EPT-5   2131.9 km   opening: null
```

Three distinct senders, one receiver, all three anomalous, none of them an
opening. The gate's baseline reads `samples: 6, mean 2043.4` identically in all
three, which rules out the exports being spread over time — these links belong
to the same window.

Two or more distinct senders is precisely the opening condition. The reason it
never fires is that `_prop_watch` groups links by the Maidenhead field of each
link's **midpoint**. Senders at 998, 1080 and 2132 km from one gate, lying in
whatever directions they lie, have midpoints hundreds of kilometres apart and
land in different fields. So they are never counted together.

**The rule misses the clearest possible evidence of an opening.** One receiver
suddenly hearing several distant, unrelated senders is a stronger signal than
several links whose midpoints happen to coincide — the midpoints are a
geometric artefact, the shared receiver is a physical fact. The rule was
written to defend against a single bad GPS faking a distance, and grouping by
receiver defends against that just as well: one misconfigured sender cannot
manufacture three different callsigns.

**Earns:** group by receiving gate as well as by midpoint field. An opening
should be raised when either two distinct senders share a midpoint field, or
two distinct senders reach the same gate, inside the window. Both are "two
independent observations of the same condition", which is what the rule is
actually for.

**Check first, cheaply:** how many gates have had 2+ distinct senders with
anomalous links inside 30 minutes, and how many of those produced a recorded
opening? If the first number is much larger than the second, this is confirmed
and sized in one query. It also explains part of F-09 — some of those
`opening: null` answers are not lookup failures at all, but openings the rule
declined to see.

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

**Closed: v3.2.14.** Three parts, and none of them is optional:

- **An in-flight guard.** One evidence export at a time, page-wide. A second
  click does not start a second request — it says so instead, rate-limited so
  six fast clicks produce one toast rather than six.
- **A real abort.** `AbortController` on the export, with a 20 s deadline that
  cancels rather than merely ignores. Ignoring a response leaves its stream
  open, which is the whole mechanism of this finding.
- **Visible state on the clicked link.** This is the part that actually stops
  the clicking, and the reason the other two were needed: the link sat
  unchanged for six seconds while it was already working, so clicking again was
  the only reasonable thing for the operator to do.

The service-worker question this entry raised was real and is fixed in the same
release: the navigate handler's 6 s race left the losing `fetch` running, so
the shell request kept a stream too. It is now aborted — but only once the
cached shell is in hand, since with nothing cached that request is still the
only way to answer.

**Tested against the earlier mistake of stubbing the unit under test.** Only
the boundaries were replaced (`fetch`, the file save, the toast); `evExport`
itself ran. Verified: a second and third click while busy issue no request and
raise exactly one toast; the busy class, `aria-busy` and the `progress` cursor
appear and are cleared; the guard is reusable immediately afterwards; and a
request that never answers is abandoned at 20 s, releasing the guard and
reporting the timeout in the operator's own language rather than a generic
error. The 20 s case was allowed to run in real time rather than shortened,
because the timer firing is the part that releases the stream.

**One thing this does not do:** it prevents the page from *creating* the
condition, it does not repair a session already saturated by something else.
That is the right scope — the pile-up was ours to cause and ours to stop.

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

### F-2026-08-16-01 — the bundle's gate baseline is created by the event it is used to judge

An outside reading of `EA5URX-7 ⇄ EA5JFX-10` (538.2 km) reasoned carefully and
reached a confident verdict from numbers the link itself had written.

The popup said **5382.0× its usual reach**. The bundle in the same request said
the gate's mean was 27.0 km, σ 120.3, threshold 508.3 — so the reader concluded
"exceeds the gate-specific threshold by 6%, very strongly anomalous, 99%".
538.2 / 27.0 is 19.9, not 5382. Two numbers, one system, no way to tell which
is the baseline.

Asking the live API settled it in one read:

| | samples | mean | threshold |
|---|---|---|---|
| `at_flag` — what the decision used | **40** | 0.1 km | not carried |
| `gate_baseline` — what the bundle published | **41** | 27.0 km | 508.3 km |

**41 = 40 + 1, and the extra sample is this link.** The EMA confirms it exactly:
`0.95 × 0.1 + 0.05 × 538.2 = 27.0`. The baseline offered as "this gate's own
history" did not exist until the event arrived, and the threshold it implies
was manufactured by the thing being measured. The reader was not careless; the
file handed it a circle.

**Two faults, both the file's.**

**a. `gate_baseline` is read at export time.** This is F-2026-08-13's problem
in a second path. The *link* record was given `at_flag` so its baseline would
be the flag-time one; the evidence bundle's `gate_baseline` block was left
reading live and nobody checked it. A fix applied to one route is not a fix.

**b. "N× its usual reach" divides by a number that hugs zero.** The denominator
is an EMA (α = 0.05) of the gate's link distances. A gate that mostly hears
stations beside it sits at ~0.1 km, so any real link yields a four-digit
multiplier. 5382× measures how near zero the denominator is, not how unusual
the link is — the neighbouring gate `EA5CKO-10`, ema 0.2, would have shown
2696× for the same 539 km. **Two adjacent gates, one event, a factor of two
between the headlines.**

There is a third, quieter consequence. The flag test is
`max(3 × mean, mean + 4σ)`; on a near-zero mean the σ term decides, and σ is an
EMA of squared deviations, equally contaminated. `at_flag` carries neither σ nor
the threshold, so the bundle **cannot** show what the decision actually compared
against, only what the numbers became afterwards.

| change |
|---|
| `at_flag` carries σ and the threshold as well — the decision's full triple |
| `gate_baseline` reports the flag-time state, or is renamed to say plainly that it is the after state and the flag-time one is printed beside it |
| the popup's multiplier is taken against the **threshold**, not the EMA: *"1.06× the threshold it had to beat"*. A threshold denominator cannot approach zero, and the figure becomes comparable between gates |

The third item was proposed a day earlier on aesthetic grounds — that offering
the mean-ratio prominently and the threshold as a bare number anchors readers on
the more dramatic framing. It now has a measured defect behind it rather than a
preference.

**Not the model's fault.** It separated anomalous / opening / proven-path
correctly, labelled the physical path unverified, and only trusted the one
number the file presented as authoritative.

**✅ Fixed in v3.2.81, 2026-08-22.** All three changes shipped together, plus
one the fix uncovered (F-2026-08-22-01 below).

`at_flag` now carries `sigma_km`, `threshold_km`, `gate_bar_km` and
`times_threshold`. `gate_baseline` in the bundle is built from those and from
nothing else — it never touches the current gate statistics — and the live
figure is published beside it as `gate_baseline_now`, named for what it is.
The popup divides by the threshold, which folds the 300 km floor in and so can
never approach zero.

**The measured drift was worse than this entry recorded.** Written from one
link where the gap was a single sample, and one EMA step explained it exactly.
Across twelve links on 2026-08-21 the gap ran **1 to 21 samples**, and on
2026-08-22 **1 to 29** — the busier the gate, the further the published
baseline sits from the one the decision used. Same circle, wider.

**What made the fix safe to make was the check, not the reasoning.** A wrong
baseline looks exactly like a right one, and the fix touches `station_db.py`'s
hot path. `tools/check_prop_bundle.py` was written first and failing, and it
caught two things the code review would not have:

1. the check's own multiplier assertion was a **proxy** — it read `at_flag.ema_km`
   and assumed that was the denominator, so the fix would have had to move the
   goalposts to pass. It now reads the published multiplier and its named
   denominator instead, which is strictly more than it asserted before.
2. assertion 2 has a blind spot: on a quiet gate the flag-time and export-time
   sample counts are equal, so a bundle that silently went back to the live
   baseline would pass **by luck**. The flag-time block must now declare
   `read_at: "flag time"`.

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

## F-2026-08-18-01 — a ceiling meant for the bill was silencing the free answers

The AI gateway's `daily_limit` sat in front of every reply. Its own docstring
says why it exists: "one viral post away from a bill they did not agree to."

Once the registry lookups landed, that placement was wrong in both directions.
Every template answer — a position from memory, a weather reading already
ingested — spent a unit of somebody's API budget while making no API call at
all. And once the ceiling was reached the gateway refused to tell its own
sender where its own sender was, which it can do offline, for free, from data
already in RAM.

**Verdict: file's fault, and mine.** Nothing reasoned badly. The check was
written when every answer cost money, that stopped being true, and it was not
moved. The class is worth naming: *a guard placed correctly for one code path
does not follow that path when a cheaper one is added beside it.* The same
question applies to the rate limiter and it comes out the other way — that one
is about RF airtime, which a template answer costs exactly as much as a model
answer does. Rate limit stays in front; the ceiling now guards `_ask_ai` alone.

`tools/check_weather.py` asserts an exhausted quota still answers.

---

## F-2026-08-18-02 — the radius was a guess, and the measurement inverted it

`wx_radius_km` shipped at 100 km. It sounded like the distance past which a
temperature stops describing where you are, and as a statement about weather
that is roughly true.

It is not a statement about weather. It is a statement about APRS weather
station density, which is a different thing entirely and varies by country.
Measured against the live registry afterwards: **235 stations within 100 km of
this instance's own operator, none of them measuring weather; nearest that did,
213 km.** At the shipped value this gateway would have refused every weather
question ever put to it, in the one region it was built for, and the logs would
have shown a working feature answering honestly.

**Verdict: file's fault.** No model was involved — this was a plausible
constant written without measuring the thing it constrains. It is the same
error as F-2026-08-16-01 one layer up: a number that looks like a physical
threshold but is actually a property of our own coverage.

The number is now the operator's. What makes a far reading safe to send is not
the ceiling but the disclosure — the reply names the distance and the age, so
a 213 km answer can be judged rather than believed.

---

## F-2026-08-21-01 — the gateway signed itself with the asker's callsign

First test after the badge deploy, on the live public service:

```
RX from TA3HRJ-10: Test
TX to TA3HRJ-10: Test received. 73 de TA3HRJ-10 gateway.
```

TA3HRJ-10 is the station that **asked**. The service took the sender's
callsign out of the packet header and signed itself with it, using DE, on the
air, days after the thing was announced publicly.

The system prompt forbids this in as many words, and has since the identity
work: *"You are not a station and have no callsign of your own. Never sign as
another callsign, never use DE with one, and do not role-play a QSO."*

**Verdict: model's fault, and therefore the file's problem anyway.** Nothing
was missing from the prompt — it named the exact construct the model then
produced. That is the whole finding: *a prohibition stated in prose is not a
constraint.* §G and §H had already reached this conclusion from the other
direction, by taking distance, age and position out of the model's hands and
into a template. This is the same rule applied to something the model must
**not** say rather than something it must say.

`_strip_signature()` now cuts the sign-off before the answer is split into
packets, and logs when it fires — which is also how the frequency finally
gets measured, since the journal could not answer that (F-2026-08-21-02).

Two edges the first version got wrong, both found by probing rather than
reasoning:

- an arbitrary `len(head) >= 15` threshold sent the live case down the wrong
  branch and produced *"Test received. gateway"*
- an answer that was **only** a sign-off excised to an empty string, hit an
  `or text` fallback, and was returned with the callsign fully intact — the
  single case where the entire transmission is a false identification

There is no length judgement to make. Either something precedes the sign-off,
or something follows it, or the answer was nothing but a sign-off and `73`
says the same thing while claiming no callsign.

`tools/check_signature.py` holds both directions: no sign-off reaches the
air, and Turkish "de"/"da" — one of the commonest words in the language — is
never mistaken for one.

---

## F-2026-08-21-02 — the packet feed ate the journal, and the evidence with it

Trying to measure how often the model signs with a false callsign
(F-2026-08-21-01), the answer came back: six responses, all recent. Widening
the window from 3 days to 14 returned the same six. The journal did not go
back further.

Asked the server rather than guessing again:

```
journal lines, last hour    : 319,051
of those, [logger]          : 310,328   (97.3%)
bytes, last hour            : ~47 MB
journalctl --disk-usage     : 4.0 G
oldest entry, WHOLE journal : 16 hours
last boot                   : two weeks earlier
```

`/var/log/journal` exists and `journald.conf` is entirely stock. **Nobody
configured a limit** — journald's default `SystemMaxUse` is min(10% of the
filesystem, 4 GB), the ring hit it, and in World Mode the packet feed refills
it faster than anything else can survive. Every operational line the agent
writes is evicted inside a day.

**Verdict: file's fault, and self-inflicted with a straight face.** The
mechanism is deliberate. `Extension._emit()` writes to the real stderr *as
well as* the Web GUI queue, and its comment says exactly why: so a
server-side operator could confirm from `journalctl` that an extension had
actually initialised. That fix is what makes `journalctl` useless for the
same purpose. Nothing reasoned badly — a decision that was right for
occasional status lines was applied to a firehose.

The class is worth naming, and it is the second time in one day: *a mechanism
sized for one call site behaves differently at another with 10,000× the
volume.* F-2026-08-18-01 was the same shape — a daily ceiling written when
every answer cost money, still counting once answers were free.

Fixed by separating volume from severity rather than by raising a limit.
`Extension.feed()` is a new channel for per-packet output: Live Log yes,
journald never, plus an optional rotating `log_file`, because the raw feed is
genuinely used for diagnosis and deleting it outright was the worse trade.
Startup, warnings and errors are untouched and still reach the journal —
that was the point of the original mechanism and it survives.

`tools/check_feedlog.py` defends the boundary in both directions, including
that an error still reaches journald and that an unwritable path degrades to
Live-Log-only instead of stopping the agent.

**Decided: left alone.** The 4 GB already on disk is stale packet data. Disk
is not the issue — 4% of a filesystem at 33%. The measurable cost is query
time: immediately after the fix, *"what did the agent do in the last 24
hours"* took **114.6 s and returned 4,741,402 lines**, which is why a journal
grep timed out during the investigation itself. But every one of those lines
predates the fix, so time-filtered queries stop touching them within a day and
the problem expires on its own. Only unfiltered queries, or ones reaching back
past 2026-08-21, stay slow. Vacuuming would buy one day of patience at the
cost of the only diagnostic history there is.

Going the other way: at 41 lines/minute the same 4 GB ring now holds **months**
of diagnostics, which is what this finding was about.

---

## F-2026-08-22-01 — a gate can be "established" and still be judged by the floor

Found by building the test for F-2026-08-16-01, not by a reading. Reconstructing
the EA5URX case offline printed this:

```
samples 40, ema 0.1 km, gate_bar 0.3 km, threshold 300.0 km
judged_by: "gate baseline"
```

The gate has 40 samples, so it is established. Its own bar is
`max(3 × 0.1, 0.1 + 4 × 0.0)` = **0.3 km** — below the 300 km floor. So the
floor is what actually stopped everything shorter; the gate's history decided
nothing. The link was nevertheless labelled *"judged against this gate's own
history"*, drawn with the heavy line reserved for the strong claim, and its
`established: true` fed the bundle's confident wording.

**The label was wrong exactly on the links this finding set out to study.**
Every case in F-2026-08-16-01 is a low-EMA gate; that is what produced the
four-digit multiplier in the first place. So the field that was supposed to
tell a reader how much to trust the flag was at its least trustworthy where it
mattered most.

`samples` answers *does this gate have a history*. It was being read as
*did that history decide anything*, and on a low-EMA gate those are different
questions.

| change | state |
|---|---|
| `judged_by` gets a third state: gate baseline / floor, gate's own bar is lower / floor alone | ✅ v3.2.81 |
| the popup and the line weight follow `judged_by`, not `established` | ✅ v3.2.81 |
| the bundle's `reading` splits into the same three cases — the "would it still be flagged if established" counterfactual belongs to young gates only, and on an established low-EMA gate it printed *"3x that figure, which here would be 0 km, so this link clears that bar"*, which reads as corroboration and is arithmetic on a near-zero number | ✅ v3.2.81 |
| **the opening alert at `web_gui.py` filters on `established`** — by the same reasoning these links were flagged by the floor alone and should not raise a notification either | **OPEN** |

The open row is deliberately not in v3.2.81. It changes what puts a
notification on somebody's phone, which is a detection change and needs its own
evidence — how many current openings are built out of these links — not a
same-day guess made while fixing something else.

**Nobody's fault but the code's**, and no model was involved. The value here is
the method: the finding fell out of writing a test that reconstructs the exact
case from the log, which is cheaper than another export round.

---

## F-2026-08-22-02 — the check would have passed by examining nothing

`tools/check_prop_bundle.py` reads the live ring buffer. The ring is in memory.
The deploy that ships a fix **restarts the service**, so the command used to
prove the fix ran against an empty buffer:

```
no anomalous links right now — nothing to check
EXIT=0
```

A clean exit from an examination that never happened. Caught by predicting it
rather than by seeing it, half an hour before the deploy — and it is the same
defect as the one the whole package is about: a number that looks like a
verdict and is an artefact of how it was produced.

Fixed before deploying: an empty buffer, or a run where no link's evidence
could be fetched, now exits 1 and says why. Confirmed live — the first run
after the v3.2.81 deploy printed exactly that failure.

A second artefact of the same kind, not a defect but worth writing down: the
red this package worked from was **"43 problems across 12 links"**, and that
figure is stable because `--max 12` caps the sample, not because the same links
persist. The pool was 33 on 2026-08-21 and 93 on the 22nd. Read the cap, not
the constancy.

---

## F-2026-08-22-03 — the check was holding one link's decision against another link's baseline

Surfaced by fixing F-2026-08-16-01. With the baseline now recorded per link,
the check still reported drift on three of twelve — 3357 samples against 3258.
It was not drift.

`/api/prop/evidence` matches on `call` + `gate`, and takes the most RECENT
record when no `ts` is given. The check never sent one. **Sender→gate pairs
repeat**, because the same station beacons from the same spot and is flagged
again each time:

```
W0ZC-15    -> RA4NHY-1    19 records
XE2BNC-1   -> KF6NYM-15    7 records, all at an identical 373.9 km
CQ0PMJ-3   -> ED1ZAX-3     3
```

So link A's `at_flag` was being compared with link B's `gate_baseline`, and the
difference was read as the event contaminating its own history. **The defect
was invisible for as long as the bug it was hunting existed**: while
`gate_baseline` was read live it was larger than `at_flag` either way, so the
assertion fired for the right reason by accident.

Fixed: the check sends `ts`, and refuses to run any assertion if the bundle
answers with a different timestamp than the one asked for — a mismatch is now
its own named failure rather than a wrong number. Negative control run: with
the `ts` removed and that guard kept, it reports exactly the three pairs above
and exits 1.

**Two things fall out of this that are not about the check.**

The repeat counts are measured evidence for F-2026-08-12-09's open item — the
repeat count for a sender→gate pair. Nineteen records of one pair at one
distance is not nineteen findings, and the map draws the same line nineteen
times.

`XE2BNC-1 → KF6NYM-15` is a calibration case for F-2026-08-12-03: 373.9 km
against a gate whose own bar sits at 300–366 km, flagged, which lifts the bar,
which it then clears again. A gate oscillating around its own threshold.

---

## F-2026-08-24-01 — 4646 km measured to a point that does not exist

An evidence bundle for DG2MMB-12 -> DB0OAL, exported at v3.2.83, reported an
anomalous RF link of 4646.2 km. **Every part of the bundle's own machinery was
sound.** Package B's head had landed and it showed: `at_flag` carried `sigma_km`
and `threshold_km`, `gate_baseline` was flag-time and said so, its sample count
equalled `at_flag`'s rather than exceeding it, `gate_baseline_now` sat in its
own block, and the multiplier divided by the threshold rather than the EMA. The
threshold arithmetic reproduces to the decimal:

```
max(3 x 317.8, 317.8 + 4 x 1019.6) = max(953.4, 4396.2) = 4396.2
4646.2 / 4396.2 = 1.057   ->  published as 1.1x
```

The sender's reported position was **lat 93.093, lon 986.8757**.

Latitude stops at 90 and longitude at 180. This is not a position that is
wrong; it is not a position. Reproduced from the parser in one line each:

```
_ddmm_to_decimal("93",  "05.58", "N")  -> 93.093
_ddmm_to_decimal("986", "52.54", "E")  -> 986.87567
```

APRS sends positions as `DDMM.mm` / `DDDMM.mm`. `_RE_POS_UNCOMP` matches the
digit *shape* and nothing ever asks whether the degrees are in range, so a
corrupt packet decoded cleanly and the locator, the haversine, the gate's
distance baseline and the map all worked on it.

**Verdict: file's fault, twice over.**

**First**, `detection.excluded` claims to drop "GPS garbage" — but only by an
upper distance bound. This link measured 4646 km against a 5000 km ceiling, so
nothing tested it. It was excluded by luck, and luck ran out. *Range is not
validity*, and the test belongs where the number is born rather than four
layers downstream.

**Second, and worse: the bundle offered a false ambiguity about it.**
`position_corroboration` reported

> "either the position is wrong, or the operator is transmitting away from
> home, and this evidence cannot separate those"

That sentence is correct in general and wrong here. An operator away from home
is still on Earth. The check ran a callsign-prefix comparison against a
coordinate it should have refused to accept, and then described the result in
the careful, balanced language reserved for genuinely ambiguous cases. A reader
handed that would weigh two possibilities where there is only one. This is the
same defect class as F-2026-08-16-01: not a missing fact, but a confident
statement built on an input nobody validated.

Fixed at the parser. `_on_earth()` gates both the uncompressed and the
compressed path; an out-of-range position sets `position_invalid` and the
lat/lon/locator fields are simply absent. The rest of the packet is kept — the
symbol, the comment and any weather in it were never in doubt, and a station
with no position is something the registry already handles.

`tools/check_coords.py` holds the live failure, both boundaries (90 and 180 are
real places, 90.001 is not), the compressed path, and — the direction this
fails if someone tightens it too far — that an ordinary position is untouched.
`tools/check_prop_bundle.py` gains a fifth assertion: no published link may
have an endpoint off the Earth.

**SQLite was a second front door.** Fixing the parser stops new impossible
positions arriving and does nothing about the ones already written: the live
database held **47 stations** whose coordinates are not on Earth, reloaded on
every start. Their stored locators show what they went through on the way in —
`3M-84Od`, `[O91qm`, `jK44rc`, `AR-85Pw` — strings `_latlon_to_locator`
produced from out-of-range input, which no Maidenhead grid can contain. A
validity rule enforced at one entrance is not enforced. `load_sqlite()` now
applies the same test, imported from the parser rather than copied, drops the
position while keeping the station, and reports the count through `web_gui`
instead of teaching a pure library to print.

**And the first version of that report was itself false**, which is worth
recording rather than quietly correcting. Shipped as v3.2.85, the live load
announced:

```
[station-db] dropped 28086 stored position(s) that were not on Earth
```

A direct query of the same database counts **47**. The other ~28,000 are
stations that never carried a position at all: the branch treated *absent* and
*impossible* as one case and then asserted the second about both. It also
blanked `locator` for every one of them, and a locator can arrive from the
repeater database with no lat/lon ever parsed — so it did discard something,
just not the thing it named.

There are three cases, not two. A number stated to an operator with confidence,
produced by counting the wrong set, is the same defect as the one this whole
finding is about — made while fixing it, and caught only because the live
figure disagreed with a query run ten minutes earlier. `check_coords.py` now
holds the distinction: a position-less row must not be counted, and must keep
its locator.

**Still open — the poisoned baseline.** DB0OAL's own figures show the damage
already done: mean 317.8 km and sigma 1019.6 km at flag time, and nine samples
later mean 1518.6 km, sigma 2167.5 km. For an EMA at alpha = 0.05 to move that
far in nine steps, the arriving samples must average about **3565 km** — so
this was not one bad packet but a stream. The parser fix stops new ones; it
does not un-teach a gate that has already learned garbage as its normal, and a
gate whose sigma is 3.2x its mean will not flag the next real opening. Whether
affected baselines should be reset, and how such a gate is identified, is a
question for §D rather than something to decide here.

---

## F-2026-08-25-01 — the check was taught to ask; the server was never taught to answer

Sibling of F-2026-08-22-03, and the half of it that did not ship.

That finding established that `/api/prop/evidence` answers with the most recent
record for a `call`+`gate` pair, and fixed it by teaching **the check** to send
a `ts` and refuse every assertion if the bundle answered with a different one.
The server side was never touched. It still matched on
`abs(l["ts"] - want_ts) <= 300` while walking the ring **newest-first**, so for
any pair beaconing faster than five minutes it could not return the record it
was asked for — it returned the newest one inside the tolerance.

**How it surfaced.** `check_prop_bundle.py --max 12` exited 0 on 2026-08-22 and
1 on 2026-08-25 with no detector code changing in between. Nothing had
regressed; see F-2026-08-25-02 for why the sample decided it.

Measured on the live feed, 2026-08-25:

```
SV6NMP-9 -> SV1TNT-10: asked for ts 1787652150, answered 1787652439  (+289 s)
SV6NMP-9 -> SV1TNT-10: asked for ts 1787652166, answered 1787652439  (+273 s)
SV6NMP-9 -> SV1TNT-10: asked for ts 1787652181, answered 1787652439  (+258 s)
```

Six consecutive requests, one answer. That pair beacons about every 15 s, which
puts roughly twenty records inside a 300 s window; the newest wins every time.

**Verdict: file's fault.** The consequence is exactly the one §B exists to
remove — the reader is handed one link's `at_flag` beside another link's
`gate_baseline` and cannot see that they belong to different events. F-16 and
F-2026-08-16-01 closed that circle at the recording end. This is the same
circle re-entering through the retrieval end.

**Fixed in v3.2.87.** Exact `ts` wins outright. The tolerance stays, because a
`ts` taken from a stored event is rounded to the event rather than the link and
that is a fair thing to want — but it now resolves to the **nearest** record,
never the newest. Nearest is what the tolerance always meant; newest is what
made it wrong.

**The stored-event path was a second door**, and got the same rule. Its window
is ±3600 s, twelve times the ring's tolerance, so a repeated pair is *likelier*
there, not less; it had been taking the first match in the list. A validity
rule enforced at one entrance is not enforced — the third time this project has
written that sentence (F-2026-08-24-01, the daily quota, and now this).

`tools/check_prop_ts.py` is new and holds it offline: it builds the burst
itself, twenty records at 15 s spanning 285 s against the 300 s tolerance, and
drives the real handler. Proven in both directions before it was trusted — 0
problems against the fix, **39 against the pre-fix ring logic** (nineteen of
twenty records plus the nearest-versus-newest case), and 1 against the pre-fix
stored-event path from assertion 5 alone. A check that has only been seen to
pass has not been seen to work.

---

## F-2026-08-25-02 — a check whose sample is chosen by luck reports the weather, not the code

F-2026-08-22-02 recorded that `check_prop_bundle` would have passed by
examining nothing, and made an empty ring a failure. This is the same defect
one level in: the run was not empty, it was **unrepresentative**, and that was
enough.

The `ts` assertion can only fire when a sender→gate pair repeats inside the
endpoint's 300 s tolerance. `--max` takes the first N links. On 2026-08-22 the
top twelve held no such pair, so the check reported 0 problems over a fault
that was live at the time and had been since v3.2.81.

Measured side by side on 2026-08-25 — same process, same minute, one via the
admin API on the VPS and one via the public view:

| sampling | result |
|---|---|
| first `--max` links | **0 problems, exit 0** |
| repeat-pairs first | **6 problems, exit 1** |

**Verdict: our fault, and the more expensive kind** — a green that is wrong
costs more than a red that is noisy, because it closes the question. HANDOFF
listed this check as verification still owed; run in its old form that morning
it would have been ticked off.

**Fixed in v3.2.87.** Links whose pair repeats inside the tolerance are sampled
first, and the run prints how many of the sample came from them. A window that
genuinely contains none is now visible as such rather than passing silently.
They are also where a wrong baseline does the most damage: a pair flagged
nineteen times is nineteen chances to publish another event's history.

**Left undecided, deliberately.** The check still exits 0 when the sample
contains no repeating pair — the condition is reported, not fatal. Making it
fatal is the complete fix and would turn the hour after every deploy red, which
trains a reader to ignore the colour. That trade is the operator's to make, not
a thing to settle inside a fix for something else. The first live run after the
v3.2.87 deploy printed exactly this state:

```
sample: 1 of 1 links, 0 of them from pairs that repeat inside the 300 s tolerance
0 problems
```

Correct, honest, and worth nothing as a verification — which is now legible
from the output alone.

---

## F-2026-08-25-03 — a gate in the open Atlantic, and it passes every test we have

F-2026-08-24-01 taught the parser that latitude stops at 90 and longitude at
180, and gave `check_prop_bundle` a fifth assertion: no published link may have
an endpoint off the Earth. Run across all 400 endpoints of a 200-link sample on
2026-08-25, that assertion **passes**.

The worst link in the same sample:

```
SV6NMP-9  38.4232 N,  22.4882 E   (Greece)
SV1TNT-10 55.2734 N, -41.0935 W   (open North Atlantic)
                                   4984.0 km, 17 records in a 7.4 h window
```

55 N, 41 W is about 500 km south of Greenland's southern tip. There is no land
there. Both callsigns are `SV` — Greece — and Greece is roughly 1,000 km
across.

**It clears every guard this project has built.** The position is on the Earth,
so assertion 5 passes. The link is 4984 km against the 5000 km GPS-garbage
ceiling, so `detection.excluded` lets it through — by 16 km, which is the same
kind of luck F-2026-08-24-01 said had run out. `check_prop_bundle` reports 0
problems on it.

**Verdict: file's fault, and a gap rather than a bug.** *Range is not validity*
was the lesson of the 24th; this adds *and neither is being on the planet*. The
one independent fact available about a self-reported coordinate — the area its
callsign prefix is allocated to — is already computed by
`_prop_position_corroboration`, but only for the **sender**. Baselines are kept
per gate, gates are what the propagation detector reasons about, and a gate's
position is unchecked.

This is F-23's live example, arriving before F-23 was written. A gate producing
17 of 200 records in one window is precisely the "anomalous fraction" that
finding proposes to carry, and it reads today as 17 separate discoveries. It is
also why NEXT.md's rule that **F-22 must not ship without F-23** is right: group
openings by receiving gate while this gate is trusted and it will manufacture
apparent openings out of everything it hears.

Not fixed. Recorded so that the next reading of a long link starts by asking
where the gate claims to be.

### Correction, 2026-08-26 — two of the three claims above are wrong

Written from inference rather than from the function, and the function says
otherwise. Kept per the rule at the top of this file.

**Wrong: "`_prop_position_corroboration` runs on the sender only."** It checks
both ends and always has:

```python
gate = station_db_module.position_corroboration(
    link.get("gate"), link.get("g_lat"), link.get("g_lon"))
```

Run against the gate in question it returns exactly what it should:

```
SV1TNT-10 -> consistent: False, region: Greece,
             'position falls OUTSIDE the area this prefix is allocated to'
```

So the bundle was not silent about this gate. The verdict would have been
`contradicted`, and per F-2026-08-15-46 a contradicted link is already dropped
before the opening grouping — which also makes the claim that this gate
"blocks F-22" weaker than stated. It cannot manufacture an opening.

**Wrong, and this is the useful correction: the gap is not that gates are
unchecked, it is *where* the check sits.** `position_corroboration` runs at
export time and at the grouping stage. The detector in `station_db._prop_check`
never consults it, and the per-gate baseline is updated **before any validity
test at all** — the EMA write is the first thing in the block, above even
`if dist < PROP_MIN_KM: return`. The only positional sanity the detector
applies to a gate is a Null Island test, which 55 N 41 W passes.

So every link measured to a phantom gate position teaches that gate's distance
baseline. The comment beside the update states the intent plainly:

> "The link still updates the baseline afterwards, so a permanently
> misconfigured 'DX' station gradually becomes that gate's normal and stops
> alerting."

That is deliberate self-healing for a misconfigured **sender**. For a
misconfigured **gate** it inverts: every link through it is inflated, the
baseline climbs, and real openings at that gate become undetectable. Same
failure as the poisoned DB0OAL baseline in the open question at the end of
F-2026-08-24-01, arriving through the gate's own position rather than its
senders'.

**And the prefix test is the wrong instrument for gates anyway.** Measured over
a fresh 174-link pool, 90 distinct gates:

| test | gates caught |
|---|---|
| position contradicts own callsign prefix | **2** |
| every link through the gate flagged, AND baseline under 20 samples | **7** |

Both prefix hits are almost certainly legitimate: `SA3MHZ-10` and `SM0JLZ-2`,
Swedish callsigns reporting from 38.2 N, 0.5 W — Alicante. Swedish operators
wintering on the Costa Blanca is the single most ordinary explanation there is,
and it is the exact ambiguity the corroboration note already describes. A test
with a 2.3% hit rate whose every hit is a false positive is not a test.

What separates SV1TNT-10 is not that its prefix disagrees — it is that the
position is in the open ocean, and "is this on land" needs a landmask this
project has no reason to carry.

**F-23's own instrument does the job without any geography.** The anomalous
fraction alone is not enough — it catches genuine consecutive openings at
mature gates (`HS5AC-10` at samples 5979–5980, `IZ0FKE-8` at 1739–1740, both
2 of 2). Paired with a young baseline it isolates the shape:

```
LB4CD-7     14 flags of 14 links   samples  6-19   max  333 km
VE2SIL-1    10 flags of 10 links   samples 10-19   max 2044 km
LZ2AB        8 flags of  8 links   samples  0- 7   max  388 km
KE0TTZ-14    5 flags of  5 links   samples  4- 8   max  447 km
```

`LB4CD-7` is the clearest: fourteen consecutive links, every one flagged, none
further than 333 km. A gate that hears nothing closer than the floor is either
somewhere very strange or not where it says it is.

**Still a candidate signal, not a verdict.** A genuinely new gate somewhere
remote would look identical, and 51 of the 90 gates in this pool contributed a
single flag each, so the population is thin. This gives F-23 a starting
threshold and a measured base rate; it does not give it a rule.

---

## F-2026-08-25-04 — F-03's split has flipped, and the README still carries the old one

F-2026-08-15-46 answered F-03 on 200 live anomalous links:

| | 2026-08-15 | 2026-08-25 |
|---|---|---|
| flagged by the gate's **own** threshold | 48 (24%) | **152 (76%)** |
| flagged by the **300 km floor alone** | 152 (76%) | **48 (24%)** |

Same sample size, same endpoint, ten days apart. Gate baselines have been
persisting since v3.2.34; on 2026-08-15 only 53.9% of gates had crossed the 20
samples their own threshold needs. More of them have now, and the split moved
with it. The two figures being an exact swap is arithmetic — both samples are
200 — not a second finding.

Today's 200 break down further:

| what decided the flag | links |
|---|---|
| the gate's own baseline | 79 |
| the 300 km floor, gate established but its own bar lower | 73 |
| the 300 km floor alone, gate not established | 48 |

**The floor is not manufacturing those 73.** Their gates' own bars run to a
median of 177 km and a maximum of 293 km — all below 300 — so every one of
those links, being ≥300 km by definition, would have cleared the gate's own
standard too. There the floor is the *stricter* test.

**The 48 are repetition, not discovery.** They come from 12 distinct gates, and
17 of them are the single pair in F-2026-08-25-03.

**What this does NOT re-measure, and an earlier draft of this entry got wrong.**
F-2026-08-15-46's other figure — that 87% of young-gate flags would not clear 3×
if their gate were established — is untouched here. That counterfactual needs
the gate's would-be bar, and `at_flag.gate_bar_km` is `null` for exactly the
population it applies to. So the noise rate within young gates stands as last
measured; only the split between the two branches has moved. Claiming otherwise
would be the F-16 denominator mistake in a new coat: answering a question with
a number that cannot address it.

**Product consequence, not yet acted on.** The README states *"76% of flags
come from the floor alone and 87% of those would not have been flagged had
their gate been established."* The first clause is now the wrong way round. The
second is still the best available reading. Per house rule the correction is a
draft first — it is public text, and a number that moves with gate maturity
should probably not be quoted as a constant at all.

---

## F-2026-08-26-01 — the poisoned baseline heals itself, unless the gate is the thing that is wrong

Answers the open question left at the end of F-2026-08-24-01, and hands F-23
an instrument that needs no window at all.

The question was whether a gate whose baseline has learned garbage should be
reset, and how such a gate would be identified. Both halves turn out to be
answerable from `meta.prop_gate_stats`, which persists `[samples, mean, var]`
for every gate — **8,422 of them, 7,316 established**. No polling, no waiting
for the ring to refill.

### DB0OAL recovered on its own

The question recorded it at mean 1518.6 km, sigma 2167.5 km, nine samples after
the flag, and asked whether that gate would ever flag a real opening again.
Measured 2026-08-26:

```
DB0OAL   samples=1935   mean=96.8 km   sigma=37.1 km   own bar=290.5 km
```

Below the 300 km floor. The EMA at alpha = 0.05 washed it out over roughly
1,900 samples once the parser stopped feeding it impossible positions. **No
reset was needed and none should be written.** The worry was real and
self-limiting.

### But it does not heal when the gate's own position is the fault

`SV1TNT-10`, the gate from F-2026-08-25-03, sitting at 55.27 N / 41.09 W:

```
SV1TNT-10   samples=77   mean=4979.4 km   sigma=4.7 km   own bar=14938.1 km
```

Its mean is 16 km under the 5000 km ceiling and its sigma is **4.7 km**. Every
link it measures returns almost exactly the same wrong distance, because the
error is not in the traffic — it is in the fixed coordinate everything is
measured *to*. An EMA cannot decay an error its input keeps re-supplying.

**That is the distinction the open question was missing.** A baseline poisoned
by transient bad senders recovers. A baseline poisoned by the gate's own
position never does, because the poison is systematic.

### The consequence has a name: the gate goes permanently deaf

A gate's bar is `max(3·mean, mean + 4·sigma)`. Once that exceeds the 5000 km
ceiling, no link can ever clear it — anything longer is discarded as GPS
garbage *before* the comparison. The gate stops flagging, silently, forever.

**25 of 7,316 established gates (0.34%) are already there.** Two of them were
watched crossing over inside one 7.4 h window:

| gate | in the anomaly pool | now | |
|---|---|---|---|
| `VE2SIL-1` | 10 flags of 10 links, samples 10–19 | samples 23, bar 5778 km | **deaf** |
| `LB4CD-7` | 14 flags of 14 links, samples 6–19 | samples 21, bar 1001 km | silent — it hears nothing past 334 km |

Both flagged *everything* while young, because the floor decided; the moment
they crossed 20 samples their own bar was already above anything they would
ever hear. There is no state in between. A gate goes from flagging every link
to flagging none, and nothing reports it.

### The instrument: a high mean with almost no spread

A gate in the wrong place measures the *same* wrong distance every time. Real
DX has spread. Of the 45 established gates with a mean at or above 1,000 km,
**13 have a sigma under 10% of that mean** and 32 have honest variance:

```
LU9DCE      n=514   mean=1694.9   sigma=  0.0   cv=0.000
KC3WJU-2    n=793   mean=1250.5   sigma=  0.4   cv=0.000
CE4PLU-12   n=111   mean=1390.2   sigma=  0.0   cv=0.000
SV1TNT-10   n= 77   mean=4979.4   sigma=  4.7   cv=0.001
KG7OKR-10   n= 96   mean=3162.7   sigma=  2.6   cv=0.001
KH2SR       n= 32   mean=3104.3   sigma=  2.9   cv=0.001
```

against, for contrast:

```
WA7GMX-8    n=299   mean=2019.6   sigma=1012.7  cv=0.50
W7BMH-7     n= 35   mean=2286.8   sigma= 824.3  cv=0.36
```

`KC3WJU-2` is the one to read twice: **793 links, all at 1250.5 km ± 0.4 km.**
No propagation mechanism produces that. Neither does a busy gate. It is one
fixed geometry, repeated, and 1250 km is far past terrestrial VHF — so one of
the two positions in it is wrong.

**The rule identifies a broken pair, not a guilty end.** `mean ≥ 1000 km AND
sigma < 0.1·mean` says the baseline is built from a fixed impossible distance;
it does not say whether the gate or its single correspondent is misplaced. For
the purpose it is needed for — deciding whether this gate's baseline can be
trusted — that is enough, and claiming more would repeat the mistake corrected
in F-2026-08-25-03.

### Why this replaces the plan to widen the window

The correction to F-2026-08-25-03 proposed collecting anomalies over days to
see whether "7 suspicious gates of 90" was real or sampling noise. It is not
needed. `prop_gate_stats` already holds every gate's lifetime count and spread,
so the population is 7,316 rather than 90 and the measurement is immediate.
`prop_history` cannot substitute for it either — checked, and it stores only
**opening events**: 271 rows over 14.0 days carrying 666 links, roughly 8% of
anomalies, and biased against exactly these cases since a contradicted link is
dropped before grouping.

**A cross-check that fell out of the same read.** 6,537 of 7,316 established
gates (89.4%) have an own bar *below* the 300 km floor. That is the same shape
F-2026-08-25-04 measured from the live pool, from an independent direction and
a population 36× larger.

**Not fixed, and one decision is not ours.** Nothing here changes detection.
What it supports: reporting a deaf gate rather than letting it go quiet
unnoticed, and refusing to build an opening on a gate whose baseline matches
the fixed-distance signature. Whether a deaf gate's baseline should be reset —
now knowing that only the systematically-poisoned ones stay broken — is the
§D question, and it now has 25 named cases to be decided against instead of a
hypothetical.

---

## F-2026-08-26-02 — do not reset a deaf gate: the deafness is the quarantine

Answers the §D question left open by F-2026-08-26-01 — reset a deaf gate's
baseline, or only report it? **Report only.** The reporting shipped in v3.2.88;
nothing further should be built, and this entry exists to stop it being built
later by someone who reads "25 gates can no longer flag" as a bug report.

### What a reset would actually do

A reset makes the gate young again: under `PROP_MIN_SAMPLES` its own bar is
never consulted and the 300 km floor decides alone. So the question is simply
whether its typical link clears 300 km.

**All 25 of 25 do.** Median 6.8× the floor, lowest 1.4× (`SR9NRA`), highest
16.6× (`SV1TNT-10`). Every one of them would go from flagging *nothing* to
flagging essentially *everything it carries*.

`SV1TNT-10` is the case that makes it concrete. It sits in the open Atlantic
and every link it measures returns ~4984 km to that phantom position. Reset it
and all of them are anomalies again — the 17-records-in-one-window flood that
started this whole thread. **The reset does not repair the gate; it inverts the
failure from silent-and-wrong to noisy-and-wrong, and noisy is worse**, because
noisy reaches the map and the notification channel.

### These are not gates whose trust should be restored

Distribution of mean reach across 7,317 established gates — what an igate
normally hears:

| | km |
|---|---|
| p10 | 3.1 |
| p25 | 8.2 |
| **p50** | **20.6** |
| p75 | 46.3 |
| p90 | 84.1 |
| p99 | 425.1 |
| p99.9 | 2640.1 |

**Every deaf gate sits at p98.96 or above**, 18 of them past p99.7. A gate
whose *normal* is 1,926 km is not measuring terrestrial VHF; the median gate
hears 20.6 km, two orders of magnitude away. Only 96 of 7,317 gates (1.31%)
have a mean reach past the 300 km floor at all, and 45 (0.62%) past 1,000 km.

**Of those 45, 22 are already deaf.** So roughly half the population of
implausibly far-reaching gates has already been taken out of service — by its
own baseline, silently, with nobody deciding it.

### That is the actual finding

The deafness is not the disease. It is an **accidental quarantine**, and on
this evidence it is quarantining close to the right set. Resetting would
release exactly the population that should not be released.

What is wrong with it is not the outcome but the mechanism: it is accidental,
undocumented until v3.2.88, and it arrives late — a gate must reach 20 samples
before its own bar is consulted, and until then the floor makes it flag
*everything*. `VE2SIL-1` flagged 10 of the 10 links it carried, then went
permanently silent on the sample that made it established. Both halves of that
are wrong for the same reason, and a reset fixes neither.

**The principled version of what deafness does by accident is to exclude a gate
whose baseline shows the fixed-distance signature, explicitly and from the
start.** That is the open decision from F-2026-08-26-01, it changes detection,
and it is where this effort belongs — not in a reset.

### And a reset is not reversible

`prop_gate_stats` is the persisted record of what every gate normally hears,
rebuilt over months. Resetting on a diagnosis that has been in existence for
one day would destroy real history for any gate the rule caught wrongly, with
nothing to restore it from. The two writes are not symmetric: reporting can be
withdrawn, a reset cannot.

**Counter-evidence considered.** DB0OAL, the gate that prompted the original
worry, healed unaided over ~1,900 samples once the parser stopped feeding it
impossible positions (F-2026-08-26-01). That is the genuinely transient case,
and it argues the same way: where there is real traffic the EMA already does
what a reset would do, more slowly and without discarding anything.

Where there is *not* enough traffic to heal, the gate is by definition barely
carrying links — so what it can no longer flag is close to nothing.

---

## F-2026-08-26-03 — one fixed error, three times, is not two senders

The principled version of what gate deafness was doing by accident
(F-2026-08-26-02). Shipped in v3.2.89, and the first change in this thread that
alters detection.

### The shape

Some gates measure the same large distance every time, because the error is a
fixed coordinate rather than anything in the traffic:

```
KC3WJU-2    793 links at 1250.5 km ± 0.4 km
LU9DCE      514 links at 1694.9 km, sigma exactly 0.0
```

Against the population: the median established gate's mean reach is **20.6 km**
and p90 is 84.1 km. No propagation mechanism produces 793 identical
long-distance measurements, and no busy gate does either. It is one geometry,
repeated.

### Why repetition is the dangerous part

An opening is *two or more distinct senders in one Maidenhead field within 30
minutes*. A repeated link supplies its own second sender. Audited over 14 days
of stored events, **3 of 246 openings existed only because of one** — and one
of the three is unambiguous:

```
K4OZS-10 -> KC3WJU-2  1250.3 km
K4OZS-10 -> KC3WJU-2  1250.3 km
K4OZS-10 -> KC3WJU-2  1250.3 km
N8NOE-15 -> K2GB-10    864.4 km
```

The second sender was real. The first was one fixed error, three times. That
opening was announced: a notification, an AI assessment, a line on the map.

1.2% of openings, roughly one every five days on the world feed. Small, and
each one spends real credibility.

### The rule is on the link, not the gate

A gate with this signature that suddenly measures a **different** distance has
made a real observation — and on such a gate it is the *only* observation worth
having. So a link is excluded only when it sits on the gate's own repeated
value: `|km − mean| ≤ max(3σ, 1% of mean)`.

Measured against the same 14 days, the blunt whole-gate rule and this one
remove **the same 3 openings**. The narrower rule therefore costs nothing today
and cannot silence a real observation tomorrow, which is the only basis on
which the narrower one is worth the extra code.

The 1% floor exists because a sigma near zero is a *real value* here, not a
degenerate one — `LU9DCE` genuinely reads 0.0 — and `3σ` alone would make the
band razor-thin. On a 1250 km baseline the floor is still ±12.5 km, far tighter
than any genuine change in path length.

### Excluded from the grouping, not from the record

The link stays on the map under its own class. This is the same treatment a
position-contradicting link has had since F-2026-08-15-46, for the same reason:
**remove it from the inference, not from the observation.** A reader who wants
to know why a region did not open should still be able to see everything that
was heard there.

`prop_detection_params` now names both exclusions, so a bundle reader is told
what the rule dropped rather than left to notice an absence.

### Verification

Replayed through the real code against the live database: 246 stored openings,
**3 no longer reported, 6 individual links excluded** — matching the
independent audit exactly.

`tools/check_fixed_geometry.py` holds six assertions, including both live
shapes, the band edges either side of 12.5 km, and the four directions this
fails if someone widens it: an ordinary gate (mean 20.6 km), a real DX gate
with honest spread (`cv` 0.50), a young gate whose mean is still moving, and
the 1000 km condition itself. Proven against two reverted variants before being
trusted — the blunt whole-gate rule (3 problems) and the missing zero-sigma
floor (1).

### What this does not claim

It identifies a broken **pair**, not a guilty end: the gate's position may be
wrong, or its single correspondent's may be. For the decision at hand — whether
this link can serve as evidence of an opening — that distinction does not
matter, and asserting more would repeat the mistake corrected in
F-2026-08-25-03.

It also does not fix the other half of the `VE2SIL-1` problem. A gate still
flags *everything* while it is young, because the floor decides alone until 20
samples. This rule needs an established mean, so it cannot help there. That
half remains open.

---

## F-2026-08-26-04 — five identical readings answer a different question than twenty

The other half of `VE2SIL-1`, and the noisy one. Shipped in v3.2.90.

F-2026-08-26-03 stopped a gate's repeated distance from supplying its own
second sender, but the test needed an established mean — 20 samples — and the
damage happens before that. Until a gate reaches 20 samples the 300 km floor
decides alone, so a misplaced young gate flags **everything it carries**:

```
VE2SIL-1    10 flags of 10 links, samples 10-19
RA4NHY-1    19 identical records at 1170.6 km ± 0.35
```

`RA4NHY-1` is the one worth pausing on. F-2026-08-22-03 recorded that pair
repeating 19 times four days ago, as an observation about the evidence
endpoint. The mechanism was sitting in the gate's own baseline the whole time:
nineteen samples, all the same distance, sub-metre spread. The symptom was
logged before the cause was visible, which is the ordinary way round and worth
noticing when it happens.

### Why the sample bar can be lower here

`PROP_MIN_SAMPLES = 20` exists to trust a **level** — how far this gate
normally hears. This test asks about **spread** — does the distance repeat —
and that converges far faster. Five identical readings settle it; twenty are
needed only for the mean.

So `PROP_GEOMETRY_MIN_SAMPLES = 5`, separate from `PROP_MIN_SAMPLES` and used
by nothing else.

### The threshold was measured, not chosen

Across 1,106 young gates on the live feed:

| bar | young gates caught |
|---|---|
| 3 | 8 |
| **5** | **6 (0.54%)** |
| 10 | 3 |

The six at 5 are unambiguous — every one under `cv` 0.006, two with a sigma of
exactly zero:

```
N3VPD-2    n=19  mean=3839.5  sigma=5.78  cv=0.0015
NT5R-4     n= 8  mean=1717.0  sigma=9.85  cv=0.0057
BG6JDU     n= 8  mean=1176.3  sigma=0.00  cv=0.0000
RA4NHY-1   n=19  mean=1170.6  sigma=0.35  cv=0.0003
K4KPN-15   n=13  mean=1018.3  sigma=0.00  cv=0.0000
CE3RHA-7   n= 6  mean=1009.0  sigma=0.30  cv=0.0003
```

And the boundary holds. The nearest young gate *not* caught is `G5ATT-7` at
`cv` 0.10, and `KF6NYM-11` — mean 3838.9 km, sigma 531.9 — is correctly left
alone despite a mean higher than four of the six. **Spread is what separates a
gate that is somewhere strange from a gate that is not where it says it is**,
and it does that job at eight samples as well as at eight hundred.

Lowering the bar to 3 adds two gates on evidence too thin to call a repetition
— one station beaconing three times from one spot. Raising it to 10 loses
three genuinely fixed gates carrying 6 to 8 samples.

### What it does not buy, stated plainly

Replayed against the live database, the lower bar removes **no additional
stored openings** — still 3 of 246, the same 6 links. The six young gates it
catches did not appear in the last 14 days of events.

So its value is prospective: the repetition it stops joining future groupings,
and the marking below. That is what the evidence supports, and inflating it
into an opening count would be the same move F-2026-08-25-04 had to correct.

**A measurement still owed.** How much of the live anomaly list carries the
mark could not be taken — the ring held 6 links fifteen minutes after the
deploy, and reporting 0% from that would be the F-2026-08-25-02 trap with the
paint still wet. Worth taking once the ring has refilled.

### The link is marked, not removed

`at_flag` now carries `fixed_geometry`. The map was drawing nineteen identical
lines as nineteen discoveries; now it can say what they are. The link itself
stays — remove it from the inference, not from the record, which is the third
time this thread has landed on the same principle.

It is evaluated against the baseline *including* the link being judged, rather
than the flag-time convention the fields beside it follow. Deliberate: the
grouping pass reads the same live state a moment later, and the mark agreeing
with the decision matters more here than matching a convention.

---

## F-2026-08-26-05 — the fix for a false absence contained one, and the first live bundle showed it

F-09 shipped in v3.2.91: `opening: null` became four named states, so a reader
could tell "nothing was heard here" from "the rule is met and nothing was
written" from "this process cannot answer".

The fourth state, `unknown`, guarded the restart case — the counts come from
an in-memory ring a restart empties, so a fresh process must not report an
absence it cannot know. It fired when the buffer held **zero** links.

**The first live bundle fetched after the deploy, ten minutes later:**

```
opening_status.state : single_sender
buffer               : 1 links, window 1800 s
in_field             : anomalous_links 1, distinct_senders ['N2EDX']
```

One link in the ring — the link being asked about. `single_sender` reads as
"no second distinct sender appears in this field", which is true and worthless:
there was no second observation to be absent.

**The case that actually occurs is one, not zero**, because a bundle is
normally fetched for a link that is itself in the ring. So the false absence
this finding exists to remove came back at the boundary, inside its own fix.

Corrected in v3.2.92 to `<= 1`. Deliberately not a tuned threshold — it is
*the buffer contains nothing besides the link in question*, the point at which
the process has made no other observation at all. Verified live in the same
scenario: the state now reads `unknown` with the reason beside it.

**What this is worth recording for.** The defect was invisible offline. Every
planted fixture in `check_opening_state` had either a populated buffer or an
empty one, because those are the cases a person thinks of; the real world
served the third within ten minutes. Shipping it and looking at one live
bundle cost less than the test-writing that missed it would have. The check
now holds the case, so it cannot come back a third time.

---

## F-2026-08-26-06 — F-22 measured: grouping by gate would produce nothing, and the gap is a grid artefact

F-22 proposed grouping openings by receiving gate as well as by midpoint
field, on the reasoning that *the current rule cannot see the strongest
evidence there is — one gate hearing several distant unrelated senders*. It
was held back until a gate's trustworthiness could be measured, which arrived
in v3.2.88–90. Measured now. **Do not implement it.**

### The gap exists and is 1.1%

180 anomalous links over 7.74 hours, opening rule evaluated both ways inside
the same 30-minute window:

| | links | |
|---|---|---|
| both rules agree | 10 | 5.6% |
| field yes, gate no | 111 | 61.7% |
| **gate yes, field no** | **2** | **1.1%** |
| neither | 57 | 31.7% |

### And it produces no openings at all

Both gap links came from one gate, and both were flagged by the 300 km floor
alone:

```
LU8EB-1  -> LW7EEA-1  435.9 km  field=FF  established=False  '300 km floor alone'
CX1AA-2  -> LW7EEA-1  625.0 km  field=GF  established=False  '300 km floor alone'
```

`LW7EEA-1` had 12 samples. The opening loop already drops links whose gate is
not established — the operator's decision, taken with F-43 attached, because
on a freshly restarted process every gate is young and an opening built from
those would be announcing the restart rather than the ionosphere.

So: **additional openings gate grouping would produce: 0.** The field rule
found 13 in the same ring.

**The two filters compose, and that is the whole answer.** Gate grouping only
diverges from field grouping when one gate's senders lie far apart in
different directions — which happens most at gates with few samples, scattered
distant traffic and no established baseline. Those are exactly the links the
established filter already removes. The case F-22 was designed to catch and
the case the detector already declines to trust are the same case.

### The gap is a grid artefact, not the geometry F-22 imagined

The two fields are `FF` and `GF` — **adjacent**. The midpoints did not land
1,600 km apart; they landed either side of a Maidenhead boundary. A field is
20° × 10°, roughly 1600 × 1100 km, and two links sharing a gate have midpoints
separated by half the distance between their senders. For those to fall in
different fields the senders must be ~2,000 km apart *or* the midpoints must
straddle a grid line. Here it was the second.

That reframes the residual: what the field rule occasionally loses is not
"one gate hearing several senders" but **an opening cut in half by a grid
line**. If that is ever worth fixing, the fix is neighbouring-field grouping,
not gate grouping — and it would be a different finding with its own
measurement.

### What stays

`context.at_this_gate` (v3.2.91) keeps reporting the gate grouping beside the
field one on every bundle. It costs nothing, it is what made this measurable
in one command instead of a hand analysis, and it lets the decision be
revisited on a different window without shipping anything.

**A caveat on the sample.** One 7.74-hour ring on the worldwide feed. The gap
being 1.1% is a measurement; the gap producing zero openings rests on both its
links sharing one young gate, which is a small basis for a general claim even
though the composing argument above holds independently of it. Re-run
`measure_f22.py` on a later window before treating zero as permanent.

---

## F-2026-08-26-07 — a weather warning is not a station that fell silent

§E's *check first, before any code* asked one narrow question — are the
co-located `…SVR`/`…SVS` pairs four radios or one upstream feed? The answer
made the question obsolete. Shipped in v3.2.93.

### What they are

The NWS APRS gateway broadcasts severe-weather products as **ordinary
stations**, not objects: 557 of them in the live registry, one per
weather-service office per product. Their traffic is a message addressed to
`NWS-WARN`:

```
TBWSVR  :NWS-WARN :171915z,SVR_STORM,FLC053{R00AA
CTPSVR  :NWS-WARN :182230z,SVR_STORM,PAC023,PAC047,PAC083{G30AA
ABQFFW  :NWS-WARN :...,FLASH_FLOOD,...
```

`TBW` is Tampa Bay, `CTP` State College, `ABQ` Albuquerque. `SVR` is a severe
thunderstorm warning, `SVS` a severe weather statement, `FFW` a flash flood
warning. Symbol `\T` — thunderstorm — on 209 of the 219 `SVR`/`SVS` ones.

### Why counting them is wrong, not merely weak

Silence detection rests entirely on **cadence**: a station is silent when the
gap since its last packet exceeds 3× its own smoothed beacon interval. These
have no such interval to exceed. They transmit while a warning is in force and
say nothing for the days between.

**Their silence is fair weather, reported to an operator as a regional radio
outage.**

The object exclusion one line above in `silence_cells` already carries exactly
the right intent — *event advisory object — expires by design* — and misses
these only because they arrive as stations rather than objects. A validity
rule enforced at one entrance is not enforced; the fourth time this project
has written that sentence.

### F-25's founding case was this, not co-location

`EN03` — the cell F-25 was written from — appears in the stored history as:

```
EN03  6 stations, all weather products:
      ABRSVR, ABRSVS, FSDSVR, FSDSVS, UNRSVR
```

Aberdeen, Sioux Falls and Rapid City. And the *"two pairs sit roughly a
hundred metres apart"* that F-25 read as co-located sites are each office's
`SVR` and `SVS` **sharing one position, because they are one office**. The
proximity observation was correct and the inference from it was not: these are
not two sites behind one path, they are three offices' expired warnings.

### Measured

Over 14 days of stored snapshots:

| | |
|---|---|
| cell-snapshots touched | **4,073 of 21,865 (18.63%)** |
| emptied entirely | 1,442 (6.60%) |
| silent-station entries removed | 11,571 |
| **had 3+ silent, now under `min_silent = 3`** | **3,640** |

Live at deploy: cells fell 20 → 17, and `DM94` stopped alerting — it had 5
silent stations of which `LUBSVR` and `LUBSVS` were warnings.

**That last row is why this had to land before §D.** Calibrating `min_silent`
and `min_ratio` against a population where 16.6% of candidates are expired
weather warnings would have calibrated against noise, and the calibration
would have looked entirely reasonable.

### The rule matched on the addressee, and why not on the callsign

The tempting test is **"no digit in the base callsign"** — which this project's
own README already states as the way to tell a service addressee from an
allocated callsign, and which is true of all 557. It was measured and
rejected.

2,215 positioned stations in the registry carry no digit, and roughly half are
**real transmitters using tactical names**:

```
SADDLE     I#   South Saddle Mountain Digipeater
HOGBAK-10  L&   N1AF Hogback Mountain LoRa-APRS 433.
EUGENE     /_   PHG7380/W2,ORn-N,EUGENE 13.7V
KYIV-1     /r   Free radio repeater 446.225/434.850
OTISMA     /#   Digi I-Gate WX3in1v1
```

A mountain digipeater going quiet is precisely the news this detector exists
for. The digit rule would silence all of them.

Nor does the callsign suffix work: `TA8SVS` ends in `SVS` and is an operator
in Turkey, symbol `%`, comment *"Op.Volkan"*.

**The digit rule does survive as an independent check**, and it is worth
recording as one: of the 557 caught by the addressee test, **zero** carry a
digit in the base callsign. Two rules derived differently agreeing on the
whole set is the cheapest corroboration available.

`tools/check_event_broadcast.py` holds both directions, and the second is the
one that matters: it fails if someone replaces this with the digit rule,
naming each real transmitter that would be silenced. Verified that way before
being trusted — 7 problems.

### Left open

The ~1,097 positioned tactical-named stations that are *not* weather products
remain in the population. Whether an irregular beacon cadence should weaken a
station as a silence sensor — whatever it is called — is a larger design
question than §E's denominator, and deserves its own finding. The system
already measures the thing it would need: `ema_interval_s`.

Also unaffected: 440 no-digit stations with no position at all (`NTSGTE`,
`WLNK-1`, `AIS`, `EMAIL-2`). They contribute **0%** to silence cells already,
because a station needs a position to be placed in a Maidenhead square. No
rule required.

---

## F-2026-08-26-08 — the ratio counted callsigns while the alert beside it counted operators

§E's denominator, decided and shipped in v3.2.94. It closes the question F-25
opened in v3.2.25 and did not finish.

### Two units in one cell

`few_sites` has qualified alerts on **operators** since v3.2.25 — three SSIDs
of one base callsign are three radios in one shack on one power strip and
cannot fail independently. One line above it, the ratio went on dividing
**callsigns by callsigns**.

So a reader was told *"80% of this square fell silent"* about two operators,
one of whom was still transmitting.

### Measured before deciding

Over 20,423 stored cell-snapshots, with the v3.2.93 weather exclusion applied
first so the population was not the contaminated one:

| | |
|---|---|
| hold more callsigns than operators | **9,047 (44.30%)** |
| on those, mean silent count | 5.96 callsigns → **4.24 operators** |

Live at the time, 13 of 17 cells had `silent ≠ sites`. The plainest:

```
HD53  silent=3 sites=1  ['PU3AAG-D', 'PU3AAG-N', 'PU3AAG-Y']
NK94  silent=6 sites=3  ['E23JWE-N','E25VZX-10','HS7TRE-C','HS7TRE-D','HS7TRE-E','HS7TRE-F']
```

`HD53` counted three witnesses. It had one operator's D-Star, DMR and Fusion
ports.

### It is not a discount, and that had to be asserted

The textbook case falls: three radios of one operator, in a cell of three
operators, go from `3/5 = 0.60` — which clears `min_ratio = 0.5` — to
`1/3 = 0.33`, which does not.

But it also **rises**. Two operators in a cell, both silent, is 100% of that
cell's operators however many callsigns sit around them: `0.40` by the old
measure, `1.00` by the new one. Measured live across 17 cells the day it
shipped: **down 4, up 7, unchanged 6.**

`ML88` is the case worth keeping: `0.80 → 1.00`, two sites of two. The old
figure understated it.

`tools/check_silence_ratio.py` asserts the upward direction explicitly,
because a rewrite that can only lower the number has replaced the measure with
a discount and would pass every other assertion in the file.

### What it did not do, stated plainly

On the live snapshot the day it shipped, `threshold_met` went 17 → 17 and
`alert` went 2 → 2. **It changed no alert.** Its value is that the published
ratio now means what it says, and that `min_ratio` can be calibrated in §D
against the unit the alert is actually qualified on. Claiming an alert
improvement from this would be the move F-2026-08-25-04 had to correct.

### What was deliberately left alone

`threshold_met` keeps its raw callsign count. It is what the narrower
definition is measured against, and the entry has carried both since v3.2.25
precisely so the narrowing hides nothing.

`ratio_callsigns` is published beside the new ratio for the same reason:
fourteen days of stored snapshots were computed with the old figure and mean
what they were computed with. `baseline_sites` names the denominator, because
a ratio published without what it divided by is the defect F-2026-08-16-01b
names on the propagation side.

The denominator is accumulated as a set of base callsigns during the walk the
detector already makes — one string split and one set add per station. The
co-location grouping two blocks below is confined to the silent set because it
cannot afford the whole cell; this can, and the comment there says so.

### A measurement error worth recording

Re-deriving the history to answer this, I filtered the v3.2.93 weather
broadcasts out of stored snapshots and then asked how many had alerted with
fewer than three operators. The answer was 2,449 — apparently a live defect in
the `few_sites` demotion.

2,333 of them predated v3.2.25. The remaining **116 were all padded**: a
weather product supplied the third operator at the time they fired.

```
DM73  as stored     : ['ABQFFS', 'KJ7AZ-11', 'KJ7AZ-3', 'W5JXT-D']
      owners then   : ABQFFS, KJ7AZ, W5JXT = 3   -> alert
      after v3.2.93 : KJ7AZ, W5JXT = 2           -> demoted
```

`ABQFFS` is an Albuquerque flood statement. **The alert threshold was being
cleared by an expired weather product.** So the 116 are not a demotion failure
at all — they are independent evidence for the exclusion shipped an hour
earlier, arriving through a mistake in how I filtered.

The lesson is the applying-a-new-rule-retroactively one: a filter applied to
history answers *"what would this look like now"*, never *"what happened
then"*. Checking the code at the tag deployed on the day — identical to
today's — is what turned an apparent live defect into a confirmation.

---

## F-2026-08-26-09 — §D measured: leave both thresholds alone, and here is what holds them up

F-04 asked whether `min_silent = 3` and `min_ratio = 0.5` are right, having
never been measured against anything. Measured 2026-08-26. **Leave them
alone** — which `NEXT.md` said in advance would be a perfectly good outcome,
and is.

No code change. What follows is the reasoning, because the *reason* they are
right turns out to matter more than the verdict.

### F-04's premise was wrong, and that had to be fixed first

> *"Fourteen days of `silence_history` are available now, so this needs no
> preparation."*

`record_silence_history` stores `[c for c in silence_cells() if c["alert"]]`.
All **21,786** stored rows carry `alert = True`. History holds only the cells
that alerted, so it cannot say what the thresholds **rejected** — which is the
entire question.

Measured against the live registry instead: 204,678 stations, **2,125
candidate cells** with the thresholds opened to `min_silent=1, min_ratio=0.0`.
`silence_cells()` takes both as parameters, so the sweep is direct.

### `min_ratio = 0.5` sits on a quantisation spike

The ratio distribution is not smooth:

```
0.3  ###### 99
0.4  ##     30
0.5  ####### 66      <- spike
0.6  #       1       <- near-void
0.7  #      14
1.0  ######## 106
```

This is arithmetic, not physics. With few operators the ratio takes small
integer fractions: `1/2` and `2/4` both land on 0.50, while 0.60 needs exactly
`3/5`. **53 of the 66 cells at 0.50 are one operator of two.**

So the threshold is a cliff rather than a point on a continuum:

| `min_ratio` | `threshold_met` | `alert` |
|---|---|---|
| 0.49 | 26 | 9 |
| **0.50** | **26** | **9** |
| 0.51 | 17 | 5 |
| 0.60 | 17 | 5 |

A hair's move from 0.50 to 0.51 costs 44% of alerts; everything from 0.51 to
0.60 is the same decision. `min_ratio` is not a dial, it is **a switch that
admits or excludes "exactly half"**.

### But the fragility is benign, and that is the finding

The four alerts a move to 0.51 would remove are not the weak `1/2` cells:

```
FF96   3/6  operators silent, 2 independent gates
KM87   6/12 operators silent, 2 independent gates
PH57   3/6  operators silent
PN26   7/14 operators silent
```

**Half of a populated cell**, not one operator of two. Losing those would be a
real loss. Meanwhile the 53 `1/2` cells never reach an alert at all — they do
not clear `min_silent = 3` on callsigns, or `few_sites` demotes them for
having fewer than three operators.

And lowering to 0.40 would admit `3/7`, `5/11`, `4/10` — under half the cell,
a materially weaker claim.

So 0.5 is the boundary between *"at least half this cell's operators"* and
*"fewer than half"*, which is a meaningful line to draw about a region.

### `min_silent = 3` is doing its documented job

At `(3, 0.5)`: 2,125 cells → **26 clear the thresholds** → **9 alert**. The
qualifiers reject 17 of 26, by `few_sites` (9) and `no_local_path` (7).

Nine of the 26 admitted have fewer than three *operators* — `min_silent`
counts callsigns and `few_sites` requires the same number of operators. That
is not a defect: `threshold_met` is deliberately the raw result so the
narrowing hides nothing, and the narrowing is published beside it. The
pre-filter admits, the qualifier disqualifies, and both are visible.

### The one thing worth carrying forward

**The three gates are coupled, and `min_ratio = 0.5` is only safe because the
other two exist.** Fifty-three cells of a single silent operator sit exactly on
it, held back by `min_silent = 3` and `few_sites` rather than by the ratio.

Anyone who later loosens `min_silent`, or reworks `few_sites`, releases that
mass through a threshold that looks untouched. **Do not change one of the
three without re-running this sweep.**

That is the answer §D was actually worth asking for. The verdict — leave them
alone — was available by guessing; the coupling was not.

---

## F-2026-08-26-10 — the data we removed as a sensor is the correlation we were missing

Prompted by the operator asking whether `leolost2605/emergency-alerts` — a
Vala/GTK desktop app for GNOME, GPL-3.0 — has anything to give this project.

**No code can be taken.** GPL-3.0 into an MIT project is not a licence
question with a workaround; it would relicense everything. Nor is there
technical overlap: Vala, Meson, Flatpak, a Linux desktop target. What it does
have is one architectural idea — a pluggable *provider* abstraction for
official alert feeds — and that idea turns out to point at something already
sitting in our own database.

### The observation

Silence cells are correlated against **USGS earthquakes only** (500 km, 24 h).
An earthquake is a rare reason for a region to go quiet. Severe weather,
flooding and the power failures they cause are not.

And v3.2.93 had just finished *removing* 557 NWS severe-weather broadcasts
from the silence sensor set, because they have no beacon cadence to fall
silent against (F-2026-08-26-07). Their traffic carries everything a
correlation layer wants:

```
CTPSVR  :NWS-WARN :182230z,SVR_STORM,PAC023,PAC047,PAC083,PAC105,PAC123
```

A timestamp, a product type, and FIPS county codes. **The same data that was
noise in the sensor role is signal in the correlation role** — and it is
already arriving, already parsed, already positioned.

### The spatial gate: passed

| | |
|---|---|
| hazard broadcasters carrying a position | 548 |
| distinct Maidenhead cells they sit in | 232 |
| **cells with both a hazard broadcaster and a silence record** | **45** |
| silence snapshots in a field that also carries hazards | **5,245 of 21,671 (24.2 %)** |

Product mix: FLASH_FLOOD 174, SVR_STORM 104, SEVERE_WX 101, **TORNADO 51**,
FLOOD 44, MARINE 34.

Two of the 45 are the cells this whole thread was written from:

```
EN03   632 silence snapshots   hazards ABRSVR, UNRSVR, ABRSVS
DM94   236 silence snapshots   hazards AMAFFW, AMAFFS, LUBSVR
```

`EN03` is F-25's founding cell. `DM94` is the cell that stopped alerting when
v3.2.93 shipped. The offices whose *products* were polluting the sensor set
issue the warnings for exactly those areas.

### The temporal gate: cannot be tested with what we retain

The measurement above uses the **current** warning footprint against fourteen
days of silence. An NWS callsign is reused for every new warning from that
office, so the registry holds one position and one timestamp per office — the
latest. "A hazard broadcaster sits in cell X" is not "a warning was active
while X was silent", and nothing stored can close that gap.

**Stated rather than glossed**, because the tempting move is to report 24.2 %
as if it were a hit rate. It is not. It is the ceiling: no correlation can
exceed it, and the real figure is some unknown fraction of it.

### What that makes the next step

Not a feature. **Record hazard warnings as they arrive** — a small table like
`prop_history`, event-driven, pruned on the same retention window. It changes
no detection, costs one insert per warning, and in fourteen days the temporal
question answers itself. If the answer is near zero the idea dies having cost
a table; if it is not, `cause: "outage"` can become *"SVR_STORM, PAC023,
20 minutes earlier"* the way a quake already does.

### The honest limit on coverage

FIPS codes are US-only and NINA is Germany-only, while this feed is worldwide.
Only 12 of the 72 silence fields carry hazard broadcasters at all. Coverage
would be patchy in exactly the way the Turkey Repeaters DB is — which is fine,
and must be described that way rather than as a general capability.

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
