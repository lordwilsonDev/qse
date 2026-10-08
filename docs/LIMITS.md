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

## Verifier independence is by name, and now also by attested identity

`R-VER-1` refuses when the verifier's name equals the builder's name (case-folded and
stripped). Two different strings can still be one person, one model in two sessions,
or a client and its own alias, so QSE now also accepts **attested identities**: pass
`--builder-identity` and `--verifier-identity` (a session id, a runner identity) and a
shared identity is refused even when the names differ, while differing identities
establish independence by *identity* rather than by name.

The limit that remains: the attestation is caller-supplied. QSE records it and reads
`independence_basis == "names and identities differ"` into the close-out, so `Q10`
becomes `SUPPORTED` -- but QSE does not itself prove the two ran as separate
processes or institutions. Where no identity is attested, `Q10` still answers
`UNKNOWN`, because a name is not a path. And `SUCCESS` stays unreachable for a
second, unrelated reason: no real-world outcome with a measured delta exists.

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

## A ledger holds a history, not a run -- so an id repeated across runs is merged

The ledger is append-only and the CLI takes a caller-supplied path, so one file can
hold several runs (`selftest` appends to whatever it is given; `CLAIMS.md` C-002 and
C-004 share `/tmp/qse-claims.jsonl`). `State`'s dict buckets are **indexes**, so an
id two runs emit again -- deterministic ids recur exactly -- lands as one entry.
`records` keeps every event; the buckets collapse repeats.

`A16` therefore checks **containment** (every id an event names is present in the
state, plus no unknown event types and no rebuild errors), not equality of counts.
An equality would fail on any healthy ledger holding more than one run, which is
exactly the false alarm that `verify-claims --run` surfaced on C-002
(`qse-d1-0002` in [D1-failure-to-leverage.md](D1-failure-to-leverage.md)).

The limit that remains: a ledger carries no run/session id, so an id repeated
**within a single run** (a genuine id-collision bug) is indistinguishable from the
same id emitted by a second run. Telling them apart needs a run id, which is the
next question recorded in the D1 entry, not a control shipped here.

## The fixture carries the moonshot's terminal test, and the comparison is scored

The terminal test -- *does engineered questioning create measurable capability
that would not otherwise exist* -- is a comparison, so it needs a counterfactual.
`qse.cli fixture` supplies the cheapest one (an analyst with no question
engineering takes the top correlate) and asks whether this fixture can punish it.

It can. The holdout is generated (`scripts/generate_holdout.py`) as a period in
which the fitting-sample confounds are absent, so every column that outranks the
driver on the fit collapses on data the fit never saw:

```text
staff_on_shift    fit -0.810   holdout +0.047   <- the naive arm picks this
system_latency_ms fit +0.808   holdout +0.098
precursor_h       fit +0.798   holdout +0.351
handoffs          fit +0.798   holdout +0.839   <- the planted driver
```

`SEPARABLE: True`, exit 0. A separable fixture means the naive arm *can* be
punished; it does not by itself mean the engineered arm wins.

The comparison has been **run** (`qse.cli compare`), scoring both arms by the same
statistic -- Youden's J of the rule's flagged set against the outcome, at each
rule's own threshold -- on the holdout:

```text
arm          rule                       fit J  holdout J  flagged
naive        staff_on_shift <= 6.0       +0.826     -0.028      132
engineered   handoffs >= 6.0             +0.872     +0.916      163
```

The naive arm collapses (`+0.826` in-sample, negative out of sample), which is the
fixture working as intended. The engineered arm names a measured field and beats it
by far more than the `0.10` margin, so **the moonshot's terminal claim holds on this
fixture** and `compare` exits `0`. Read the next section before repeating that.

## The win is not a single-table win, and `compare` says so itself

`compare` prints a **field provenance** block, read from the run's own ledger. On
the shipped pair it says:

```text
decided by holdout: handoffs (separation 0.9157, margin 0.6041 over precursor_h)
did NOT decide over orders-fortune500-synthetic: could not separate the best
    candidate 'handoffs' (separation 0.8719) from precursor_h, message_volume,
    queue_wait_h
```

The second line is the whole qualification. The field was named by the scan over the
**second** source; on the fitting sample the same scan **cannot decide** -- `handoffs`
(`0.8719`) is tied with `precursor_h` (`0.8719`) and `message_volume` (`0.8393`) is
inside the `0.10` floor. The fitting period is deliberately built so that a correlate
cannot be told from the mechanism on it.

So the engineered arm used a second period the naive arm was not given. That is the
asymmetry, and it is the finding rather than a footnote: the engineered arm's
advantage is that it ran the discriminating experiment on an independent source
*before* naming a mechanism, which is what the scenario's own `obligation` demanded
("must prove the precursor generalises across shifts and regions"). It is a claim
about question engineering, not about one table answering one question better, and
it does not hold as a same-data comparison.

