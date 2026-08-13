# What to do next — draft

A proposed order for the open items in [FINDINGS.md](FINDINGS.md). This is a
plan, not a record: it gets rewritten as work lands. Nothing here is a new
feature; every item makes something that already exists tell the truth.

The ordering principle: **fix what actively misinforms someone before fixing
what merely under-informs them.**

---

## A · The silence alert chain — first, and not close

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

---

## B · Propagation evidence — second

The bundle currently contradicts itself, and the fix unblocks the calibration
that has been waiting since July.

| finding | change |
|---|---|
| **F-16** | record the gate's `samples`, `mean`, `sigma` and threshold **as they stood at flag time**, on the link. Show both that and the current baseline |
| **F-03** | with that field recorded, count how many of the anomalies came from gates below the 20-sample threshold. Then decide whether the absolute-floor branch is producing signal or noise — with numbers, not judgement |
| **F-02** | when `established` is false, say plainly that mean and sigma are not meaningful yet and that the floor alone decided |
| **F-09** | replace `opening: null` with three states — a recorded event exists / the rule is met right now but nothing was written / genuinely one sender. Add the live field context (other anomalous links and distinct senders in the same field) and the repeat count for this sender→gate pair |

**Order inside B:** F-16 first — it is one field, and both F-03 and F-02 lean on
it. F-09 is independent and can go in the same release or the next.

**Files:** `station_db.py` (`_prop_links.append`, `gate_baseline`,
`find_prop_event`), `web_gui.py` (`get_prop_evidence`).

**Risk:** low. Additive fields plus one wording change.

**Verify:** a link whose printed baseline says it should not have been flagged
must also carry the baseline that did flag it, and the two must differ in the
direction the caveat describes.

**Note:** F-03's measurement needs a few days of data after the field ships.
That waiting period is the reason to start B soon even though A matters more.

---

## C · Text and ergonomics — cheap, ride along with A or B

| finding | change |
|---|---|
| **F-14b** | sharpen the symbol caveat: *the symbol is a fixed setting chosen when the station was configured; it does not change with conditions and reports nothing about the current weather.* A caveat has to close the inference, not name the source |
| **F-10** | split the export prompts into the three questions that actually have different answers — is it anomalous, is it an opening/cluster, is the underlying thing physically real |
| **F-12** | `?blind=1` to omit the whole `assessment` block server-side, plus a "copy blind" action, so a blind pass never depends on hand-editing JSON |
| **F-15c** | move the copy feedback into the button itself. The message at the bottom of the page was missed twice, and it was right both times |

**Risk:** none worth naming. Text, one query parameter, one small piece of UI.

---

## D · Silence threshold calibration — whenever

**F-04.** `min_silent = 3` and `min_ratio = 0.5` have never been measured
against anything. Fourteen days of `silence_history` are available now, so this
needs no preparation — only someone's attention. It is an analysis, not a code
change, and its answer may well be "leave them alone", which is a perfectly
good outcome to have on record.

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
