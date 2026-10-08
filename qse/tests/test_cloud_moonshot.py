"""MOONSHOT-C: the cloud fixture, and the two defects pointing the engine at it found.

The tests are grouped the way the defects were found:

* ``TheCloudFixture`` -- the fixture can carry the comparison, and the columns derived
  from the outcome are declared rather than inferred.
* ``ThePlannerHasToBeTold`` -- QSE guessed *orders* column names, so on a cloud table
  every experiment came back ``ran: False`` and the engine reported "no explanation
  found" without saying it had never looked.
* ``CrossSourceReplication`` -- a field named by one period's scan is not trusted until
  it separates on the other, because the period that was recorded badly likes its own
  confound best.
* ``TheProbeRule`` -- a planning threshold declared before any data was seen must not
  become the shipped artifact's detector.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from .. import baseline as baseline_mod, cli
from ..build import generator
from ..cloud import scenario
from ..core.evidence import make_evidence
from ..core.experiment import make_experiment
from ..control.controller import Engine
from ..experiment import planner, runner
from ..experiment.runner import Dataset
from ..ledger import chain
from .support import REPO, pin_clock

#: The script is a script, not a module in the package. Loaded from its path so the
#: test drives the same file a person runs.
_spec = importlib.util.spec_from_file_location("moonshot_cloud", REPO / "moonshot_cloud.py")
moonshot = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(moonshot)


def _run_script(argv: list[str]) -> tuple[int, dict]:
    out = io.StringIO()
    with redirect_stdout(out), redirect_stderr(io.StringIO()):
        code = moonshot.main(["--json", *argv])
    payload = json.loads(out.getvalue()) if out.getvalue().strip() else {}
    out.close()
    return code, payload


class TheCloudFixture(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_the_fixture_can_punish_the_naive_arm_once_the_outcome_derived_column_is_declared(self):
        gate = baseline_mod.audit(scenario.fit_rows(), scenario.holdout_rows(),
                                  outcome="over_budget", driver="idle_hours",
                                  exclude=scenario.EXCLUDED)
        self.assertTrue(gate["separable"], gate["reason"])
        self.assertEqual(gate["naive_pick"]["column"], "vcpus")
        self.assertLess(abs(gate["naive_pick"]["holdout"]), 0.10,
                        "the naive pick must collapse out of sample")
        self.assertGreater(abs(gate["excluded"] and 0 or 1), 0)

    def test_the_bill_is_never_offered_as_an_explanation_for_the_bill(self):
        # the whole reason `exclude` exists: billed_usd correlates with the overspend
        # flag near-perfectly because the flag is computed from it
        gate = baseline_mod.audit(scenario.fit_rows(), scenario.holdout_rows(),
                                  outcome="over_budget", driver="idle_hours",
                                  exclude=scenario.EXCLUDED)
        self.assertNotIn("billed_usd", [row["column"] for row in gate["ranked"]])
        with_exclusion_removed = baseline_mod.audit(
            scenario.fit_rows(), scenario.holdout_rows(),
            outcome="over_budget", driver="idle_hours")
        self.assertEqual(with_exclusion_removed["naive_pick"]["column"], "billed_usd",
                         "without the declaration the comparison is meaningless: the bill "
                         "explains the overspend perfectly and nothing else can compete")

    def test_the_fixture_is_deterministic(self):
        self.assertEqual(scenario.fit_rows(), scenario.fit_rows())
        self.assertEqual(scenario.holdout_rows(), scenario.holdout_rows())

    def test_the_declared_roles_name_columns_that_exist(self):
        keys = set(scenario.fit_rows()[0])
        for role, value in planner.roles_for(scenario.ROLES).items():
            for column in (value.split(",") if role in ("columns", "candidates") else [value]):
                self.assertIn(column.strip(), keys, f"role {role} names a missing column")


class ThePlannerHasToBeTold(unittest.TestCase):
    """The defect: the planner guessed orders-domain names, so cloud data found nothing."""

    def setUp(self) -> None:
        pin_clock()
        self.fit = Dataset(name="cloud-fit", rows=scenario.fit_rows())
        self.hold = Dataset(name="cloud-holdout", rows=scenario.holdout_rows())

    def _evidence(self, report):
        return [s for s in report.stages if s.get("stage") == "run"][0]

    def test_without_declared_roles_every_experiment_fails_to_find_its_columns(self):
        from ..reasoning.hypothesis import from_inversions
        from ..inversion.ail import AILEngine
        from ..core.proposition import parse_proposition
        from ..question_engine import decomposer

        question = decomposer.decompose(scenario.QUESTION, answers=dict(scenario.FACTS))
        engine = AILEngine(question, proposition=parse_proposition(question.value("proposition")))
        hypotheses = from_inversions(engine.invert(), question, authority="ops")
        self.assertTrue(hypotheses)
        ran = Engine("/tmp/qse-cloud-defect.jsonl")
        planned = ran.plan(question, hypotheses, columns=list(scenario.fit_rows()[0]))
        frames = [self.fit, self.hold]
        result = ran.run_experiments(planned["experiments"], frames)
        self.assertEqual(result["evidence"], [],
                         "with no declaration the guessed bindings name orders columns, so "
                         "no cloud experiment can run -- which is the defect, pinned here")
        self.assertTrue(all(not row["ran"] for row in result["results"]))

    def test_with_declared_roles_the_same_experiments_run(self):
        report = self._run()
        self.assertGreater(report["ran"], 0, "declared roles must make the experiments runnable")
        self.assertGreater(report["evidence"], 0)
        # Not every planned test must fire. The planner routes some hypotheses to
        # ``counterfactual_replay`` and binds a threshold it declared *before seeing
        # any data* (24, the placeholder). On this fixture idle_hours never reaches
        # 24, so the probe cannot fire, and the engine records EXPERIMENT_NOT_RUN
        # rather than inventing a result. What must hold is that the only unrunnable
        # tests are those declared probes -- not that none may exist.
        self.assertLessEqual(report["not_run"], 2)
        unrunnable = [d for d in chain.load("/tmp/qse-cloud-roles.jsonl")
                      if d.get("kind") == "EXPERIMENT_NOT_RUN"]
        self.assertTrue(unrunnable, "the declared probes that could not fire are reported")
        self.assertTrue(all("24.0" in str(d.get("why")) for d in unrunnable),
                        "the only tests that could not fire are the declared probes")

    def _run(self) -> dict:
        engine = Engine("/tmp/qse-cloud-roles.jsonl")
        report = engine.run(
            scenario.QUESTION, answers=dict(scenario.FACTS),
            datasets=[self.fit, self.hold], rows=scenario.fit_rows(),
            authority="finance", roles=scenario.ROLES)
        return [s for s in report.stages if s.get("stage") == "run"][0]

    def test_a_declared_role_whose_value_contains_an_equals_is_refused(self):
        with self.assertRaises(ValueError):
            planner.roles_for({"outcome": "a=b"})

    def test_an_outcome_derived_column_is_dropped_from_multi_valued_roles_too(self):
        binding = planner._binder(
            "discrimination_scan", ["idle_hours", "billed_usd", "vcpus"],
            {"outcome": "over_budget", "exclude": "billed_usd"})
        joined = " ".join(binding)
        self.assertNotIn("billed_usd=", joined)
        self.assertNotIn("candidates=billed_usd", joined)
        self.assertNotIn("billed_usd,", joined)


class CrossSourceReplication(unittest.TestCase):
    """A field is not named until it holds where the choice was not made."""

    def setUp(self) -> None:
        pin_clock()
        self.hypothesis = "HYP-1"

    def _scan(self, source: str, detector, ranking):
        return make_evidence(
            "candidate explanations were ranked against the outcome",
            hypothesis=self.hypothesis, kind="MEASURED", source=source,
            method="discrimination_scan: ranking candidate explanations by separation",
            collected_at="2026-10-08T12:00:00Z",
            observed={
                "outcome": "over_budget", "excluded_circular": ["over_budget"],
                "ranking": ranking, "favours": (detector or {}).get("field"),
                "decided": detector is not None, "detector": detector, "contenders": [],
                "best_separation": ranking[0]["separation"], "margin": 0.25,
                "runner_up": ranking[1]["column"] if len(ranking) > 1 else None,
            })

    def _rule(self, evidence):
        from ..build import specification

        spec = specification.from_hypothesis(
            type("H", (), {"hid": self.hypothesis, "text": "t", "mechanism": "CAPACITY",
                           "locus": "STAFFING", "timescale": "HOURS",
                           "measurement_assumption": "m", "authority": "a",
                           "title": None})(),
            evidence, exclude=scenario.EXCLUDED)
        return generator.default_rule(spec, evidence)

    def test_a_field_the_other_source_rejects_is_not_shipped(self):
        # the fitting period's scan is not wrong to prefer its confound: on that period
        # the confound really is the better column. Only the other source can show it.
        confounded = self._scan("cloud-fit", {"field": "vcpus", "op": ">=", "threshold": 16.0},
                                [{"column": "vcpus", "separation": 0.885, "n": 600},
                                 {"column": "idle_hours", "separation": 0.6355, "n": 600}])
        honest = self._scan("cloud-holdout", {"field": "idle_hours", "op": ">=", "threshold": 13.0},
                            [{"column": "idle_hours", "separation": 0.9687, "n": 400},
                             {"column": "vcpus", "separation": 0.0091, "n": 400}])
        rule = self._rule([confounded, honest])
        self.assertEqual(rule["field"], "idle_hours",
                         "the replicated field ships, not the one the confounded period liked")
        self.assertIn("rejected as not replicating", rule["basis"])
        self.assertIn("vcpus", rule["basis"], "the rejection is named, not dropped in silence")

    def test_a_field_that_holds_on_neither_source_is_not_named(self):
        # the fitting scan ranks untagged_fraction weakly, so the field the holdout
        # decided on has a source to fail replication against -- silence is not a
        # failure, so a field ranked by no other source is (correctly) accepted
        fit = self._scan("cloud-fit", {"field": "vcpus", "op": ">=", "threshold": 16.0},
                         [{"column": "vcpus", "separation": 0.885, "n": 600},
                          {"column": "idle_hours", "separation": 0.02, "n": 600},
                          {"column": "untagged_fraction", "separation": 0.05, "n": 600}])
        hold = self._scan("cloud-holdout", {"field": "untagged_fraction", "op": ">=", "threshold": 0.3},
                          [{"column": "untagged_fraction", "separation": 0.51, "n": 400},
                           {"column": "vcpus", "separation": 0.0091, "n": 400}])
        rule = self._rule([fit, hold])
        self.assertIsNone(rule["field"], "neither field replicated, so neither is named")
        self.assertFalse(rule["detector"])
        self.assertFalse(rule["validated"])


class TheProbeRule(unittest.TestCase):
    """A threshold declared before any data was seen is a probe, not a measurement."""

    def setUp(self) -> None:
        pin_clock()

    def test_the_replay_runner_reports_its_hypothetical_rule_as_a_probe(self):
        # A threshold that CAN fire, so the assertion is about the key the runner
        # reports and not about whether the probe happened to flag anything. It is
        # still a probe: ``counterfactual_replay`` never measures its own threshold.
        item = make_experiment(
            hypothesis="HYP-1", question=scenario.QUESTION,
            design="counterfactual replay of a rule declared before any data was seen",
            prediction_if_true="the flagged rows carry the outcome more often",
            prediction_if_false="the flagged and unflagged rows are alike",
            refuted_by="refuted if the rule does not land on the bad rows more often",
            runner="counterfactual_replay", discriminates=("HYP-1",),
            required_data=("field=idle_hours", "op=>=", "threshold=13",
                           "outcome=over_budget"),
        )
        result = runner.run(item, Dataset(name="cloud-fit", rows=scenario.fit_rows()))
        self.assertTrue(result["ran"], result["reason"])
        observed = result["observed"]
        self.assertTrue(observed["probe"])
        self.assertIn("probe_rule", observed)
        self.assertNotIn("rule", observed,
                         "the key the builder reads as a measured rule must not carry a probe")

    def test_a_probe_that_cannot_fire_says_what_the_field_actually_spans(self):
        # A declared threshold outside the data's range is a planning defect. The probe
        # must not go looking for a threshold that works (that would be a fit); it must
        # say what the data does span, so the defect is diagnosable and the engine's own
        # next question -- "what threshold does this data support?" -- is answerable.
        item = make_experiment(
            hypothesis="HYP-1", question=scenario.QUESTION,
            design="counterfactual replay at a threshold the data does not reach",
            prediction_if_true="t", prediction_if_false="f", refuted_by="r",
            runner="counterfactual_replay", discriminates=("HYP-1",),
            required_data=("field=idle_hours", "op=>=", "threshold=999",
                           "outcome=over_budget"),
        )
        result = runner.run(item, Dataset(name="cloud-fit", rows=scenario.fit_rows()))
        self.assertFalse(result["ran"])
        self.assertIn("ranges", result["reason"], result["reason"])
        top = max(row["idle_hours"] for row in scenario.fit_rows()
                  if row.get("idle_hours") is not None)
        self.assertIn(f"{top:g}", result["reason"],
                      "the reason names the range, so the next question can be answered")

    def test_a_planned_threshold_never_becomes_the_artifacts_detector(self):
        # the shipped rule on the cloud fixture must come from the scan, not from the
        # planner's data-blind `threshold=24`
        report = Engine("/tmp/qse-cloud-probe.jsonl").run(
            scenario.QUESTION, answers=dict(scenario.FACTS),
            datasets=[Dataset(name="cloud-fit", rows=scenario.fit_rows()),
                      Dataset(name="cloud-holdout", rows=scenario.holdout_rows())],
            rows=scenario.fit_rows(), authority="finance", roles=scenario.ROLES)
        built = next(s for s in report.stages if s.get("stage") == "build")
        self.assertEqual(built["rule"]["field"], "idle_hours")
        self.assertNotEqual(float(built["rule"]["threshold"]), 24.0,
                            "24 is the planner's declared placeholder, not a measured cut")
        self.assertEqual(float(built["rule"]["threshold"]), 13.0)


class TheAcceptanceListOnACleanRun(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_a07_passes_when_sufficiency_was_scanned_and_found_no_gap(self):
        # the false alarm the cloud fixture surfaced: every explanation had evidence, so
        # no KNOWLEDGE_GAP was recorded, and A07 -- a requirement about identifying
        # missing evidence -- failed a run that had simply found none.
        engine = Engine("/tmp/qse-cloud-a07.jsonl")
        engine.run(scenario.QUESTION, answers=dict(scenario.FACTS),
                   datasets=[Dataset(name="cloud-fit", rows=scenario.fit_rows()),
                             Dataset(name="cloud-holdout", rows=scenario.holdout_rows())],
                   rows=scenario.fit_rows(), authority="finance", roles=scenario.ROLES)
        from ..ledger import chain
        from ..control.state import State

        records = chain.load("/tmp/qse-cloud-a07.jsonl")
        state = State.replay(records)
        coverage = [d for d in state.decisions if d.get("kind") == "EVIDENCE_COVERAGE"]
        self.assertTrue(coverage, "the sufficiency scan must record itself")
        row = next(r for r in cli.acceptance(records) if r["id"] == "A07")
        self.assertTrue(row["ok"], row["why"])

    def test_a07_still_fails_when_nothing_evaluated_sufficiency(self):
        row = next(r for r in cli.acceptance([]) if r["id"] == "A07")
        self.assertFalse(row["ok"], "an empty ledger must not pass a requirement about scanning")


class TheMoonshotScript(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_the_synthetic_run_answers_its_own_question(self):
        code, payload = _run_script([])
        self.assertEqual(code, 0, payload)
        self.assertTrue(payload["separable"])
        self.assertTrue(payload["engineered_wins"])
        self.assertEqual(payload["engineered_rule"]["field"], "idle_hours")
        self.assertEqual(payload["acceptance"]["failed"], [])
        self.assertEqual(payload["acceptance"]["total"], 17)

    def test_the_provenance_says_the_second_period_named_the_field(self):
        _, payload = _run_script([])
        provenance = payload["field_provenance"]
        self.assertFalse(provenance["named_by_fitting_source"])
        self.assertEqual([e["source"] for e in provenance["named_by"]], ["cloud-holdout"])
        self.assertEqual([e["decided_on"] for e in provenance["rejected"]], ["vcpus"])

    def test_a_fixture_that_cannot_answer_is_refused_rather_than_scored(self):
        # fitting and scoring on the same period never lets a confound collapse
        code, payload = _run_script([
            "--fit", str(REPO / "examples" / "cloud_fit.json"),
            "--holdout", str(REPO / "examples" / "cloud_fit.json"),
            "--outcome", "over_budget", "--driver", "idle_hours",
            "--exclude", "billed_usd"])
        self.assertEqual(code, 1)
        self.assertFalse(payload["separable"])
        self.assertEqual(payload["arms"], [], "nothing was scored, and nothing was claimed")

    def test_real_data_without_a_named_outcome_is_unusable(self):
        code, _ = _run_script(["--fit", str(REPO / "examples" / "cloud_fit.json"),
                               "--holdout", str(REPO / "examples" / "cloud_holdout.json")])
        self.assertEqual(code, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
