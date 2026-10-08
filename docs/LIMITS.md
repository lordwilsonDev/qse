# QSE v0.1 — honest limits

This file exists so that the interesting claims in `README.md` cannot be read as
broader than they are. Everything listed here is a real ceiling, not a roadmap
item disguised as one.

## The engine does not answer its own clarifying questions

The loop generates the question it should ask next, records why it chose that one
over the others, and then **stops** if nobody answers it. In `Engine.run` the
answers come from the scenario's `facts` block: an operator or a data owner
supplies `referential`, `scope`, `authority`, and so on.

So the contribution of v0.1 is *which* question to ask, the inversion →
hypothesis → experiment → build → attack → verify chain, and the audit trail.
It is **not** answering a clarifying question from the data. Nothing here reads
a table and works out what "bottleneck" should mean.

The answers are applied at decomposition, all at once, and recorded as `STATED`.
They are facts about the question, not discoveries: an earlier design applied
them one blocking slot per revision, which meant a brief that answered
`authority` was silently dropped unless the engine happened to ask about
`authority` — and the artifact was then refused for having none.

When a blocking slot cannot be answered, the run reports `blocked`, records
`R-QUE-1`, and names the question it would have asked. It does not guess.

## An ambiguity is reported against the question as it was asked

`detect(..., as_asked=True)` — what the controller uses — fires the rules on the
raw text and marks a finding `closed` when the operator's answer covers its slot.
The finding is kept, not deleted, so the ledger holds the defect and the repair
side by side and blindspot reduction has a `before` to subtract from.

The cost is that a fully briefed question still reports its original ambiguities,
with `closed: true`. Reading the count without the flag will overstate what is
still open. Read `closed` per finding.

## The runners are small declared procedures, not a statistics engine

Seven runners exist. Each is a few dozen lines of ordinary Python: a
nearest-rank threshold scan, a Youden separation, a Pearson correlation on
complete pairs, contingency counts, dispersion comparisons, coverage counts.
They are deterministic and they refuse to run without the columns they need.

They are not a causal-inference library. There is no propensity matching, no
instrumental variables, no difference-in-differences, no bootstrap. Where a
runner would need those to be honest, it returns `ran: false` with a reason
rather than a number.

Consequences you should expect:

- `attack_causality` will usually land on evidence that is only associational.
  That is the runner doing its job, not a bug.
- `attack_scope` is not auto-cleared by adding rows to the same file; the second
  source has to be genuinely separate (the shipped example uses a holdout drawn
  from a different seed and horizon).

## A planned experiment can be unrunnable, and it says so

The planner writes a threshold before it has seen any data, because it plans
from the hypothesis. On the shipped scenario that threshold is
`precursor_h >= 24`, and `precursor_h` in that data ranges over 7.4–14.6 hours,
so the test can never run. QSE records `EXPERIMENT_NOT_RUN` as a decision and
produces **no** evidence from it — a non-run is never a weak result.

The honest reading is that the plan is data-blind, not that the data is wrong. A
test that cannot fire is a fact about the plan, and it is better recorded than
silently dropped.

## The close-out is a reading of the ledger, and it shares the ledger's blind spots

`qse.cli closeout` answers the fifteen terminal questions from the records, and
labels each one. Two limits follow from that design and are not defects:

- It cannot report a fact the ledger never recorded. Where nothing was written it
  answers `UNKNOWN`, which is why `Q14` on an empty ledger refuses to critique
  anything: a critique of a process that left no records is not a critique.
- One item in `Q14` -- that cost, adoption and feasibility were never modelled --
  is labelled as coming from review rather than from the ledger, because no record
  can evidence what was never asked.

The `next_question` score weights the five factors with hand-chosen constants. It
ranks candidates and is declared ordinal in the output; it is not a probability.

## Reproducible is not the same as valid

`A15` can pass on an artifact that `A10` and `A12` fail: a `REJECTED` artifact
still reproduces deterministically. Reproducibility says the same input gives the
same output; it says nothing about whether the output should have been accepted.
A run can therefore show `A15` PASS next to `A10`/`A12` FAIL, and that is not a
contradiction — but a reader skimming for green can mistake it for validity.

## Thresholds are visible constants, and they are conventions

`CORRELATION_FLOOR` (0.10), `VARIANCE_RATIO_SUPPORT` (2.0),
`VARIANCE_RATIO_REFUTE` (1.2), `COVERAGE_GAP_SUPPORT` (0.20),
`DISCRIMINATION_MARGIN_FLOOR` (0.10), and the `precursor_detection` default of
6 hours are all hand-chosen. They are named constants precisely so they can be
argued with. None of them is calibrated against anything.

## Information gain is ordinal

`qse.control.feedback.information_gain` multiplies a per-kind weight by how many
open hypotheses stand on the question and whether the slot is still unresolved.
The resulting number ranks candidates. It is **not** an expected information
gain in the Shannon sense and it is not a probability. Nothing in QSE should be
read as calibrated because this number exists.

`question_generator`'s first-estimate gain is a coarser version of the same
idea, recorded as such so the two cannot be confused.

## The uncertainty load is not a probability either

`uncertainty_load` returns a mean of ordinal severities (BLOCKING 3, MATERIAL 2,
else 1). It is a label with a decimal point. It is documented as ordinal in the
module and in the returned dict.

## Self-verification is caught by name only

