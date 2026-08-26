# Handoff — state at v3.2.97

Written for a session starting cold. `NEXT.md` is the plan and `FINDINGS.md` is
the record; this file is only *where things stand right now* and what to do
first. If it disagrees with either of those, they win.

---

## Deployment

| | |
|---|---|
| VPS | 169.58.31.240, live at aprsagent.com, systemd unit `aprs-agent` |
| running | **v3.2.97** |
| repo HEAD | `a75d422`, clean, master and tag `v3.2.97` pushed |
| deploy | commit → push master → tag `vX.Y.Z` → `systemctl start aprs-update.service` on the VPS. Nothing else |
| every tag | **must** carry a `config.VERSION` bump |

**Doc-only commits do not reach the VPS**, because `aprs-update.sh` deploys
tags and nothing else. That is right for `docs/`, which nobody reads there —
but `README.md`, `HELP.html` and `aprsconfig.toml.template` ship with the app,
so a correction to those should be carried by the next tag rather than left
sitting on master. v3.2.95 exists partly to do that.

Moving a tag is allowed and the updater copes: `git push origin --delete <tag>`
then re-tag. Doc-only commits do not need a tag.

`aprs-update.sh` only deploys tags matching `vX.Y.Z` exactly, installs against
`requirements-lock-linux.txt` as constraints, restarts, then polls
`/api/status` for up to 90 s and reports `Deploy OK: <tag> calisiyor` or fails
loudly.

**The repo on the VPS belongs to `aprs`, not root.** Run git there as
`sudo -u aprs git -C /opt/aprs-agent …` rather than adding a `safe.directory`
exception for root.


### Consistency, last audited 2026-08-26 at v3.2.95

Versions aligned across local, GitHub, the VPS and the running API. Every
hardcoded `3.2.x` string in the source is a historical provenance comment and
correct as written — do not "fix" them. `DEFAULTS` and
`aprsconfig.toml.template` agree on all 112 keys. `README.md`, `HELP.html`,
`aprsconfig.toml.template`, `config.py`, `station_db.py` and `web_gui.py` were
verified byte-for-byte identical between `git show HEAD:` and the VPS.

**Two figures still unmeasured**, both in the README's Silence Map row and both
predating v3.2.93's weather exclusion, which changed cell composition: *"23 of
36 cells"* (F-41) and the *"under 35 %"* novelty threshold.

---

## The guard rail

Seventeen checks in `tools/`, each one born from a live failure. Run them all
before tagging:

```
for c in tools/check_*.py; do python "$c" >/dev/null 2>&1 \
  && echo "  ok   $c" || echo "  FAIL $c"; done
```

Sixteen run offline. **`check_prop_bundle.py` needs a live feed** — but *not* an
admin API, which is what this file used to say. `/api/prop` and
`/api/prop/evidence` are both on the public app, so it runs from anywhere:

```
python tools/check_prop_bundle.py --base https://map.aprsagent.com --max 12
```

or on the VPS against `http://127.0.0.1:8080`, which is the default.

| check | what it defends |
|---|---|
| `check_unreachable` | statements after return/raise — a severed constructor cost a day of silent failure |
| `check_ascii` | accent folding, 4 of its 12 cases from real broken words |
| `check_replay` | a repeated question is answered again, not met with permanent silence |
| `check_selflookup` | the position lookup serves only the sender, and never without an age |
| `check_weather` | distance and age always present; no city guessed; a spent quota still answers |
| `check_health` | the badge cannot claim "active" about a module that is failing |
| `check_signature` | no callsign sign-off reaches the air; Turkish "de"/"da" survives |
| `check_feedlog` | packets never reach journald, errors always do |
| `check_coords` | no position off the Earth enters, by either door |
| `check_prop_ts` | the evidence bundle answers with the link that was asked for, at both doors |
| `check_deaf_gate` | a gate that can no longer flag is reported, not left to go quiet |
| `check_fixed_geometry` | a gate's own repeated distance cannot supply its own second sender |
| `check_opening_state` | an absent opening never reads as a negative finding |
| `check_event_broadcast` | a weather warning is never counted as a station that fell silent |
| `check_silence_ratio` | the ratio counts operators, and can rise as well as fall |
| `check_hazard_record` | a warning that beacons for an hour is one row, read from the live packet |
| `check_prop_bundle` | the evidence bundle cannot judge an event with numbers that event wrote |

