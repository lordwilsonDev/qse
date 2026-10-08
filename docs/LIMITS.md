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

## The shipped fixture cannot measure the moonshot's own terminal test

The terminal test -- *does engineered questioning create measurable capability
that would not otherwise exist* -- is a comparison, so it needs a counterfactual.
`qse.cli fixture` supplies the cheapest one (an analyst with no question
engineering takes the top correlate) and asks whether this fixture can punish it.

It cannot. Measured on the two shipped samples:

```text
staff_on_shift    fit -0.810   holdout -0.791   <- the naive arm picks this
system_latency_ms fit +0.808   holdout +0.809
handoffs          fit +0.798   holdout +0.784   <- the planted driver
```

The columns the scenario calls misleading correlates are *not* misleading in the
statistical sense: they are as predictive on data the fit never saw as the driver
is. So the naive arm would be right enough to count, and any claim that the
engineered arm did better on this fixture rests on nothing.

What this means concretely: the moonshot's headline question is **unmeasurable
here**, not answered. A fixture can only carry the comparison if its decoys are
*spurious* -- strong in-sample, collapsed out of sample -- and these are not.

**And on the current code the engine does not land on a mechanism either.** Its
discriminating experiment returns `INCONCLUSIVE (supported=None, refuted=False)`
on both datasets; the explanation it selects is a measurement objection
(`MEASUREMENT`/`TELEMETRY` -- "the data is insufficient to support ..."); and the
artifact it produces is a conservative default, `failed >= 24.0 -> escalate`,
whose own stated basis is that no usable measured evidence reached the bar.
`handoffs` appears in the ledger only as a *candidate column* in experiment
designs and in the artifact's required-columns list -- never as the selected
mechanism. Two explanations are left open as knowledge gaps.

An earlier version of this file claimed "the engine does find the `handoffs`
mechanism". That was true of an earlier controller and is **false of the code
shipped now**; it was corrected rather than left standing, because a claim like
that is exactly the kind a reader would trust without re-running.

## The scenario is synthetic, and the engine is told nothing

`examples/orders_scenario.json` is generated. Its intended driver is coordination
(`handoffs`); `recorded_wait_h` is truncated on the night shift and produces a
genuine Simpson flip; `supplier_lead_days` is missing for 17% of orders. None of
that is disclosed to QSE.

The correlated decoys were meant to be *misleading*, and measurably they are not:
`system_latency_ms` and `staff_on_shift` are as predictive of the outcome on the
holdout as `handoffs` is, so they are not decoys at all in the statistical sense
(see "The shipped fixture cannot measure the moonshot's own terminal test"). What
that means for this section: the generator's design intent is one claim, and what
the numbers do is another, and only the second one is evidence.

It is still a dataset a human built to be findable. Discovering structure in a
table that was constructed to contain structure is a weaker result than
discovering structure in a real company's records, and the shipped example
should not be cited as if it were the latter.
