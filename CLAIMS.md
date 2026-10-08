# Claims

Every claim QSE makes about itself has a row here. **Status** is one of `verified`
(checked, and the check passed), `pending` (not yet checked -- never restate as
fact), or `retracted` (checked and found wrong -- kept, not deleted). **Expected**
is the exit code the check must return; a `-` means the check is a judgement, not a
command, and is not executed.

Check the structure (and the evidence paths) with `python3 -m qse.cli verify-claims`;
add `--run` to execute the runnable checks and compare exit codes. Cells never
contain the `|` character.

Discipline borrowed from the BlackSwanLabz Research Lab `CLAIMS.md`: a claim is not
a result until it is staged and mechanically checkable.

| ID | Claim | Evidence | How to check | Expected | Status | Checked |
|---|---|---|---|---|---|---|
| C-001 | The shipped fixture can carry the control-arm comparison (the decoys that outrank the driver on the fit collapse out of sample) | `examples/orders_scenario.json` `examples/orders_holdout.json` | python3 -m qse.cli fixture --scenario examples/orders_scenario.json --holdout examples/orders_holdout.json --driver handoffs | 0 | verified | 2026-10-08 |
| C-002 | The moonshot's 17-item acceptance list holds on the shipped run | - | python3 -m qse.cli selftest --ledger /tmp/qse-claims.jsonl | 0 | verified | 2026-10-08 |
| C-003 | RETRACTED 2026-10-08: the control-arm comparison does NOT credit the engineered arm because it emits no detector. FALSE from the scan-reports-its-cut change: a discrimination scan that decides now names the field, so the engineered arm is scored and credited. Kept rather than deleted, and the check is withdrawn with it -- C-010 stages what is true now | - | withdrawn with the claim; the command it used to run is the one C-010 runs | - | retracted | 2026-10-08 |
| C-004 | The close-out ends UNRESOLVED on the shipped run (verification independence is not established) | - | python3 -m qse.cli closeout --ledger /tmp/qse-claims.jsonl | 1 | verified | 2026-10-08 |
| C-005 | A decision rule may never sit on the outcome it predicts; with nothing measured the artifact is detector-less | `qse/build/generator.py` | python3 -m unittest qse.tests.test_experiment_build | 0 | verified | 2026-10-08 |
| C-006 | Verifier independence is NOT established on the default run: Q10 answers UNKNOWN because a name is not a path | `qse/closeout.py` | read q10_independence in qse/closeout.py and confirm it returns UNKNOWN when only the names differ | - | verified | 2026-10-08 |
| C-007 | The whole test suite passes | - | python3 -m unittest discover -s qse/tests -t . | 0 | verified | 2026-10-08 |
| C-008 | Verifier independence can be established by attested identity, and a shared identity is refused even when the names differ | `qse/verification/verifier.py` | python3 -m unittest qse.tests.test_verification | 0 | verified | 2026-10-08 |
| C-009 | Replay is checked by containment, not by counting ids: a ledger holding the same run twice still passes A16 (the defect C-002 surfaced) | `qse/control/state.py` | python3 -m unittest qse.tests.test_acceptance | 0 | verified | 2026-10-08 |
| C-010 | The engineered arm now names a field and beats the naive arm on the shipped fixture by more than the margin -- and the field was named by the scan over the holdout, NOT the fitting sample, where the scan cannot separate it | `qse/cli.py` | python3 -m unittest qse.tests.test_baseline.TheArmComparison | 0 | verified | 2026-10-08 |
| C-011 | The discrimination scan reports the cut behind every candidate's separation, so a ranking can become a rule; and a scan that decides names the rule, while one that cannot names the contenders it refused to separate | `qse/experiment/runner.py` | python3 -m unittest qse.tests.test_experiment_build.TheScanReportsItsMeasurement | 0 | verified | 2026-10-08 |
| C-012 | A scan that could not decide leaves the artifact detector-less and its basis names the best candidate and the contender it could not separate it from | `qse/build/generator.py` | python3 -m unittest qse.tests.test_experiment_build.SpecificationAndGeneration | 0 | verified | 2026-10-08 |
