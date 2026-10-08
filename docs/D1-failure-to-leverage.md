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
