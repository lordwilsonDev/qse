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
python3 -m qse.cli verify-claims --run                         # check the staged claims against reality
python3 -m qse.cli metrics  --ledger /tmp/qse.jsonl     # QBY, BSR, EC, BC, VI, OC
python3 -m qse.cli replay   --ledger /tmp/qse.jsonl     # rebuild the run from the ledger alone
python3 -m qse.cli why <qid> --ledger /tmp/qse.jsonl    # reconstruct why that question was asked
python3 -m qse.cli rules                                # every refusal and what it protects

# one question, on its own
python3 -m qse.cli ask    "Can we predict operational bottlenecks before they become expensive failures?"
python3 -m qse.cli invert "Can we predict operational bottlenecks before they become expensive failures?"

# MOONSHOT-C: the same comparison on a second question, in a second domain
python3 moonshot_cloud.py                 # gate, build, score, check -- one command, one page
python3 moonshot_cloud.py --write examples  # write the synthetic cloud fixture and stop

# MOONSHOT-M: invert the axioms of an always-on Mac mini and build the witness
python3 moonshot_machine.py               # reverse-engineer the machine, invert, run the witness
```

Exit codes are the verdict: `0` it did what it says and every check it ran holds,
`1` a defect, a refusal, or an unmet condition, `2` input QSE cannot use at all.

## MOONSHOT-M — the machine that can attest its own continuity

Everyone's always-on Mac mini runs *something*: local models, agents, media. The settled
belief is **"the mini is worth running because it computes."** AIL inverts the belief, not
the sentence. Its TEMPORAL, AUTHORITY, FAILURE and MEASUREMENT axioms -- that an always-on
node is one continuous process whose log is its history; that its own log is evidence of
what it did; that the failures that matter are the ones it observed; that its health is in
its own reports -- invert to a single capability no one builds:

> the machine's value is not the work it does; it is the **continuity it can prove**,
> which no machine can honestly prove about itself.

`moonshot_machine.py` derives that with the AIL operators (7 axioms → 63 gated inversions,
7 refused), then **runs** it: `qse/witness/` keeps a hash-chained heartbeat whose every gap
is a claim to be settled by an *independent* witness, never by the machine.

```text
real ledger: 4 beats, verdict CONTINUOUS, chain_ok True
tampered line rewritten -> verdict TAMPERED
injected history, a machine that slept    -> SLEPT          (the OS power log explains it)
injected history, a machine that rebooted -> REBOOT         (the boot time changed)
injected history, a recorder that died    -> HEARTBEAT_LOST (nothing explains it)
subject (a real process we started, then ended)
  recorder verdict SUBJECT_BROKE -- the ledger never missed a beat