`R-VER-1` refuses when the verifier's name equals the builder's name, case-folded
and stripped. Two different strings can still be one person, one model in two
sessions, or a client and its own alias. Telling those apart needs something the
string cannot carry — a session id, a runner identity, a signed attestation.
v0.1 does not have that, and does not claim to.

## The hash chain cannot vouch for the last line

A backwards chain has nothing after the final line to disagree with it. Editing
the last line of a ledger is undetectable by `verify_chain`. `chain.tail()`
publishes the last line's hash so a later reader can notice a change, which is
the most this design can do. It is tested in
`test_the_tail_hash_is_published_because_the_last_line_is_uncovered`.

`verify_chain` also reports only the **first** break, because after one break
every later `prev` is meaningless by construction.

## QBY, BC, VI, EC and OC are definitions, not achievements

`QBY = 1.0` on the shipped scenario means one question produced one verified
artifact. It is not evidence that QSE works in general, and the denominator is
one. `OC` is `0.0` there because no real-world outcome exists to count: the run
records an artifact, not a company that shipped more orders on time.

The scorecard carries a `limits` list for the same reason, so a number never
travels without it.

## The blocked path is vacuous in one direction

`A16` (replayable) and `A17` (auditable reasons) are refused on an empty ledger
rather than passing vacuously, because "it replays" is a claim about a run and
there was no run. The reverse case is not caught: a ledger with exactly one
trivial question would satisfy A17 without demonstrating anything. The list
checks for the presence of a process, not for the process being hard.

## The fixture can now carry the moonshot's terminal test -- but it has not been scored

The terminal test -- *does engineered questioning create measurable capability
that would not otherwise exist* -- is a comparison, so it needs a counterfactual.
`qse.cli fixture` supplies the cheapest one (an analyst with no question
engineering takes the top correlate) and asks whether this fixture can punish it.

It can now. The holdout is generated (`scripts/generate_holdout.py`) as a period in
which the fitting-sample confounds are absent, so every column that outranks the
driver on the fit collapses on data the fit never saw:

```text
staff_on_shift    fit -0.810   holdout +0.047   <- the naive arm picks this
system_latency_ms fit +0.808   holdout +0.098
precursor_h       fit +0.798   holdout +0.351
handoffs          fit +0.798   holdout +0.839   <- the planted driver
```

`SEPARABLE: True`, exit 0. That is the necessary condition for the comparison to be
runnable, and it is all it is: a separable fixture means the naive arm *can* be
punished, not that the engineered arm wins.

The comparison has now been **run** (`qse.cli compare`), scoring both arms by the
same statistic -- Youden's J of the rule's flagged set against the outcome -- on the
holdout:

```text
arm          rule                      fit J  holdout J  flagged
naive        staff_on_shift <= 6.0      +0.826     +0.000      132
engineered   failed >= 24.0               n/a        n/a        -
```

The naive arm collapses (`+0.826` in-sample, `+0.000` out of sample), which is the
fixture working as intended. But the engineered arm **cannot be scored at all**: the
rule QSE built is a conservative default that flags on the outcome itself
(`failed >= 24`), which is circular and is reported as such rather than scored. So
the moonshot's terminal claim still does **not** hold -- not because the naive arm
won, but because the engineered arm produced no valid detector. `compare` exits `1`.

An earlier version of this file recorded the opposite result -- that the shipped
pair was `SEPARABLE: False`, because the decoys held out of sample as strongly as
the driver and `precursor_h` was a *deterministic* function of `handoffs`
(r = 1.000) and so tied it forever. That was corrected by generating a holdout that
removes the period-specific confounds, not by changing the audit.

**And on the current code the engine still does not land on a mechanism.** The
comparison above makes this concrete: the engine's verified artifact flags on the
outcome, so it is not a detector and cannot win the control-arm comparison. Its
discriminating experiment returns `INCONCLUSIVE (supported=None, refuted=False)`
on both datasets; the explanation it selects is a measurement objection
(`MEASUREMENT`/`TELEMETRY` -- "the data is insufficient to support ..."); and the
artifact it produces is a conservative default, whose own stated basis is that no
usable measured evidence reached the bar. `handoffs` appears in the ledger only as
a *candidate column* in experiment designs and in the artifact's required-columns
list -- never as the selected mechanism. So the fixture now distinguishes mechanism
from correlate, and the engineered arm still does not produce the mechanism.

An earlier version of this file claimed "the engine does find the `handoffs`
mechanism". That was true of an earlier controller and is **false of the code
shipped now**; it was corrected rather than left standing, because a claim like
that is exactly the kind a reader would trust without re-running.

## The scenario is synthetic, and the engine is told nothing

`examples/orders_scenario.json` is generated. Its intended driver is coordination
(`handoffs`); `recorded_wait_h` is truncated on the night shift and produces a
genuine Simpson flip; `supplier_lead_days` is missing for 17% of orders. None of
that is disclosed to QSE.

The correlated decoys are *misleading on the fitting period*: `system_latency_ms`
and `staff_on_shift` outrank the driver there. They are spurious in the sense the
comparison needs -- they collapse on the holdout, where the period-specific
confound is absent (see "The fixture can now carry the moonshot's terminal test").
The fitting sample is left as built; only the holdout is generated to remove the
confound, and that generation is a construction, not a discovery.

It is still a dataset a human built to be findable. Discovering structure in a
table that was constructed to contain structure is a weaker result than
discovering structure in a real company's records, and the shipped example
should not be cited as if it were the latter.
