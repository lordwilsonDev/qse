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

## Answered since (cross-reference)

The first entry's new question — "should the engine emit a detector at all, or an
explicit *no usable detector* artifact?" — is answered in the no-detector
direction: with nothing measured, the artifact now says so (`field: None`,
`validated: False`) instead of inventing a field. The mechanism-based detector
remains open.