---

## What is open, in order

### 1. F-23 — the gate anomalous fraction, now with a measured base rate
Promoted to the front because F-2026-08-25-03's correction (2026-08-26) turned
it from an idea into the only instrument that works.

The detector updates a gate's EMA baseline **before any validity test** — the
write is the first thing in the block, above `if dist < PROP_MIN_KM: return` —
and the only positional sanity it applies to a gate is a Null Island test. So a
gate in the wrong place teaches its own baseline from links measured to a
phantom position, its bar climbs, and real openings there stop being detectable.
That is the poisoned-baseline failure arriving through the gate rather than the
sender.

`position_corroboration` **does** check the gate — that part of the finding was
wrong — but it runs at export and grouping time, downstream of both the
detector and the baseline. And as a gate test it does not work: over 174 links
and 90 gates it caught 2, both Swedish callsigns reporting from Alicante, which
is a Swede on holiday and not a fault.

What separates the real cases, with no geography involved:

| signal | gates of 90 |
|---|---|
| prefix contradicts position | 2 (both false positives) |
| **every link flagged AND baseline under 20 samples** | **7** |

```
LB4CD-7     14 flags of 14 links   samples  6-19   max  333 km
VE2SIL-1    10 flags of 10 links   samples 10-19   max 2044 km
LZ2AB        8 flags of  8 links   samples  0- 7   max  388 km
```

The fraction alone is not enough — it also catches genuine consecutive openings
at mature gates (`HS5AC-10` at samples 5979–5980).

**Superseded the same day by F-2026-08-26-01, which is the better instrument.**
Do not widen the window as suggested above — it is unnecessary.
`meta.prop_gate_stats` persists `[samples, mean, var]` for all **8,422** gates,
so the population is 7,316 established rather than 90, and available instantly:

```
mean >= 1000 km AND sigma < 0.1 * mean   ->  13 gates
```

`KC3WJU-2` carries 793 links at 1250.5 km ± 0.4 km; `LU9DCE` 514 at 1694.9 km
with a sigma of exactly 0.0. No propagation produces that. Honest DX gates in
the same mean range have cv 0.1–0.5.

**And 25 of 7,316 established gates are permanently deaf** — their own bar has
climbed past the 5000 km ceiling, so no link can ever clear it. They stop
flagging silently and nothing reports it. `VE2SIL-1` and `LB4CD-7` were watched
crossing over inside one window: flagging every link while young, flagging
nothing the moment they became established.

**F-22 still must not ship without this**, though the original reason was
overstated: a contradicted link is already dropped before the opening grouping
(F-2026-08-15-46), so a misplaced gate cannot manufacture an opening today. The
reason to keep the order is that grouping by receiving gate starts trusting
gates, and nothing yet measures whether a gate deserves it.

**✅ The reporting half shipped in v3.2.88.** `/api/prop` carries `deaf_gates`
and `deaf`; the evidence bundle's calibration block carries
`gates_that_can_no_longer_flag`. Live immediately after the deploy: ring empty,
**25 reported, 7 of them fixed-distance** — the startup rebuild works, which is
the case `check_deaf_gate`'s seventh assertion exists for. Detection is
unchanged.

**Two decisions remain, both the operator's:**

1. ~~**Refuse to build an opening on a gate with the fixed-distance
   signature.**~~ **Shipped in v3.2.89** — see F-2026-08-26-03. The test is on
   the link rather than the gate: excluded only when it sits on the gate's own
   repeated value, `|km − mean| ≤ max(3σ, 1% of mean)`, so a signature gate
   measuring something *different* still counts. Replayed against the live
   database: 246 stored openings, **3 no longer reported (1.2%)**, 6 links
   excluded. Excluded from the grouping only — the link stays on the map, the
   same treatment F-2026-08-15-46 gives a position-contradicting link.

   **The other half of `VE2SIL-1` shipped in v3.2.90** — see F-2026-08-26-04.
   `PROP_GEOMETRY_MIN_SAMPLES = 5`, separate from `PROP_MIN_SAMPLES`, because
   "does this distance repeat" is a question about spread and converges far
   faster than "how far does this gate hear". Measured over 1,106 young gates:
   bar 5 catches 6 (0.54%), all under `cv` 0.006, two with sigma exactly zero;
   the nearest gate not caught sits at 0.10. `at_flag` carries
   `fixed_geometry` so the map stops drawing nineteen identical lines as
   nineteen discoveries.

   **It removes no additional stored openings** — still 3 of 246 — and that is
   stated rather than dressed up. Its value is prospective.

   **Item 1 is now closed.** What began as F-23 produced three shipped changes
   and two decisions; nothing on it is outstanding.