```

It beats **for a subject**, recording the subject's identity at every beat, so "the ledger
never stopped" and "the job never stopped" are told apart -- the recorder can stay
continuous while the watched thing dies and returns (`SUBJECT_RESTARTED` / `SUBJECT_MISSING`
→ verdict `SUBJECT_BROKE`). The subject is witnessed **twice**: the machine observes a
process identity, and the subject may declare a token (a run id). Neither is trusted over
the other, so their disagreement is the finding -- `SUBJECT_VOUCH_CONFLICT` (a new process
vouching the same run id) versus `SUBJECT_TOKEN_DRIFT` (same process, a new run id). It
also keeps **absence as evidence**: a watched metric that never moved is reported with the
same standing a change would get, because "the disk did not fill" is exactly what a log of
changes can never show. And a disagreement between the two witnesses is settled by a
**policy declared before the run** (`report` / `probe` / `token` / `both`), recorded and
applied, so the verdict follows a stated rule that a reader can restate -- nothing is
settled silently. It also separates **liveness from progress**: each beat may carry an
advancing signal, so a subject that stays alive and advances nothing over a declared
threshold is reported `SUBJECT_STALLED` -- the failure no gap or identity check can see --
while a counter that goes backwards is `SUBJECT_BROKE`. And the counter is checked against
the world, not only reported: a side effect the recorder reads for itself (a file the
subject grows) is compared with the declared progress, so a claimed advance nothing
substantiates is `SUBJECT_UNSUBSTANTIATED`, an unclaimed advance is benign (and must not be
misread as a stall), and the same two-witness pattern applied to identity is applied to
advance. Independence itself is **counted, not asserted**: the record reads named sources
and reports how many agree -- two or more advancing is corroborated, one alone is
`SUBJECT_UNCORROBORATED`, sources that contradict each other are `SUBJECT_WITNESSES_SPLIT`
-- so it never says "independent", only how many witnesses back the claim. And agreement
is not independence: each source may **declare why it is beyond the subject's reach**
(`read_only` / `causal` / `external` / `within`), and the record counts the agreeing
sources declared beyond reach -- two or more is independent, two-or-more agreeing with
fewer than two beyond reach is `SUBJECT_INDEPENDENCE_UNPROVEN`, so the strongest verdict a
*declaration* can reach is "unproven", never a silent pass. And a declaration can be
**checked, not just recorded**: name each source's path and the recorder stats it itself,
so two sources it cannot write are `INDEPENDENCE_ATTESTED` (independence observed) and a
writable source marked `read_only` is `SUBJECT_INDEPENDENCE_CONTRADICTED` -- the check
outranks the word. And the *value* can be **measured, not just reported**: name a source's
path and the recorder reads the bytes itself (a checksum over what it read), so the number
the advance rests on is a function of the file, a reported number the bytes refute is
`SUBJECT_VALUES_CONTRADICTED`, two sources it both checks read-only and measures are
`INDEPENDENCE_MEASURED`, and an advance resting only on numbers the caller typed is
`SUBJECT_VALUES_REPORTED`. The full inversions and the honest limits are in
[docs/moonshot-m.md](docs/moonshot-m.md).

## MOONSHOT-C — the same test on a cloud bill, in one script

`moonshot_cloud.py` reruns the terminal comparison on an unrelated question -- a
cloud bill finance cannot explain -- end to end in one command. It gates on
separability, builds the engineered arm on two periods, scores both arms by the same
statistic, and evaluates the 17-item acceptance list against the run's own ledger.
Its exit code is the answer: `0` when the data can carry the comparison, the
engineered arm is validated and wins, and every check holds; `1` when it does not;
`2` for input it cannot use at all.

```text
    arm          rule                       fit J  holdout J  flagged
    naive        vcpus >= 16.0               +0.885     -0.003      165
    engineered   idle_hours >= 13.0          +0.603     +0.969      178

  named by cloud-holdout: idle_hours (separation 0.9687, margin 0.5924 over retries_millions)
  cloud-fit decided on 'vcpus' instead (separation 0.885) -- rejected: it does not replicate
```

Pointing the engine at a second domain surfaced the failures in
[docs/D1-failure-to-leverage.md](docs/D1-failure-to-leverage.md) entry `qse-d1-0004`:
the planner guessed *orders* column names, so on cloud data every experiment came back
`ran: false` and the engine reported "no explanation found" without saying it had never
looked. Columns are now **declared** (`--role ROLE=COLUMN`), a column derived from the
outcome is **excluded** (`--exclude`), a field one period's scan named is not shipped
until the other period also supports it, a planned data-blind threshold travels as a
**probe**, and a run that *scanned* for missing evidence no longer fails the check that
asks whether it looked.

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
cannot -- and on the shipped scenario it exits `0`. A runnable comparison is not a
won one, which is why the comparison itself is run in the next subsection.

The fitting sample (`orders_scenario.json`) is left untouched: it is the historical
period an analyst actually fits on, confounds and all. Only the holdout is
constructed, and only to remove the period-specific confounds. That is not rigging
the comparison's outcome -- it is shaping the fixture into the form the test
requires, the same way a controlled experiment chooses a clean control period.

### The comparison, actually run

`qse.cli compare` scores both arms by the **same** statistic on the holdout --
Youden's J of the rule's flagged set against the outcome, at each rule's own
threshold -- so neither arm gets a friendlier metric. The naive arm takes the top fit
correlate and fits its best single threshold; the engineered arm is the rule QSE
built and verified:

```text
    arm          rule                       fit J  holdout J  flagged
    naive        staff_on_shift <= 6.0       +0.826     -0.028      132
    engineered   handoffs >= 6.0             +0.872     +0.916      163

  engineered arm wins: True
