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

## The control arm, and the fixture that cannot carry one

The moonshot's terminal test is a comparison -- *does engineered questioning
create measurable capability that would not otherwise exist* -- so it needs a
counterfactual. The cheapest honest one is a competent analyst given the same
table and **no** question engineering: rank every candidate column by its
correlation with the outcome and take the top one.

`fair comparison` requires that doing so is *punished*. `qse.cli fixture` asks
whether the columns which outrank the real driver on the fitting sample keep that
strength on data the fit never saw. On the shipped scenario they do:

```text
    column                  fit r  holdout r
    staff_on_shift         -0.810     -0.791     <- the naive arm picks this
    system_latency_ms      +0.808     +0.809
    handoffs               +0.798     +0.784     <- the planted driver

  SEPARABLE: False
```

So the naive arm would pick `staff_on_shift`, and it would be **right enough to
count**: the column stays as predictive out of sample as the mechanism does.
Nothing in this fixture distinguishes "found the mechanism" from "found a strong
correlate", which means a win for the engineered arm here would be unfounded.

The command exits `0` when the fixture *can* carry the comparison and `1` when it
cannot -- and on the shipped scenario it exits `1`. That is the honest state of
this moonshot's terminal test: **not failed, not passed, unmeasurable on this
fixture.** Making the fixture adversarial (the misleading correlates have to be
*spurious* -- strong in-sample, collapsed out) is the prerequisite for ever
answering the moonshot's own question.

One more thing the same ledger shows, and it is not flattering: on this fixture
the engine **does not land on the mechanism either.** Its discriminating
experiment returns `INCONCLUSIVE (supported=None, refuted=False)` on both
samples; the explanation it selects is a measurement objection ("the data is
insufficient to support ..."); and the artifact is a conservative default,
`failed >= 24.0 -> escalate`, whose own basis is that no usable measured evidence
reached the bar. So on this data neither arm identifies `handoffs`, and the
honest summary is that the fixture leaves both arms without a mechanism rather
than showing that one arm found it.

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
