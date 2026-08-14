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
