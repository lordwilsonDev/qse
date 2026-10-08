# D1 — Failure-to-Leverage: the circular detector

Status: **LEVERAGE_CAPTURED**
Date: 2026-10-08
Method source: BlackSwanLabz Research Lab, *D1 — Failure-to-Leverage Compiler*
(`~/projects/blackswanlabz-research-lab/02-frameworks/d1-failure-to-leverage.md`,
compiler at `.../scripts/d1_failure_to_leverage_compiler.py`). QSE adopts the loop,
not the compiler: the framework is the lab's; this is one application of it.

> Turn every discovered problem into the highest-leverage reusable capability
> available from that discovery.

## research id

`qse-d1-0001` — the engineered arm's rule read the outcome it was meant to predict.

## problem

`qse.cli compare` (added to run the moonshot's terminal comparison on the now
separable fixture) reported the engineered arm as **unscoreable**: the rule QSE had
built and verified was `failed >= 24` — a threshold on `failed`, the very column the
rule is supposed to flag ahead of.

## observed event

On the shipped run the winning hypothesis's evidence kinds were
`aggregation_check`, `correlation_split`, `variance_compare` and `coverage_scan`.
None of them report a `field`/`threshold`, so `specification.measured_columns()`
returned empty, `BuildSpec.inputs` fell back to **all** columns (sorted
alphabetically), and `generator.default_rule`'s fallback took `spec.inputs[0]` —
which is `failed`.

## assumptions (all checked)

- A decision rule's `field` is applied to a row to decide before the outcome.
- The outcome column must therefore never be that field.
- The runners already name the outcome (`outcome` on some observations,
  `excluded_circular` on `discrimination_scan`), so the generator does not have to
  guess it.

## variables and provenance

- target failure, not environment or measurement failure (see Steel below);
- provenance: `qse/build/generator.py::default_rule`,
  `qse/build/specification.py::{measured_columns,from_hypothesis}`.

## failure (retained)

The rule `failed >= 24` resolves to a detector that flags nothing (no order has
`failed == 24`), and — worse — *if* the threshold had been reachable it would have
"predicted" the outcome from the outcome. **A failure is retained as an
observation**: the ledger run that produced `ART-e7bbfd82cf0b` is kept.

## inversion

| Assumption treated as settled | Inverted |
|---|---|
| "The fallback field is just the first input." | "The field must be a predictor, and no rule may read the outcome." |

## missing variable

**The identity of the outcome column was not represented as a constraint on rule
construction.** The data carried it (the runners reported it); the builder did not
consume it. `UNKNOWN` was silently converted to "any column" — the exact move the
lab's D1.3 forbids.

## causal attribution