```

Two honest readings:

- The **naive arm collapses** exactly as the fallible-analyst story predicts
  (`+0.826` in-sample, negative out of sample). The fixture punishes it.
- The **engineered arm names a measured field and beats it** by far more than the
  margin, so the moonshot's terminal claim holds on this fixture and `compare` exits
  `0`. But read the provenance `compare` prints alongside the verdict, because the
  win is **not** a single-table win: the field was named by the scan over the
  **holdout**, and on the fitting sample the same scan *cannot decide* (`handoffs`
  `0.8719` tied with `precursor_h` `0.8719`, with `message_volume` at `0.8393` inside
  the `0.10` floor). The engineered arm's advantage is that it ran the discriminating
  experiment on an independent period *before* naming a mechanism -- which is what
  the question's own `obligation` demanded -- and the naive arm was handed one
  period. That asymmetry is the finding, and [docs/LIMITS.md](docs/LIMITS.md) states
  it in full.

Running the comparison exposed three real defects and compiled each into reusable
controls: the generator's fallback first selected the *outcome* as the rule's field
(`failed >= 24`), then an arbitrary input; and the discrimination scan computed the
cut behind every candidate's separation and threw it away, so the engine could rank
explanations and could never turn a ranking into a rule. A rule can no longer sit on
the outcome; nothing arbitrary is named; and a scan that decides now reports the field
*and the cut*, while a scan that cannot decide names the contenders it refused to
separate. The failures, the inversions and the controls are recorded in
[docs/D1-failure-to-leverage.md](docs/D1-failure-to-leverage.md).

## Claims

QSE makes claims about itself, and `CLAIMS.md` stages each one with its evidence, how
to check it, and the exit code that check must return. `qse.cli verify-claims --run`
executes the runnable checks and fails if any claim has drifted from reality.
**Status** is `verified`, `pending` (not yet checked -- never restate as fact) or
`retracted` (checked and found wrong -- kept, not deleted), following the
BlackSwanLabz Research Lab's CLAIMS discipline. A claim nobody can fail is decoration.

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

It is deliberately hard to satisfy. On the default run `Q10` answers `UNKNOWN`,
because the only evidence for independence is that the verifier's *name* differs from
the builder's, and a name is not an independent path. Pass `--builder-identity` and
`--verifier-identity` (a session id, a runner identity) and independence is
established by identity -- `Q10` becomes `SUPPORTED`, and a *shared* identity is
refused even when the names differ. `SUCCESS` still stays unreachable for a second,
unrelated reason: no real-world outcome with a measured delta exists here.

## Tests

```bash
cd ~/projects/qse
python3 -B -W error::ResourceWarning -m unittest discover -s qse/tests -t .
```

431 tests. `-t .` matters (it puts the repository root on `sys.path` so `import qse`
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
qse/cloud/          the MOONSHOT-C synthetic cloud fixture (scenario.py)
qse/witness/        MOONSHOT-M: the continuity ledger, OS power-log witness, progress, side-effect, corroboration + independence + value-measurement checks
qse/cli.py          the command line
moonshot_cloud.py   MOONSHOT-C: the same terminal comparison, on a cloud bill, in one command
moonshot_machine.py MOONSHOT-M: invert a machine's axioms and build the witness, in one command
qse/tests/          the adversarial suite
```

## Honest limits

Read `docs/LIMITS.md`. In short: the runners are small deterministic procedures
over a declared dataset, not a statistics engine; information gain is ordinal,
not a calibrated probability; the hash chain cannot vouch for the last line, so
the tail is published instead; and `VI` counts independence by declared verifier
identity, which is exactly as strong as the identity is.