2. ~~**§D — reset a deaf gate's baseline, or only report it?**~~ **Answered
   2026-08-26: report only, and do not build a reset.** See F-2026-08-26-02.
   All 25 would flag their *average* link if reset — median 6.8× the floor —
   so a reset inverts the failure from silent-and-wrong to noisy-and-wrong,
   and noisy reaches the map and the notify channel. Every deaf gate sits at
   p98.96 or above of gate mean reach, where the median gate hears **20.6 km**;
   22 of the 45 gates with a mean past 1,000 km are already deaf. The deafness
   is an **accidental quarantine** holding close to the right set. Its fault is
   the mechanism, not the outcome — which is what decision 1 above addresses.

### 2. ~~F-22 — group openings by receiving gate~~ — MEASURED, NOT DOING IT
**Package B is closed.** F-09 and F-23 shipped in v3.2.91; F-22 was measured
on 2026-08-26 and declined. See F-2026-08-26-06.

180 links over 7.74 hours, the opening rule evaluated both ways: the gap where
gate grouping sees something the field rule misses is **2 links, 1.1%** — and
both were flagged by the 300 km floor alone, at a gate with 12 samples. The
opening loop already drops links whose gate is not established, so **the
additional openings gate grouping would produce is zero**, against 13 the
field rule found in the same ring.

The two filters compose: gate grouping only diverges where one gate's senders
lie far apart in different directions, which happens at young gates with
scattered distant traffic — exactly the links already excluded. The case F-22
wanted to catch and the case the detector already declines to trust are the
same case.

**And the gap is a grid artefact.** The two fields were `FF` and `GF`,
adjacent: the midpoints straddled a Maidenhead boundary rather than lying
1,600 km apart. If that is ever worth fixing the answer is neighbouring-field
grouping, not gate grouping, and it needs its own finding.

`context.at_this_gate` keeps reporting both groupings on every bundle, so this
can be revisited on a later window with `measure_f22.py` and no code change.

### 3. ~~The README's F-03 sentence~~ — CORRECTED 2026-08-26
Drafted, approved and applied. The propagation paragraph now says the
floor-only share **moves** — 76 % on 2026-08-15, 24 % on 2026-08-25 — and that
this is why the popup names the test rather than the page naming a number. The
companion 87 % figure was dropped rather than updated: measured once, and the
counterfactual needs `at_flag.gate_bar_km`, which is `null` for exactly the
floor-only population it describes.

Two omissions closed in the same edit: deaf gates (25 of 7,316) and the
fixed-geometry exclusion.

**The Silence Map row was corrected the same day.** Both exclusion forms are
named now, the ratio's change of units is stated with `ratio_callsigns` beside
it, and one wrong claim was removed: the row said the raw threshold result *"is
still what gets stored"*. It is not — `silence_history` has no `threshold_met`
column and stores only alerting cells, which is what made §D's sweep run
against the live registry instead.

**Two figures in that row were NOT re-measured** and both predate the v3.2.93
weather exclusion, which changed cell composition: *"23 of 36 cells"* (F-41)
and the *"under 35 %"* novelty threshold. Flagged rather than quietly left.

### 4. ~~§E — non-independent stations in a silence cell (F-25)~~ — CLOSED v3.2.94
**Before §D, not after it** — this file had the two the wrong way round until
2026-08-26, and the sentence "feeds §D; no point before it" left "it"
ambiguous. `NEXT.md`'s own heading settles it: *"E — new, and it feeds D"*.

