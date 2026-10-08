# QSE — Question Singularity Engine

Internal codename **MOONSHOT-Q**. Pure Python, standard library only.
No web UI, no distributed agents, no orchestration framework.

QSE does not optimise for **answer quality**. It optimises for
**question-to-validated-artifact transformation**. That is a different objective:
a question can produce a brilliant-looking answer while producing zero executable
value.

```
QUESTION
   -> QUESTION MODEL          (seven slots)
   -> ASSUMPTIONS
   -> INVERSIONS              (AIL, every inversion needs a testable consequence)
   -> COMPETING HYPOTHESES    (MoIE, structurally different, no majority vote)
   -> KNOWLEDGE GAPS
   -> EXPERIMENTS
   -> BUILD
   -> ADVERSARIAL ATTACK
   -> VERIFICATION            (independent, or it does not count)
   -> EVIDENCE
   -> OUTCOME
   -> QUESTION REVISION  (loop)
```

The core invariant is enforced by the type system and the registries, not by prose:

```
Answer != Hypothesis != Evidence != Artifact != Verified Artifact != Real-world Outcome
```

A hypothesis cannot be stored as evidence. Evidence cannot be stored as an
artifact. An artifact cannot reach `VERIFIED` because it was built, only because
an independent verifier reproduced it after it was attacked.

## Run it

```bash
cd ~/projects/qse
python3 -m qse.cli --help

# the whole loop over the shipped synthetic company, then the acceptance list
python3 -m qse.cli selftest --ledger /tmp/qse.jsonl

# the same, step by step
python3 -m qse.cli run --scenario examples/orders_scenario.json \
    --holdout examples/orders_holdout.json --ledger /tmp/qse.jsonl
python3 -m qse.cli checks   --ledger /tmp/qse.jsonl     # the 17 conditions, exit 0 only if all hold
python3 -m qse.cli closeout --ledger /tmp/qse.jsonl     # the 15 close-out questions, exit 0 only on SUCCESS
python3 -m qse.cli fixture  --scenario examples/orders_scenario.json \
    --holdout examples/orders_holdout.json --driver handoffs   # can this fixture measure anything?
python3 -m qse.cli compare  --scenario examples/orders_scenario.json \
    --holdout examples/orders_holdout.json --driver handoffs   # score naive vs engineered, same metric
python3 -m qse.cli metrics  --ledger /tmp/qse.jsonl     # QBY, BSR, EC, BC, VI, OC
python3 -m qse.cli replay   --ledger /tmp/qse.jsonl     # rebuild the run from the ledger alone
python3 -m qse.cli why <qid> --ledger /tmp/qse.jsonl    # reconstruct why that question was asked
python3 -m qse.cli rules                                # every refusal and what it protects

# one question, on its own
python3 -m qse.cli ask    "Can we predict operational bottlenecks before they become expensive failures?"
python3 -m qse.cli invert "Can we predict operational bottlenecks before they become expensive failures?"
```

Exit codes are the verdict: `0` it did what it says and every check it ran holds,
`1` a defect, a refusal, or an unmet condition, `2` input QSE cannot use at all.

## The control arm, and the fixture that now carries one

The moonshot's terminal test is a comparison -- *does engineered questioning
create measurable capability that would not otherwise exist* -- so it needs a
counterfactual. The cheapest honest one is a competent analyst given the same
table and **no** question engineering: rank every candidate column by its
correlation with the outcome and take the top one.

`fair comparison` requires that doing so is *punished*. `qse.cli fixture` asks
whether the columns which outrank the real driver on the fitting sample keep that
strength on data the fit never saw. The shipped holdout is now generated
(`scripts/generate_holdout.py`) as a period in which the fitting-sample confounds
are absent, so they do not:

```text
    column                  fit r  holdout r
    staff_on_shift         -0.810     +0.047     <- the naive arm picks this
    system_latency_ms      +0.808     +0.098
    precursor_h            +0.798     +0.351
    handoffs               +0.798     +0.839     <- the planted driver

  SEPARABLE: True
```

So the naive arm still reaches for `staff_on_shift` on the fitting sample, but the
column **collapses** out of sample while the mechanism holds. The fixture can now
tell "found the mechanism" from "found a strong correlate", which is the necessary
condition for the comparison to be runnable at all.

The command exits `0` when the fixture *can* carry the comparison and `1` when it
cannot -- and on the shipped scenario it now exits `0`. Two honest caveats, because
a runnable comparison is not a won one:

- **The comparison has not been scored.** A separable fixture means the naive arm
  *can* be punished; it does not make the engineered arm win. Running the two arms
  against each other is the next step, not this one.
- **The engine still does not land on the mechanism.** On this data its selected
  explanation is a measurement objection ("the data is insufficient to support ...")
  and the artifact is a conservative default; `handoffs` appears only as a
  *candidate column* in experiment designs, never as the selected mechanism. So the
  fixture now distinguishes mechanism from correlate, and the engineered arm still
  does not produce the mechanism. Whether it would beat the naive arm is therefore
  still open -- and answering it honestly is what the control arm is for.

The fitting sample (`orders_scenario.json`) is left untouched: it is the historical
period an analyst actually fits on, confounds and all. Only the holdout is
constructed, and only to remove the period-specific confounds. That is not rigging
the comparison's outcome -- it is shaping the fixture into the form the test
requires, the same way a controlled experiment chooses a clean control period.

### The comparison, actually run

