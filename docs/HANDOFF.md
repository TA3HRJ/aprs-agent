# Handoff — state at v3.2.88

Written for a session starting cold. `NEXT.md` is the plan and `FINDINGS.md` is
the record; this file is only *where things stand right now* and what to do
first. If it disagrees with either of those, they win.

---

## Deployment

| | |
|---|---|
| VPS | 169.58.31.240, live at aprsagent.com, systemd unit `aprs-agent` |
| running | **v3.2.88** |
| repo HEAD | `dafbead`, clean, master and tag `v3.2.88` pushed |
| deploy | commit → push master → tag `vX.Y.Z` → `systemctl start aprs-update.service` on the VPS. Nothing else |
| every tag | **must** carry a `config.VERSION` bump |

Moving a tag is allowed and the updater copes: `git push origin --delete <tag>`
then re-tag. Doc-only commits do not need a tag.

`aprs-update.sh` only deploys tags matching `vX.Y.Z` exactly, installs against
`requirements-lock-linux.txt` as constraints, restarts, then polls
`/api/status` for up to 90 s and reports `Deploy OK: <tag> calisiyor` or fails
loudly.

**The repo on the VPS belongs to `aprs`, not root.** Run git there as
`sudo -u aprs git -C /opt/aprs-agent …` rather than adding a `safe.directory`
exception for root.

---

## The guard rail

Twelve checks in `tools/`, each one born from a live failure. Run them all
before tagging:

```
for c in tools/check_*.py; do python "$c" >/dev/null 2>&1 \
  && echo "  ok   $c" || echo "  FAIL $c"; done
```

Eleven run offline. **`check_prop_bundle.py` needs a live feed** — but *not* an
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

1. **Refuse to build an opening on a gate with the fixed-distance signature.**
   This *does* change detection, so it wants its own evidence and its own
   threshold. `fixed_distance` is already reported and decides nothing.
2. **§D — reset a deaf gate's baseline, or only report it?** Now decidable
   against 25 named cases rather than a hypothetical, and the split matters:
   the 7 fixed-distance ones cannot recover on their own, the other 18 can.
   Note DB0OAL, which prompted the original worry, healed without help.

### 2. Rest of Package B — F-09, F-22, F-23
Presentation, independent of each other. See `NEXT.md` §B. Two measurements
they were waiting on now exist, both from 2026-08-25 over a 7.4 h window of
200 links:

- **F-22's cheap pre-check:** 16 of 112 gates carried 2+ distinct senders.
- **F-09's repeat count:** 200 records are 128 distinct pairs, 112 gates, 95
  senders — 36% of records are repeats.

**F-22 and F-23 still must ship together**, and item 1 is why.

### 3. The README's F-03 sentence
It states *"76% of flags come from the floor alone and 87% of those would not
have been flagged had their gate been established."* The first clause is now
the wrong way round (F-2026-08-25-04): re-measured on 2026-08-25 it is 24%, as
gate baselines matured. The second clause was **not** re-measured and stands.
Public text, so house rule applies — draft first. Consider whether a figure
that moves with gate maturity should be quoted as a constant at all.

### 4. §D — silence threshold calibration
`min_silent = 3`, `min_ratio = 0.5`, never measured against anything.

### 5. §E — non-independent stations in a silence cell (F-25)
Feeds §D; no point before it.

### 6. §I — per-gate range mapping
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