The reporting half shipped in v3.2.25: cells carry `sites`,
`sites_colocated`, `independent_gates`, `self_gated` and `few_sites`.

**What is still open is one decision** — should the ratio count sites rather
than callsigns? Today `station_db.py:2282` reads

```
ratio = c["silent"] / c["baseline"]
```

and both ends count callsigns. Measured live on 2026-08-26, 20 cells:
**14 have `silent` != `sites`**, so the decision moves the ratio on most of
them. `HD53` reports 3 silent callsigns from **1 site**; `NK94` 6 from 3. Of
the three cells alerting at the time, `OM65` had 4 sites but
`independent_gates = 1` — four sites behind one path, which is F-25's original
EN03 case still live.

**✅ The check-first ran on 2026-08-26 and answered something bigger** — see
F-2026-08-26-07, shipped in v3.2.93. The `…SVR`/`…SVS` stations are **NWS
severe-weather broadcasts**, 557 of them, arriving as ordinary stations rather
than objects. They have no beacon cadence to fall silent against, so their
silence is fair weather reported as a regional outage. `EN03`, the cell F-25
was written from, was six expired warnings from three weather offices — the
"two pairs a hundred metres apart" are each office's SVR and SVS sharing one
position. Excluded now, matched on the `NWS-WARN` addressee.

That removed **3,640 cell-snapshots from having 3+ silent stations** (16.6% of
all of them), which is why it had to land before §D.

**✅ The denominator decision was made in v3.2.94** — see F-2026-08-26-08.
Both ends of the ratio count operators now, matching `few_sites`, which had
qualified alerts that way since v3.2.25 while the ratio beside it still
divided callsigns by callsigns. Re-measured on the cleaned population: 44.3%
of 20,423 cell-snapshots hold more callsigns than operators, and on those the
silent count falls 5.96 → 4.24.

It is not a discount — live the day it shipped, ratios moved **down 4, up 7,
unchanged 6**. `ML88` went 0.80 → 1.00 because both operators in it were
silent. And it changed **no alert**: `threshold_met` 17 → 17, `alert` 2 → 2.
What it bought is that `min_ratio` can now be calibrated against the unit the
alert is actually qualified on.

**§E is closed.**

### 5. ~~§D — silence threshold calibration~~ — MEASURED, LEAVE THEM ALONE
Answered 2026-08-26, see F-2026-08-26-09. No code change, and the reason is
worth more than the verdict.

**F-04's premise was wrong first.** `silence_history` stores only alerting
cells — all 21,786 rows carry `alert = True` — so fourteen days of it cannot
say what the thresholds rejected. Measured against the live registry instead:
204,678 stations, 2,125 candidate cells, `silence_cells()` swept directly
since it takes both thresholds as parameters.

**`min_ratio = 0.5` sits on a quantisation spike.** 53 of the 66 cells at
exactly 0.50 are one operator of two, because `1/2` and `2/4` both land there
while 0.60 needs exactly `3/5`. Moving to 0.51 costs 44% of alerts and 0.51
through 0.60 are identical — it is a switch, not a dial.

**The fragility is benign.** The four alerts a move to 0.51 removes are `3/6`,
`6/12`, `3/6`, `7/14` — half of a populated cell. The 53 weak ones never reach
an alert: `min_silent = 3` or `few_sites` stops them first.

**Carry this forward.** The three gates are coupled. `min_ratio = 0.5` is safe
only because `min_silent = 3` and `few_sites` hold back the mass sitting on
it. **Do not change one of the three without re-running the sweep** — a
loosened `min_silent` releases 53 single-operator cells through a threshold
that looks untouched.

### 6. Hazard correlation — ⏳ COLLECTING, measure on or after **2026-09-09**
The table shipped in v3.2.96 and is filling. **Its first four rows carried no
cell** and were therefore unjoinable — an NWS warning is a message and has no
coordinates; the position had to come from the station record. Fixed in
v3.2.97 (F-2026-08-26-11). Those four rows cannot be repaired and age out with
the retention window; **the fourteen days start from v3.2.97, not v3.2.96.** **Nothing reads it and no
detection depends on it** — that is deliberate, so the collection costs
nothing if the answer turns out to be no.

