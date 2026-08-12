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

### F-2026-08-12-01 — the AI note asserts simultaneity it never checked
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

### F-2026-08-13-13 — the decisive fact is missing from the bundle, and the classifier reads its absence as an outage
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

### F-2026-08-13-11 — the AI note is written without the cell's history
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