The defect is in **rule construction** (`default_rule`'s fallback), amplified by
**specification** (`from_hypothesis` putting the outcome into `inputs`). It is *not*
in the runners, the ledger, or the fixture. A correct result with the wrong
attribution is still an attribution failure, so this is recorded explicitly.

## leverage — the controls

1. **`outcome_columns(evidence)`** reads the outcome name(s) back from the evidence
   (`outcome`, `excluded_circular`). One source of truth, in `specification.py`.
2. **`from_hypothesis`** excludes those columns from `inputs`; `measured_columns`
   no longer treats `outcome` as a field.
3. **`default_rule`** skips any observed/parsed rule whose field is an outcome, and
   its fallback picks the first non-outcome, non-identifier input — marking the
   choice `validated: False`, basis "chosen by construction, not by measurement".
4. **`compare`** never credits an **unvalidated** rule as a win, even when its
   separation looks high. A rule that wins by luck is not evidence that engineered
   questioning created the capability.

Ranked by impact × recurrence × generality ÷ cost (the D1 heuristic, not a law):
controls 1–3 score highest (they close the class of "rule reads what it predicts"
everywhere); control 4 is the honesty backstop for the terminal test.

## downstream dependencies

`qse.cli compare`, the engine's `build` stage, the artifact's `requires`, and the
`ART-*` records. All re-verified after the change.

## tests (reusable)

- `test_experiment_build.SpecificationAndGeneration.test_a_generated_rule_never_sits_on_the_outcome_it_predicts`
- `test_baseline.TheRulePrimitives.test_score_rule_scores_at_the_rules_own_threshold_not_the_best_one`
- `test_baseline.TheArmComparison.test_an_unvalidated_engineered_rule_is_reported_and_not_credited`

A second defect surfaced while making the first testable: `score_rule` had scored a
rule at the **best** threshold rather than the rule's own — so a rule that flags
nothing looked excellent (`J +0.916` beside `flagged: 0`). Fixed: score at the
rule's own threshold. Same class of fault — a number that did not mean what it said.

## steel (the boundary checks)

- **Boundary:** the change is confined to QSE's builder; no environment capability
  was altered to make the result.
- **Measurement context:** obtained under a frozen clock
  (`2026-10-07T12:00:00Z`); the verdict is clock-free (`TheClockDoesNotDecide`).
- **Observer:** the investigator (this session) changed QSE's own code; the
  comparison is therefore a *target* failure, and the fixture's separability was
  established by an independent probe (`qse.cli fixture`) before any rule changed.
- **Independence:** not claimed. The control-arm comparison still has no
  independent verifier path — see the close-out's Q10 (`UNKNOWN`).

## new question (the compiler's real output)

> What field *should* a decision rule sit on when the winning explanation is a
> measurement objection rather than a mechanism — and should the engine emit a
> detector at all, or an explicit "no usable detector" artifact?

That question did not exist before the failure. It is the prerequisite for the
engineered arm ever being scorable *and* creditable.

## stopping condition

No currently identified influential unknown remains untested at this boundary, and
the next question is recorded above. The loop is therefore closed at
`LEVERAGE_CAPTURED`, not at "nothing else could ever be missed."

---

# D1 — Failure-to-Leverage: the replay check that counted instead of checking

Status: **LEVERAGE_CAPTURED**
Date: 2026-10-08
Method source: BlackSwanLabz Research Lab, *D1 — Failure-to-Leverage Compiler*.

## research id

`qse-d1-0002` — A16 ("entire process replayable") failed on a healthy ledger.

## problem

`CLAIMS.md` C-002 runs `qse.cli selftest --ledger /tmp/qse-claims.jsonl`. A
`selftest` **appends** to the ledger it is given, so a second invocation — or a
second `verify-claims --run` against the same fixed path — put two runs in one
ledger. On that ledger A16 failed and `selftest` printed "16/17 hold".

## observed event

`verify-claims --run` reported `[FAIL] C-002 check exit 1 (expected 0)`. Replaying
the ledger by hand showed `errors 0`, `unknown_events 0`, chain intact — the ledger
was fine. The failure was in A16 itself:

```python
and expected["hypothesis"] == sum(1 for r in records if r.get("ev") == "hypothesis")
```

Two identical runs emit the same nine `HYP-*` ids; the state keys hypotheses by id,
so `len(state.hypotheses)` is 9 while hypothesis **events** number 18. 9 != 18.

## assumptions (all checked)

- A ledger is append-only and may hold more than one run — `chain.append` chains
  onto whatever is there, and the CLI takes a caller-supplied path.
- `State`'s dict buckets are **indexes**, not the record of truth; `records` is the
  record of truth (stated in `state.py`).
- Therefore a count equality between distinct ids and id-bearing events encodes a
  *one-run-per-ledger* assumption that was never part of the claim.

## variables and provenance

- target failure, not environment or measurement failure;
- provenance: `qse/cli.py::acceptance` (A16), `qse/control/state.py::{replay,_fold}`,
  `CLAIMS.md` C-002.

## failure (retained)

A16 is a **false alarm on legitimate input**: it reported a defect where none
existed. Kept as an observation — the two-run ledger `/tmp/qse-claims.jsonl` is
reproducible, and the new CLI test builds it on purpose.

## inversion

| Assumption treated as settled | Inverted |
|---|---|
| "One ledger means one run." | "One ledger means one *history*; a run is not privileged." |
| "Equal counts prove nothing was lost." | "Containment proves nothing was lost; equality proves no id repeated." |

## missing variable

**What "no event lost" actually means was never separated from "no id repeated."**
Counting distinct ids cannot be satisfied by an append-only ledger that legitimately
repeats ids; it silently replaced the property it was standing in for.

## causal attribution

The defect is in the **acceptance check** (`acceptance`'s A16), not in `replay`,
`_fold`, the ledger, or the runs. The engine is right; the test was wrong.

## leverage — the controls

1. **`State.unreplayed_ids(records)`** — for every keyed event type, the id the
   record names must be **present** in the state's bucket. Containment, not
   equality: true for one run and for many.
2. **A16** now passes iff `unknown == 0`, `errors` is empty, and
   `unreplayed_ids(records)` is empty. A record the fold cannot rebuild still
   fails (via `errors`); an event type it does not know still fails (via
   `unknown`); an id the state lacks still fails (via the new check).

Ranked by impact × recurrence × generality ÷ cost: control 1 scores highest — it
states the real property once, in the module that owns the fold. Control 2 composes
it into the acceptance row without widening the claim in its message ("no unknown
event types and no rebuild errors").

## downstream dependencies

`qse.cli.run/selftest/checks/closeout`, `CLAIMS.md` C-002/C-004, and the whole
suite. All re-verified after the change.

## tests (reusable)

- `test_acceptance.Auditability.test_replaying_the_same_run_twice_names_no_id_the_state_lacks`
- `test_acceptance.Auditability.test_an_id_an_event_names_but_the_state_lacks_is_reported`
- `test_acceptance.Auditability.test_a_record_the_fold_cannot_rebuild_fails_the_replay_check`
- `test_acceptance.TheCliVerdicts.test_a_second_identical_selftest_on_one_ledger_still_passes`

## steel (the boundary checks)

- **Boundary:** only the check changed; no data was altered to make the result.
- **Measurement context:** frozen clock; the verdict is clock-free.
- **Observer:** the session changed QSE's own check while auditing QSE's own claims
  — a target failure. The ledger was inspected independently (`qse.cli replay`)
  before any code changed, which is what showed the ledger was healthy.
- **Is-an-alarm-wrong test (the second control direction):** A16 must still FAIL on
  a ledger it *should* reject. Covered by
  `test_a_record_the_fold_cannot_rebuild_fails_the_replay_check`; the fix narrows
  the false positive, it does not disable the check.

## new question (the compiler's real output)

> A ledger holds no run id, so an id repeated *within a single run* (a genuine
> id-collision bug) is indistinguishable from the same id emitted by a second run.
> Should each run carry a run/session id so replay can tell the two apart?

That question did not exist before this failure.

## stopping condition

No currently identified influential unknown remains untested at this boundary, and
the next question is recorded above. Closed at `LEVERAGE_CAPTURED`.

---

# D1 — Failure-to-Leverage: the scan that measured the mechanism and could not name it

Status: **LEVERAGE_CAPTURED**
Date: 2026-10-08
Method source: BlackSwanLabz Research Lab, *D1 — Failure-to-Leverage Compiler*.

## research id

`qse-d1-0003` — a runner computed its decisive number, reported a decision, and the
number was thrown away before anything could consume it.

## problem

`qse.cli compare` still reported the engineered arm as **unscoreable** ("the rule
names no field") even though the run's own ledger held a `discrimination_scan` that
had **decided**. On the second source that scan reported `favours: "handoffs"`,
separation `0.9157`, margin `0.6041` over `precursor_h`. The engine had measured the
mechanism and named it; the artifact still said "no detector".

## observed event

`discrimination_scan` called `_youden(pairs)` — which returns
`(j, threshold, sensitivity, specificity, n)` — and unpacked
`separation, _, _, _, count`. The cut that produced the separation was computed and
discarded. `default_rule`'s branches need a `field` and a numeric `threshold`; the
scan reported neither, so it fell through to the detector-less fallback whose basis
said "no usable measured evidence exists" — which was false about the run it was
summarising.

## assumptions (all checked)

- A decision rule needs a field and a numeric threshold. A *separation* is not a
  rule, so the runner's output was not yet consumable.
- `_youden` already computes the cut and the two rates. Supplying them requires no
  new statistic and no second computation, so nothing has to be invented to close
  the gap.
- A margin below `DISCRIMINATION_MARGIN_FLOOR` means the data cannot choose. That is
  a real finding, and it is different from `favours: None` standing in for "no
  candidates".

## variables and provenance

- target failure, not environment or measurement failure;
- provenance: `qse/experiment/runner.py::discrimination_scan`,
  `qse/build/generator.py::default_rule`,
  `qse/build/specification.py::{measured_columns,favours}`.

## failure (retained)

The detector-less artifact `ART-e7bbfd82cf0b` and its ledger are kept. So is the
observation that is the point of this entry: a run that measured `handoffs` at
J `0.8719` on the fitting sample and `0.9157` on a second source **still emitted no
detector**, and every check in the apparatus passed.

## inversion

| Assumption treated as settled | Inverted |
|---|---|
| "A separation is a measurement; a rule is a construction." | "A separation *is* a rule with its cut attached — reporting one without the other is a measurement half-made." |
| "If the scan cannot decide, the engine cannot name a field." | "True — and it must then *say* what it could not separate. Silence is not a refusal; it is indistinguishable from finding nothing." |
| "Evidence is whatever the runner returned." | "A runner that throws away its own decisive number has not returned its evidence." |

## missing variable

**The cut.** The scalar the runner reported (`separation`) was never the thing the
builder needed (`field`, `op`, `threshold`), and nothing in the pipeline noticed the
gap because both were "a measurement".

## causal attribution

The defect is in the **runner's return value** (discarding `_youden`'s threshold),
amplified by the **builder's vocabulary** (`default_rule` could consume a field and a
threshold but never a decision). It is *not* in the ledger, the fixture, or the
verifier. A correct number that cannot be consumed is still a defect, and the
attribution is recorded rather than left to read as a fixture problem.

## leverage — the controls

1. **`discrimination_scan` reports the cut behind every candidate's separation**
   (`op`, `threshold`, `sensitivity`, `specificity`), from the same `_youden` call —
   no second statistic, so the ranking and the cut cannot disagree by construction.
2. **It reports `decided`, and `detector`** when it decided: the rule the
   measurement implies, so a consumer reads a decision instead of reconstructing one
   from a ranking by convention.
3. **It reports `contenders`** when it did not decide — the candidates inside the
   margin floor of the best — so a refusal names what it refused to separate.
4. **`default_rule` gains an explicit branch** that consumes a scan's `detector`. It
   sits *after* the two branches that name a rule measured for this hypothesis, so
   precedence only widens, and its `basis` records the source that decided, the
   separation and the margin over the runner-up. A scan that did not decide is
   skipped exactly as an unmeasured runner is.
5. **The fallback's `basis` distinguishes two findings**: nothing measured at all,
   versus a scan that measured and could not separate. The second names the best
   candidate and its contenders.
6. **`measured_columns` reads `favours`**, so the artifact's `inputs` name the column
   it actually reads. Before this the artifact declared the whole table as its input
   while reading one column of it — a smaller lie of the same shape as the big one.
7. **`compare` prints a field-provenance block**, read from the run's own ledger, and
   `_detector_provenance` refuses to state the win without saying which source named
   the field and which could not.

Ranked by impact × recurrence × generality ÷ cost: controls 1–2 score highest — they
close the class "a runner computes its decisive number and drops it" everywhere, at
the cost of one unpack. 3–5 are the honesty of refusals. 6 fixes a second, smaller
misstatement. 7 is the disclosure the win requires, and it is what makes the win
readable rather than merely true.

## downstream dependencies

`qse.cli compare/selftest/checks`, the engine's build stage, `CLAIMS.md` C-003
(retracted) and C-010–C-012, and the whole suite. All re-verified after the change.

## tests (reusable)

- `test_experiment_build.TheScanReportsItsMeasurement.test_every_candidate_carries_the_cut_that_produced_its_separation`
- `test_experiment_build.TheScanReportsItsMeasurement.test_the_reported_cut_is_the_cut_that_measured_that_separation`
- `test_experiment_build.TheScanReportsItsMeasurement.test_an_inconclusive_scan_names_the_contenders_it_could_not_separate`
- `test_experiment_build.TheScanReportsItsMeasurement.test_a_source_that_decides_reports_the_rule_it_decided_on`
- `test_experiment_build.SpecificationAndGeneration.test_a_scan_that_decided_is_how_the_builder_names_a_field`
- `test_experiment_build.SpecificationAndGeneration.test_a_scan_that_could_not_decide_leaves_the_artifact_detector_less_and_says_why`
- `test_baseline.TheArmComparison.test_the_shipped_fixture_is_scored_and_the_engineered_arm_wins_on_the_second_source`
- `test_baseline.TheArmComparison.test_the_engineered_arm_with_no_detector_is_reported_and_not_credited`

The **second control direction**, which D1 #2's lesson demands: a fix that only
widens is not a fix. `test_the_reported_cut_is_the_cut_that_measured_that_separation`
scores the reported cut on the same rows and requires it to reproduce the reported
separation; the uncredited control builds a fixture that is separable *and* on which
no source decides, and requires the refusal to still refuse.

## steel (the boundary checks)

- **Boundary:** only the runner's return value and the builder's consumption changed;
  no data, fixture or statistic was altered to make the result.
- **The comparison's own boundary, stated plainly:** the field is named by the scan
  over the **second source**, not the fitting one. On the fitting source the same scan
  cannot separate `handoffs` (`0.8719`) from `precursor_h` (`0.8719`) and
  `message_volume` (`0.8393`). So this is **not a single-table win**, and `compare`
  now says so in its own output rather than leaving it to this document. The
  engineered arm's advantage is that it ran the discriminating experiment on a second
  source before naming a mechanism — which is what the scenario's own `obligation`
  demanded ("must prove the precursor generalises across shifts and regions"). The
  naive arm is given one period. That asymmetry is the finding, not a hidden
  convenience.
- **Measurement context:** obtained under a frozen clock; the verdict is clock-free.
- **Observer:** the session changed QSE's own runner while auditing QSE's own
  comparison — a target failure. The run's ledger was inspected first, which is what
  showed the second source's scan had already decided.
- **Is-the-win-real test:** the engineered rule `handoffs >= 6.0` scores J `+0.9157`
  on the holdout with specificity `1.0`; the naive arm's `staff_on_shift <= 6.0`
  collapses to `−0.028`. Both arms are scored by the same statistic, at each rule's
  own threshold.
- **Is-the-cut-rigged test:** the cut the scan took came from the source that decided.
  The fitting sample's own best cut for the same column is also `6.0`, so nothing
  about the threshold differs between the two periods — but the honest statement is
  that the cut was measured on the deciding source, not that it was validated on both.

## new question (the compiler's real output)

> The artifact is titled for the winning hypothesis (`MEASUREMENT`/`TELEMETRY` — "the
> data is insufficient to support ...") while its rule sits on a field that
> hypothesis does not mention. Its `basis` records where the field came from, so the
> disagreement is visible; nothing forces the artifact's title, its acceptance
> criteria and its detector to be about the same explanation. Should a detector that
> names a field be built for the hypothesis whose mechanism that field is, even when
> another hypothesis won the synthesis?

That question did not exist before this failure.

## stopping condition

No currently identified influential unknown remains untested at this boundary, and
the next question is recorded above. Closed at `LEVERAGE_CAPTURED`.

---

# D1 — Failure-to-Leverage: the domain the engine could not be told about

Status: **LEVERAGE_CAPTURED**
Date: 2026-10-08
Method source: BlackSwanLabz Research Lab, *D1 — Failure-to-Leverage Compiler*.

## research id

`qse-d1-0004` — pointed at a second question, in a second domain, the engine found
nothing and said nothing had gone wrong.

## problem

MOONSHOT-C reruns the moonshot's terminal comparison on a second, unrelated
question — a cloud bill finance cannot explain — and ships it as one script,
`moonshot_cloud.py`. On a real cloud table the engine reported "no explanation
found" while every experiment in the plan had come back `ran: false`. The engine
was not broken and the data was not wrong: the planner guessed conventional
*business-workflow* column names, and a cloud table has none of them.

## observed event

`planner._guess` binds `outcome=failed`, `precursor=queue_wait_h`,
`group=shift`, `field=precursor`, and so on. On the shipped orders fixture those
names exist by coincidence, so the guess never showed. On cloud data every runner
came back `ran: false` — "needs column `queue_wait_h`" — and the run recorded no
evidence and reported no defect, because "no experiment could run" is not itself a
refusal. Four further faults surfaced behind it:

- **The outcome-derived column.** `billed_usd` correlates with the `over_budget`
  flag near-perfectly, because the flag is computed from it. With no way to declare
  that, the naive arm picked the bill to explain the bill.
- **One period is not enough.** The fitting period's own scan decided confidently on
  `vcpus` — a column that only holds on that period because the idleness metric was
  estimated by a sampling agent wrong in both directions and `vcpus` was taken from a
  review list that tracked true idleness. The column that ships must be one the
  other source still supports.
- **The probe rule.** The planner binds `threshold=24` before it has seen any data.
  `counterfactual_replay` reported that rule under `rule`, the key the builder reads
  as a *measured* rule, so a data-blind placeholder could become the artifact's
  detector.
- **A07's false alarm.** A07 required a `KNOWLEDGE_GAP` decision. The cloud run
  found none — every explanation had usable evidence — so A07 failed a run that had
  simply found no gap.

## assumptions (all checked)

- A column name is a fact about a table, not something the engine can infer. The
  caller must be able to declare it.
- A column computed from the outcome is never an explanation for it. The caller must
  be able to say so, and the default must be to keep it out, not to keep it in.
- A measurement made on one period is not a measurement that holds on another until
  the other source says it does.
- A threshold nobody measured is a probe, and the key it is reported under decides
  whether a builder can mistake it for a measurement.

## variables and provenance

- target failure, not environment or measurement failure;
- provenance: `qse/experiment/planner.py::{_guess,_binder,roles_for,excluded_columns}`,
  `qse/experiment/runner.py::counterfactual_replay`, `qse/build/generator.py::{separation_of,default_rule}`,
  `qse/baseline.py::score_arms`, `qse/cli.py::{acceptance,detector_provenance,cmd_fixture}`,
  `qse/control/controller.py::run`.

## failure (retained)

The first MOONSHOT-C run recorded **0 evidence** and reported nothing wrong, and
that run's shape is kept as the thing the entry is about. So is the naive arm's
cloud pick: `vcpus >= 16.0`, fit J `+0.885`, holdout J `-0.003`.

## inversion

| Assumption treated as settled | Inverted |
|---|---|
| "The planner can guess the columns." | "A guess is a convenience for one domain's naming, not a capability; a caller must be able to *tell* the engine what a column is." |
| "Any column can explain the outcome." | "A column computed from the outcome explains nothing — it *is* the outcome, renamed." |
| "A scan that decided has named the field." | "A scan has named a field *for the period it ran on*; another period can show the choice was an artifact of that period." |
| "A runner's rule is a rule." | "A rule declared before any data was seen is a probe, and the key it travels under must say so." |
| "Found no gap" and "never looked" are the same record." | "They are different findings, and a check that accepts only the first fails the second." |

## missing variable

**The caller's declaration.** The engine had one implicit table of column names, in
`_guess`, and no way to be told a different one — so every domain but the one it was
written against looked like a dataset with no usable columns.

## causal attribution

The primary defect is in **planning** (`_guess` treated as the only source of column
names, rather than as a fallback under a declaration). Amplified by **specification**
(no way to exclude the outcome's derivatives), by **rule construction** (the probe's
key), and by a check (**A07**). It is *not* in the runners, the ledger, the fixture,
or the verifier — those behaved correctly on a table they were never told how to
read.

## leverage — the controls

1. **Declared roles.** `roles_for(roles)` separates engine keys from runner roles;
   `_binder(runner, columns, roles)` makes the guess *first* and layers the caller's
   declaration over it, so a declared `outcome` fixes every runner at once while
   undeclared roles keep their conventional guess. `Engine.run`/`plan`/`build` thread
   it through; the CLI exposes it as repeated `--role ROLE=COLUMN`.
2. **`exclude`.** `excluded_columns(roles)` names columns derived from the outcome;
   they are stripped from `rank_correlates`/`audit`, from `specification.outcomes`
   and from every multi-valued role, so a derived column is never a candidate and
   never an artifact input. `--exclude COLUMN` on `run`/`fixture`/`compare`.
3. **Cross-source replication.** `separation_of(observed, field)` reads what a scan
   measured for a field, and it distinguishes "this source ranked the field low"
   from "this source never ranked it" (`None` is not `0.0`). `default_rule` ships a
   scan-decided field only if *every other* scan that ranked it measured
   `abs(separation) > CORRELATION_FLOOR`; a field that fails is named in the `basis`
   — the rejection is the finding, not a silent drop.
4. **The probe.** `counterfactual_replay` reports its hypothetical rule under
   `probe_rule` with `probe: True`, never under `rule`, so the builder cannot read a
   data-blind placeholder as a measurement.
5. **`score_arms`.** The credit decision (does the engineered arm beat the naive one
   by the margin, and was the engineered rule validated?) lives in one function,
   `baseline.score_arms`, so `compare` and `moonshot_cloud.py` cannot disagree about
   what a win is.
6. **`EVIDENCE_COVERAGE`.** The controller records a decision after the
   `KNOWLEDGE_GAP` loop — `chosen` = how many explanations carry usable evidence,
   `unsupported`, `checked` — and **A07** passes when that decision exists, so
   "scanned and found none" passes while an empty ledger still fails.
7. **Exit-code honesty in the script.** `moonshot_cloud.py` raises `Unusable` (and
   returns `2`) rather than `SystemExit(str)`, because `SystemExit` with a string
   exits `1` — which would report unusable input as a *defect* and make the exit code
   a different answer from the printed one.

Ranked by impact × recurrence × generality ÷ cost: controls 1–2 score highest — they
close the class "the engine was never told what a column is" everywhere, and the
class "a rule read the thing it predicts" through a second door. 3–4 are the honesty
of a win and a probe. 5 centralises the credit rule so two callers cannot differ. 6
fixes a false alarm. 7 keeps the exit code and the page from disagreeing.

## downstream dependencies

`moonshot_cloud.py`, `qse/cloud/scenario.py`, `qse.cli run/fixture/compare/checks`,
`qse.baseline` (all three public functions gained `exclude=`, plus the new
`score_arms`), the engine's plan/build stages, `CLAIMS.md` C-013–C-017, and the whole
suite. All re-verified after the change.

## tests (reusable)

- `test_cloud_moonshot.TheCloudFixture.test_the_fixture_can_punish_the_naive_arm_once_the_outcome_derived_column_is_declared`
- `test_cloud_moonshot.TheCloudFixture.test_the_bill_is_never_offered_as_an_explanation_for_the_bill`
- `test_cloud_moonshot.ThePlannerHasToBeTold.test_without_declared_roles_every_experiment_fails_to_find_its_columns`
- `test_cloud_moonshot.ThePlannerHasToBeTold.test_with_declared_roles_the_same_experiments_run`
- `test_cloud_moonshot.CrossSourceReplication.test_a_field_the_other_source_rejects_is_not_shipped`
- `test_cloud_moonshot.CrossSourceReplication.test_a_field_that_holds_on_neither_source_is_not_named`
- `test_cloud_moonshot.TheProbeRule.test_the_replay_runner_reports_its_hypothetical_rule_as_a_probe`
- `test_cloud_moonshot.TheAcceptanceListOnACleanRun.test_a07_passes_when_sufficiency_was_scanned_and_found_no_gap`
- `test_cloud_moonshot.TheMoonshotScript.test_the_synthetic_run_answers_its_own_question`
- `test_cloud_moonshot.TheMoonshotScript.test_real_data_without_a_named_outcome_is_unusable`

The **second control direction**, which D1 #2's lesson demands:
`test_without_declared_roles_every_experiment_fails_to_find_its_columns` pins the
*defect* — with no declaration, every experiment fails — so the fix is shown to be a
widening of what can be told to the engine, not a change to what the engine does with
what it knows. `test_a_field_that_holds_on_neither_source_is_not_named` requires the
refusal to still refuse when replication genuinely fails, and
`test_the_bill_is_never_offered_as_an_explanation_for_the_bill` requires the
comparison to be *meaningless* without the exclusion, so the control is load-bearing.

## steel (the boundary checks)

- **Boundary:** every change is in QSE's own planner/builder/checks and the new script;
  no fixture was reshaped to make a result, and the synthetic cloud fixture's
  parameters are documented in `qse/cloud/scenario.py` as a tuning record.
- **The comparison's own boundary, stated plainly:** on the cloud fixture the field
  `idle_hours` is named by the scan over the **second** period, and the fitting
  period's scan decides on `vcpus` instead (`0.885`), which does not replicate and is
  rejected rather than shipped. So this, too, is **not a single-table win**, and
  `moonshot_cloud.py` and `compare` print the provenance rather than burying it.
- **Measurement context:** obtained under a frozen clock (`2026-10-08T12:00:00Z`);
  the verdict is clock-free.
- **Observer:** the session changed QSE's own planner while pointing QSE at a new
  domain — a target failure. The no-declaration run was reproduced first, which is
  what showed the experiments were failing on guessed names.
- **A planned test that cannot fire is honest, not hidden:** the counterfactual probes
  bind `threshold=24`; `idle_hours` never reaches 24 on the cloud holdout, so the
  probes record `EXPERIMENT_NOT_RUN` and produce no evidence. `test_with_declared_roles_the_same_experiments_run`
  asserts the only unrunnable tests are those declared probes, rather than asserting
  that none may exist. Q14 reports the same fact as a planning defect.

## new question (the compiler's real output)

> The probe binds a threshold before it has seen any data, and on this fixture the
> value it happened to pick (`24`) cannot fire. Should a runner that is answering "what
> threshold does this data support?" be allowed to choose its own candidate set of
> thresholds from the data it has, and report *which* candidate rule it replayed — or
> does that turn a declared probe into a fitted measurement and lose the distinction
> this entry just made?

That question did not exist before this failure. It is the boundary between a probe
and a fit, and it is not obvious which side keeps the engine honest.

## stopping condition

No currently identified influential unknown remains untested at this boundary, and
the next question is recorded above. Closed at `LEVERAGE_CAPTURED`.

---

## Answered since (cross-reference)

- Entry #1's new question — "should the engine emit a detector at all, or an explicit
  *no usable detector* artifact?" — is answered twice over. With nothing measured the
  artifact says so (`field: None`, `validated: False`) instead of inventing a field;
  and with a scan that decided, the engine now **does** emit a mechanism detector
  (`field: handoffs`, `validated: True`) instead of a detector-less one. The
  mechanism-based detector is no longer open.
- Entry #2's new question — should each run carry a run/session id, so an id repeated
  *within* one run can be told from a repeat across runs? — remains open. The ledger
  still holds a history rather than a run.
- Entry #3's new question — should a detector that names a field be built for the
  hypothesis whose mechanism that field is, even when another hypothesis won the
  synthesis? — remains open. On MOONSHOT-C the artifact is titled for the winning
  hypothesis while its rule sits on `idle_hours`, the same disagreement entry #3
  recorded, now reproduced in a second domain.
- Entry #4's new question — should a probe be allowed to choose its own candidate
  thresholds from the data, or does that turn a declared probe into a fitted
  measurement? — is open, and it is the boundary the probe/measurement distinction
  rests on.