**Why the wait.** The spatial gate was measured on 2026-08-26 and passed: 45
cells hold both a hazard broadcaster and a silence record, 24.2 % of silence
snapshots sit in a field that carries hazards, and `EN03` (F-25's founding
cell) and `DM94` (the cell that stopped alerting at v3.2.93) are both among
them. The **temporal** gate could not be tested at all: an NWS callsign is
reused for every product from that office, so the registry holds one timestamp
and no history. Fourteen days of `hazard_history` is what makes it answerable.

**24.2 % is a ceiling, not a hit rate.** Do not quote it as one — see
F-2026-08-26-10.

**The measurement, when the table is ripe.** For each alerting silence
snapshot, was a warning active in the same cell within a window of its
`since`? Both tables carry `cell` and `ts`:

```sql
SELECT COUNT(*) FROM silence_history s
  JOIN hazard_history h ON h.cell = s.cell
 WHERE s.alert = 1 AND ABS(h.ts - s.ts) < 7200;
```

against `SELECT COUNT(*) FROM silence_history WHERE alert = 1` for the base
rate. If the share is near zero the idea dies having cost one table; if it is
not, `cause` can carry the warning the way it already carries a quake.

**Coverage is US-only** (FIPS), 12 of 72 silence fields. Describe it the way
the Turkey Repeaters DB is described, not as a general capability.

### 7. §I — per-gate range mapping
**DRAFT, operator's idea, nothing agreed.** RX is measurable and already being
measured; TX is not, and that is a data-availability fact, not an effort one.

### Closed since the last handoff
- **v3.2.87 verified on the live feed**, 2026-08-26 06:22, 7.4 h after the
  deploy: `sample: 12 of 173 links, 6 of them from pairs that repeat` →
  `0 problems`. Six repeat-pair links means the `ts` assertion actually ran;
  the same code before the fix produced 6 failures out of 12. Note the bar
  stated in the previous handoff — "12 of them from pairs that repeat" — was
  over-specified: hot links are sampled first, so 6 is simply all the pool
  held. The real bar is *some* repeat-pairs sampled **and** 0 problems.
- **F-03 answered again** (F-2026-08-25-04). The split flipped from 24/76 to
  76/24 as baselines matured. The 87% noise figure is untouched — the
  counterfactual needs `at_flag.gate_bar_km`, which is `null` for exactly the
  population it applies to.
- **F-2026-08-22-01 measured, and it is small.** Only 2 of 152 established
  gates have an own bar under 10 km; none under 1 km. The feared
  "established by count, bar still meaningless" case is rare on live data.
  Deprioritise unless it grows.
- **The floor is not manufacturing flags.** Of 200 links, 73 were floor-decided
  on gates whose own bar runs to a median of 177 km and a max of 293 km — all
  under 300, so those links would have cleared the gate's own standard too.
  There the floor is the stricter test.

### Not scheduled
- `active.ai` badge is done (§F, v3.2.78)
- §C is fully struck through
- MaxMind GeoLite2 key would add a country breakdown to `/stats`; nobody asked

---

## Verification still owed

**How much of the live anomaly list carries `fixed_geometry`.** Not
takeable at deploy time — the ring held 6 links fifteen minutes after
v3.2.90 went out, and a percentage from that would be the
F-2026-08-25-02 trap with the paint still wet. Run once the ring has
refilled (~32 links an hour):

```
curl -s http://127.0.0.1:8080/api/prop | python3 -c "import sys,json; d=json.load(sys.stdin); ls=d['links']; n=sum(1 for l in ls if (l.get('at_flag') or {}).get('fixed_geometry')); print(n, 'of', len(ls))"
```

---

## Open question, deliberately not decided

**~~A poisoned gate baseline is not repaired by fixing the parser.~~ Answered
2026-08-26 — see F-2026-08-26-01.** DB0OAL healed on its own: mean 96.8 km,
sigma 37.1 km, own bar 290.5 km, back under the floor after ~1,900 samples of
EMA decay. **No reset should be written.** What does *not* heal is a gate whose
own position is wrong, because the error is systematic — `SV1TNT-10` sits at
mean 4979.4 km with a sigma of 4.7 km and can never flag again. The §D question
that remains is narrower: whether the 25 permanently-deaf gates should be reset
or merely reported.