`qse.cli compare` scores both arms by the **same** statistic on the holdout --
Youden's J of the rule's flagged set against the outcome -- so neither arm gets a
friendlier metric. The naive arm takes the top fit correlate and fits its best
single threshold; the engineered arm is the rule QSE built and verified:

```text
    arm          rule                       fit J  holdout J  flagged
    naive        staff_on_shift <= 6.0       +0.826     -0.028      132
    engineered   (no detector)                 n/a        n/a        -

  engineered arm wins: False
```

Two honest readings, both unflattering and both the point:

- The **naive arm collapses** exactly as the fallible-analyst story predicts
  (`+0.826` in-sample, negative out of sample). The fixture punishes it.
- The **engineered arm emits no detector at all**: with nothing measured, the
  builder refuses to invent a field and produces an explicit *detector-less*
  artifact (`validated: False`, flags nothing). `compare` cannot score it and does
  not credit it, so the moonshot's terminal claim still does **not** hold.
  `compare` exits `1` -- the honest verdict, not a bug.

Running the comparison exposed a real defect and compiled it into reusable
controls: the generator's fallback first selected the *outcome* as the rule's field
(`failed >= 24`), then an arbitrary input. A rule can no longer sit on the outcome,
and with nothing measured the engine emits an explicit "no usable detector"
artifact rather than an arbitrary one. The failure, the inversion and the controls
are recorded in [docs/D1-failure-to-leverage.md](docs/D1-failure-to-leverage.md).

## The close-out

`closeout` answers fifteen terminal questions -- referential validity, proposition
validity, assumptions, inversion, disagreement, evidence sufficiency, experiment
selection, build conversion, adversarial verification, independence,
reproducibility, mutation, outcome, self-critique, and the strongest claim the
evidence permits -- **from the ledger alone**, and prints which record each answer
was read from.

Every answer carries one label, and the labels are never averaged:

```text
PROVEN     a record exists that could only exist if the thing happened
SUPPORTED  evidence reaches the bar
PLAUSIBLE  a story consistent with the records
UNKNOWN    not established -- which is not the same as "no"
REFUTED    contradicted by a record
UNTESTED   nothing has been run that could settle it
```

The run ends in exactly one terminal condition -- `SUCCESS`, `FALSIFICATION`,
`BLOCKED`, `UNRESOLVED` or `QUESTION_REPLACED` -- and when more than one holds,
**all of them are printed** alongside the precedence actually used, so no state is
silently converted into another. Exit is `0` only on `SUCCESS`.

It is deliberately hard to satisfy. `Q10` answers `UNKNOWN` on every run in this
repository, because the only evidence for independence is that the verifier's
*name* differs from the builder's, and a name is not an independent path. That
single refusal is what keeps `SUCCESS` unreachable here.

## Tests

```bash
cd ~/projects/qse
python3 -B -W error::ResourceWarning -m unittest discover -s qse/tests -t .
```

292 tests. `-t .` matters (it puts the repository root on `sys.path` so `import qse`
resolves) and so does `-B` (bytecode caches left in the tree are noise).

## The seven slots

Every question is decomposed into seven slots. A slot is `STATED` (the asker
supplied it), `INFERRED` (a rule derived it from the raw text, with the rule
recorded) or `UNRESOLVED` (nobody has answered it, and that is logged as an
ambiguity rather than silently guessed).

1. **Referential** — what exactly is referred to
2. **Proposition** — what is actually claimed
3. **Scope** — over what the claim ranges
4. **Authority** — who may define and validate it
5. **Obligation** — what must be proven, what must never be claimed
6. **Temporal validity** — was the definition valid when the event occurred
7. **Consumption** — who consumes the result, and what happens if it is wrong

## What it refuses

The refusals are the apparatus. Each one is a rule in `qse/control/policy.py`,
each one raises, and each one is covered by a test:

| Refusal | Rule |
|---|---|
| an inversion with no testable consequence | `R-INV-1` |
| an experiment that cannot be refuted | `R-EXP-1` |
| evidence with no provenance | `R-EVD-1` |
| a model proposal consumed as evidence | `R-EVD-2` |
| the builder verifying its own artifact | `R-VER-1` |
| an artifact verified before it was attacked | `R-VER-2` |
| an artifact verified with no reproduction that ran and matched | `R-VER-3` |
| two hypotheses that are the same explanation | `R-HYP-1` |
| a decision by majority vote over hypotheses | `R-SYN-1` |
| a question consumed while its scope is unresolved | `R-QUE-1` |

## Layout

```
qse/core/           the seven types and the invariant between them
qse/question_engine/ decomposition, ambiguity detection, revision
qse/inversion/      AIL axioms and operators, MoIE expert interface
qse/reasoning/      hypotheses, disagreement, evidence-weighted synthesis
qse/experiment/     falsification, planning, deterministic runners
qse/build/           specification, generation, execution, artifact graph
qse/verification/   provenance, sufficiency, reproducibility, adversarial attack, the gate
qse/control/        replayable state, policy, information gain, the controller
qse/ledger/         hash-chained JSONL events, receipts, the "why" reconstruction
qse/metrics/        QBY, BSR, EC, BC, VI, OC
qse/cli.py          the command line
qse/tests/          the adversarial suite
```

## Honest limits

Read `docs/LIMITS.md`. In short: the runners are small deterministic procedures
over a declared dataset, not a statistics engine; information gain is ordinal,
not a calibrated probability; the hash chain cannot vouch for the last line, so
the tail is published instead; and `VI` counts independence by declared verifier
identity, which is exactly as strong as the identity is.