The cut was measured on the source that decided. The fitting sample's own best cut
for the same column is also `6.0`, so nothing about the *threshold* differs between
the two periods -- but it is not validated on both, and this file will not say it is.

## The same comparison on a second question, in a second domain

MOONSHOT-C (`moonshot_cloud.py`) points the engine at a cloud bill finance cannot
explain and runs the same terminal comparison. The fixture is
`qse/cloud/scenario.py` (written to `examples/cloud_fit.json` and
`examples/cloud_holdout.json`). The real driver is provisioned-but-unused capacity
(`idle_hours`); the fitting-period confound is `vcpus`, which only holds there
because the idleness metric was estimated by a sampling agent and `vcpus` was taken
from a review list that tracked true idleness. `billed_usd` is declared derived from
the outcome (`over_budget` is computed from it) and excluded, or the bill would
explain the overspend perfectly and nothing else could compete.

One command, `python3 moonshot_cloud.py`, gates on separability, builds the
engineered arm on both periods, and scores both arms:

```text
    arm          rule                       fit J  holdout J  flagged
    naive        vcpus >= 16.0               +0.885     -0.003      165
    engineered   idle_hours >= 13.0          +0.603     +0.969      178

  named by cloud-holdout: idle_hours (separation 0.9687, margin 0.5924 over retries_millions)
  cloud-fit decided on 'vcpus' instead (separation 0.885) -- rejected, it does not replicate
```

The naive arm collapses out of sample; the engineered arm names a field and beats it,
and `moonshot_cloud.py` exits `0` with the 17-item acceptance list at `17/17`. But the
same qualification as the orders pair applies, in a sharper form: **the field was named
by the second period, not the fitting one.** The fitting period's scan decides on
`vcpus` (`0.885`) and that decision is *rejected*, because `vcpus` does not replicate on
the holdout. That rejection is the finding the cloud domain was built to produce, and
it is a real limit: on the fitting period alone the engine would have shipped `vcpus`.

Two further honest limits the cloud run exposes:

- **A declared probe can fail to fire.** The planner routes some hypotheses to
  `counterfactual_replay` and binds `threshold=24` before seeing any data. `idle_hours`
  never reaches 24 on the holdout, so two planned probes record `EXPERIMENT_NOT_RUN`
  and produce no evidence. This is a fact about the plan, not the data; Q14 flags it.
- **The cross-source requirement can reject the truth.** A field that genuinely holds
  on only one period is rejected, because there is no other period to confirm it. The
  control prefers a field two sources agree on, which is the right default and is not
  the same as always finding the right field.

The cloud fixture is synthetic, generated to be findable, and its parameters are
recorded in `qse/cloud/scenario.py` as a tuning log. It is not a real company's
records, and the reading is the same as for the orders fixture: finding structure in a
table built to contain structure is weaker than finding it in the wild.

## Two residual limits of the scan and the artifact, both visible in the output

- **The scan measures one direction.** `_youden` scans `value >= threshold` only, so
  a column that is *protective* (low values flag) is measured at its least favourable
  direction and its separation in the ranking is a floor rather than its best.
  `baseline.best_threshold_rule` scans both directions, so the two arms do not measure
  direction the same way.
- **The artifact's title can disagree with its rule.** Here the artifact is titled for
  the winning hypothesis -- a `MEASUREMENT`/`TELEMETRY` one whose text is "the data is
  insufficient to support ..." -- while its rule sits on `handoffs`, a field that
  hypothesis does not mention. The rule's `basis` records where the field came from, so
  the disagreement is readable inside the artifact (the generated module carries
  `Rule:`, `Basis:` and `Detector:` lines), but nothing forces the title, the acceptance
  criteria and the detector to be about the same explanation. That is the open question
  recorded in `qse-d1-0003`.

## Corrections kept in place

The first version of `compare` reported the engineered rule as *circular* (its field
was `failed`, the outcome); the next chose an arbitrary input; then the engine emitted
a deliberate **detector-less** artifact and `compare` could not score it at all. All
three are fixed: the outcome is excluded from a rule's field and from the artifact's
inputs, nothing arbitrary is named, and the scan's measured cut now reaches the
builder, so a scan that decides names a field (`qse-d1-0003` in
[D1-failure-to-leverage.md](D1-failure-to-leverage.md)).

An earlier version of this file recorded the shipped pair as `SEPARABLE: False`,
because the decoys held out of sample as strongly as the driver and `precursor_h` was
a *deterministic* function of `handoffs` (r = 1.000) and so tied it forever. That was
corrected by generating a holdout that removes the period-specific confounds, not by
changing the audit.

Earlier versions of this file also asserted, in both directions, whether "the engine
finds the `handoffs` mechanism". It did not, and then it did; both statements were
true of the code they described and are kept here rather than deleted, because the
sequence is the evidence that the controls work. What is true of the shipped code
now is the scored comparison above, with its provenance.

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