**Should `check_prop_bundle` fail when it cannot exercise the `ts` assertion?**
Today it reports the condition and exits 0. Making it fatal is the complete fix
and would turn the hour after every deploy red, which trains a reader to ignore
the colour. Alert fatigue against a silent hole — the operator's call, recorded
in F-2026-08-25-02 rather than settled inside someone else's fix.

---

## Traps this project has already paid for

Each of these cost real time. They are in `FINDINGS.md` in full; this is the
short form.

**A check can go green by being asked an easy question.** `check_prop_bundle`
exited 0 on 2026-08-22 and 1 on 2026-08-25 with no detector code changing
between them — the sample decided it. Measured side by side on one process in
one minute: 0 problems by first-N sampling, 6 by repeat-pair-first. A green
that is wrong costs more than a red that is noisy, because it closes the
question.

**Read how a number was produced before reading it as a finding.** "43 problems
/ 12 links" held for days because `--max 12` capped the sample — the pool was 33
one night and 93 the next. Same shape as the bundle artefact trap.

**A check can plant the input it should have demanded.**
`check_hazard_record` asserted that rows carry a Maidenhead cell, and passed,
because the fixture set `r["lat"], r["lon"]` by hand first — testing the
arithmetic and never the supply. The first four live rows had no position at
all. Written the same day as the trap below, by the same hand.

**A check that returns green having examined nothing is the same defect class
as the bug it hunts.** `check_prop_bundle` would have passed by reading an
empty ring after a deploy restart. An empty run is now a failure.

**Prove a new check fails before trusting that it passes.** `check_prop_ts` was
run against the reverted code first: 39 problems from the ring logic, 1 from
the stored-event door. A check that has only been seen to pass has not been
seen to work.

**Ask the server.** Three rounds of client-side guessing lost to one read of
the Apache log. The journal is now usable again for this — the packet feed no
longer floods it (v3.2.80) — but note it holds ~16 hours of history from before
that fix, and everything older is gone.

**Where an answer must contain something a model drops, or must not contain
something it invents, the code decides.** Distance, age and position are
template fields; a callsign sign-off is stripped after the fact. Three findings
say this. Do not re-argue it in the prompt.

**A validity rule enforced at one entrance is not enforced.** The parser and
`load_sqlite` are both doors. So are `_emit` and `feed`. So was the daily
quota, which guarded free answers as if they cost money. So were the ring and
the stored-event path in `get_prop_evidence` (v3.2.87).

**Never edit a source file with PowerShell `Get-Content` / `Set-Content`.**
That pair uses the console's default codepage, not UTF-8. Used once on
`config.py` for a one-line version bump it added a BOM and turned 13 lines of
box-drawing and em-dashes into mojibake — in the file whose own comment
records a mangled encoding writing over a real bot token. `check_unreachable`
caught it, because a BOM makes the file unparseable, which is the guard rail
earning its place on a fault nobody was hunting. Use the editor, or `git
checkout --` to undo.

**Write patch scripts to a file, not through a heredoc.** Backslash levels get
eaten; `\b` has arrived as a literal backspace more than once and the regex
then silently matches nothing while the script reports success.

**Chain with `&&`.** A doc-writing script failed, the chain continued, and a
tag shipped without the finding it claimed to carry.

**Assert after writing.** `str.replace` returns silently when it matches
nothing, and indentation differs between call sites that look identical.

---

## House rules

- No personal data in code, config defaults, or check fixtures — anonymised
  callsigns (`TA1ABC`, `YM1ABC`). Real callsigns are fine in `FINDINGS.md`,
  which is a record of what actually happened.
- Credits in `LICENSE` and code comments only. Nowhere else in code or UI.
- The service operator's identity belongs on the website, not in
  `README`/`HELP`/the repo — those reach other operators.
- English UI by default; ask about Turkish each time.
- Anything product-facing — naming, versions, credits, public text — gets a
  **draft** first. Do not implement and publish in one step.
- Anything that walks the whole registry goes off the event loop.
