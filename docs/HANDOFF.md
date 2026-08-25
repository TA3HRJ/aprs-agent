# Handoff — state at v3.2.86

Written for a session starting cold. `NEXT.md` is the plan and `FINDINGS.md` is
the record; this file is only *where things stand right now* and what to do
first. If it disagrees with either of those, they win.

---

## Deployment

| | |
|---|---|
| VPS | 169.58.31.240, live at aprsagent.com, systemd unit `aprs-agent` |
| running | **v3.2.86** |
| repo HEAD | `beea580`, clean, master and tag pushed |
| deploy | commit → push master → tag `vX.Y.Z` → `systemctl start aprs-update.service` on the VPS. Nothing else |
| every tag | **must** carry a `config.VERSION` bump |

Moving a tag is allowed and the updater copes: `git push origin --delete <tag>`
then re-tag. Doc-only commits do not need a tag.

---

## The guard rail

Ten checks in `tools/`, each one born from a live failure. Run them all before
tagging:

```
for c in tools/check_*.py; do python "$c" >/dev/null 2>&1 \
  && echo "  ok   $c" || echo "  FAIL $c"; done
```

Nine run offline. **`check_prop_bundle.py` needs a live admin API**, which is
localhost-only in production, so it runs on the VPS:

```
cd /opt/aprs-agent && python3 tools/check_prop_bundle.py --max 12
```

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
| `check_prop_bundle` | the evidence bundle cannot judge an event with numbers that event wrote |

---

## What is open, in order

### 1. Rest of Package B — F-09, F-22, F-23
Presentation only, independent of each other, unchanged by the head that
shipped. See `NEXT.md` §B.

### 2. F-03 — the absolute-floor branch
**Its measurement clock started when B's head shipped.** The field it needs now
exists; it wants a few days of data before the question can be answered with
numbers rather than judgement. Nothing to do but wait, then count.

### 3. New OPEN from F-2026-08-22-01
The opening alert filters on `at_flag.established`, and a gate can be
established by sample count while its baseline is still meaningless.

### 4. §D — silence threshold calibration
`min_silent = 3`, `min_ratio = 0.5`, never measured against anything.

### 5. §E — non-independent stations in a silence cell (F-25)
Feeds §D; no point before it.

### 6. §I — per-gate range mapping
**DRAFT, operator's idea, nothing agreed.** RX is measurable and already being
measured; TX is not, and that is a data-availability fact, not an effort one.

### Not scheduled
- `active.ai` badge is done (§F, v3.2.78)
- §C is fully struck through
- MaxMind GeoLite2 key would add a country breakdown to `/stats`; nobody asked

---

## Verification still owed

**Run `check_prop_bundle.py` on the VPS once the ring has refilled.** The
deploy restarts the service and empties the in-memory link ring, which refills
at roughly 25 links an hour. The fifth assertion (no endpoint off the Earth)
has never been exercised against live data — it was written and shipped in the
same hour as the fix that should make it pass.

---

## Open question, deliberately not decided

**A poisoned gate baseline is not repaired by fixing the parser.** DB0OAL shows
mean 317.8 km and sigma 1019.6 km at flag time, and nine samples later mean
1518.6 km, sigma 2167.5 km. For an EMA at alpha = 0.05 to move that far in nine
steps the arrivals must average about 3565 km, so it was a stream, not one
packet. A gate whose sigma is 3.2x its mean will not flag the next real
opening. Whether affected baselines should be reset, and how such a gate is
identified, belongs to §D.

---

## Traps this project has already paid for

Each of these cost real time. They are in `FINDINGS.md` in full; this is the
short form.

**Read how a number was produced before reading it as a finding.** "43 problems
/ 12 links" held for days because `--max 12` capped the sample — the pool was 33
one night and 93 the next. Same shape as the bundle artefact trap.

**A check that returns green having examined nothing is the same defect class
as the bug it hunts.** `check_prop_bundle` would have passed by reading an
empty ring after a deploy restart. An empty run is now a failure.

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
quota, which guarded free answers as if they cost money.

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
