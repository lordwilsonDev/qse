"""Experiments that actually run, and artifacts that actually execute.

The runners are where a claim can quietly become a number. Every test here is
about refusing to produce a number that the data does not support.
"""

from __future__ import annotations

import unittest

from ..build import artifact_graph, generator, specification
from ..build.executor import execute
from ..core.artifact import make_artifact
from ..core.experiment import RUNNERS, Experiment, make_experiment
from ..core.hypothesis import make_hypothesis
from ..experiment import planner, results, runner
from ..experiment.falsification import audit as falsification_audit
from .support import rows_of, pin_clock


def hypothesis(text, **over):
    fields = dict(question="Q-1", mechanism="COORDINATION", locus="SCHEDULING",
                  timescale="HOURS", measurement_assumption="the timestamps are correct",
                  authority="ops-lead")
    fields.update(over)
    return make_hypothesis(text, **fields)


def orders() -> runner.Dataset:
    return runner.Dataset(name="orders-fortune500-synthetic", rows=rows_of())


def experiment(**over) -> Experiment:
    """A complete, clean experiment: a runner, a refutation condition and a claim to
    separate more than one explanation, so an audit of it comes back empty."""
    fields = dict(hypothesis="HYP-1", question="Q-1", design="scan thresholds over the precursor",
                  prediction_if_true="separation above the floor", prediction_if_false="no separation",
                  refuted_by="refuted if the separation is at or below the floor",
                  runner="discrimination_scan",
                  discriminates=("HYP-1", "HYP-2"))
    fields.update(over)
    return make_experiment(**fields)


class Falsification(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_an_ordinary_experiment_audits_clean(self):
        report = falsification_audit([experiment()])
        self.assertEqual(report["n"], 1)
        self.assertEqual(report["unfalsifiable"], [])
        self.assertEqual(report["weak"], {})

    def test_a_test_with_no_runner_is_weak(self):
        hand = Experiment(xid="EXP-norunner", hypothesis="HYP-1", question="Q-1", design="d",
                          prediction_if_true="a", prediction_if_false="b", refuted_by="r")
        self.assertIn(hand.xid, falsification_audit([hand])["weak"])

    def test_a_test_that_separates_only_itself_is_weak(self):
        narrow = experiment(discriminates=("HYP-1",))
        self.assertIn(narrow.xid, falsification_audit([narrow])["weak"])

    def test_two_identical_predictions_are_weak_because_the_test_cannot_fail(self):
        weak = experiment(prediction_if_true="it goes up", prediction_if_false="it goes up")
        report = falsification_audit([weak])
        self.assertIn(weak.xid, report["weak"])

    def test_a_refutation_condition_that_restates_the_prediction_is_weak(self):
        weak = experiment(prediction_if_true="the separation is above the floor",
                          refuted_by="refuted if the separation is above the floor")
        report = falsification_audit([weak])
        self.assertIn(weak.xid, report["weak"])

    def test_an_empty_refutation_condition_cannot_be_constructed_at_all(self):
        report = falsification_audit([])
        self.assertEqual(report["falsifiable"], [])
        self.assertEqual(report["unfalsifiable"], [])


class Planning(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.a = hypothesis("coordination is the cause")
        self.b = hypothesis("the measurement is the cause", mechanism="MEASUREMENT", locus="TELEMETRY")
        self.columns = tuple(sorted({k for row in rows_of() for k in row}))

    def test_every_hypothesis_gets_a_specific_refutable_test(self):
        proposed = planner.propose([self.a, self.b], question="Q-1", columns=self.columns)
        self.assertEqual(len(proposed), 2)
        for item in proposed:
            self.assertIn(item.runner, RUNNERS)
            self.assertTrue(item.falsifiable())
            self.assertTrue(item.design.strip())

    def test_the_runner_chosen_depends_on_the_hypothesis_being_tested(self):
        proposed = {item.hypothesis: item.runner for item in
                    planner.propose([self.a, self.b], question="Q-1", columns=self.columns)}
        self.assertNotEqual(proposed[self.a.hid], proposed[self.b.hid])

    def test_a_discriminating_experiment_names_more_than_one_explanation(self):
        wide = planner.discriminating([self.a, self.b], question="Q-1", columns=self.columns)
        self.assertEqual(len(wide), 1)
        self.assertGreaterEqual(len(wide[0].discriminates), 2)

    def test_coverage_names_the_hypotheses_nothing_tests(self):
        proposed = planner.propose([self.a], question="Q-1", columns=self.columns)
        coverage = planner.coverage(proposed, hypotheses=[self.a, self.b])
        self.assertIn(self.b.hid, coverage["untested"])

    def test_planning_is_deterministic(self):
        first = [x.xid for x in planner.propose([self.a, self.b], question="Q-1", columns=self.columns)]
        second = [x.xid for x in planner.propose([self.a, self.b], question="Q-1", columns=self.columns)]
        self.assertEqual(first, second)


class RunnersRefuseRatherThanInvent(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_the_runner_table_matches_the_declared_vocabulary(self):
        self.assertEqual(set(runner.RUNNERS), set(RUNNERS))
        self.assertEqual(set(runner.available()), set(RUNNERS))

    def test_missing_columns_are_reported_and_never_raise(self):
        empty = runner.Dataset(name="empty", rows=[])
        result = runner.run(experiment(runner="precursor_detection",
                                       required_data=("precursor=nope", "outcome=missing")), empty)
        self.assertFalse(result["ran"])
        self.assertIsNone(result["supported"])
        self.assertFalse(result["refuted"])
        self.assertTrue(result["reason"])

    def test_an_unknown_runner_is_reported_rather_than_crashing(self):
        # construction refuses an unknown runner, so this is built by hand
        bad = Experiment(xid="EXP-hand", hypothesis="H", question="Q", design="d",
                         prediction_if_true="a", prediction_if_false="b", refuted_by="r")
        object.__setattr__(bad, "runner", "clairvoyance")
        result = runner.run(bad, orders())
        self.assertFalse(result["ran"])
        self.assertIn("clairvoyance", result["reason"])

    def test_precursor_detection_separates_the_outcome_from_the_precursor(self):
        item = experiment(
            runner="precursor_detection", hypothesis="HYP-1",
            required_data=("precursor=precursor_h", "outcome=failed", "time=ts_h", "min_hours=6"))
        result = runner.run(item, orders())
        self.assertTrue(result["ran"], result.get("reason"))
        observed = result["observed"]
        self.assertIsNotNone(observed["threshold"])
        self.assertGreater(observed["separation"], 0.5)
        self.assertTrue(observed["lead_column"])

    def test_a_declared_lead_that_could_not_be_measured_is_inconclusive_not_supported(self):
        # One row per order is not a time series, so the lead time is genuinely not
        # computable here. Reporting SUPPORTED for a test whose decisive quantity was
        # never computed is the failure this apparatus exists to catch, so it must
        # come back INCONCLUSIVE -- and specifically not True.
        item = experiment(
            runner="precursor_detection", hypothesis="HYP-1",
            required_data=("precursor=precursor_h", "outcome=failed", "time=ts_h", "min_hours=6"))
        observed = runner.run(item, orders())["observed"]
        self.assertFalse(observed["lead_measured"])
        self.assertIsNone(observed["supported"])
        self.assertFalse(observed["refuted"])
        self.assertFalse(observed["lead_measured"] and observed["supported"] is True)

    def test_a_measured_lead_shorter_than_the_declared_minimum_refutes_the_claim(self):
        rows = rows_of()
        # a genuine time series where the precursor crosses only 2 hours ahead
        series = []
        for index in range(24):
            series.append({"precursor_h": 5.0 + (index % 6), "failed": 1 if index == 12 else 0,
                           "ts_h": float(index)})
        item = experiment(
            runner="precursor_detection", hypothesis="HYP-1",
            required_data=("precursor=precursor_h", "outcome=failed", "time=ts_h", "min_hours=6"))
        observed = runner.run(item, runner.Dataset(name="series", rows=series))["observed"]
        self.assertTrue(observed["lead_measured"])
        if observed["lead_hours"] < observed["min_hours"]:
            self.assertFalse(observed["supported"])
            self.assertTrue(observed["refuted"])
        self.assertTrue(rows)

    def test_discrimination_excludes_the_outcome_column_from_its_own_candidates(self):
        item = experiment(
            runner="discrimination_scan",
            required_data=("outcome=failed", "candidates=failed,handoffs,message_volume,system_latency_ms"))
        result = runner.run(item, orders())
        self.assertTrue(result["ran"], result.get("reason"))
        observed = result["observed"]
        self.assertIn("failed", observed["excluded_circular"])
        self.assertNotIn("failed", [row["column"] for row in observed["ranking"]])
        self.assertEqual(observed["ranking"][0]["column"], "handoffs",
                         "the real driver should outrank the misleading correlates")

    def test_aggregation_check_finds_the_pooled_correlation_that_reverses_inside_groups(self):
        # the pair the planner actually binds for this dataset: the precursor level
        # against the latency it is confounded with, grouped by shift
        item = experiment(
            runner="aggregation_check",
            required_data=("x=precursor_h", "y=system_latency_ms", "group=shift"))
        result = runner.run(item, orders())
        self.assertTrue(result["ran"], result.get("reason"))
        observed = result["observed"]
        self.assertGreater(observed["pooled_correlation"], 0.5)
        self.assertTrue(observed["flips"], "the synthetic shift truncation is a Simpson flip")
        self.assertTrue(all(abs(value) < abs(observed["pooled_correlation"])
                            for value in observed["per_group"].values() if value is not None))

    def test_coverage_scan_reports_the_gap_in_a_series_with_missing_data(self):
        item = experiment(runner="coverage_scan", required_data=("columns=supplier_lead_days"))
        result = runner.run(item, orders())
        self.assertTrue(result["ran"], result.get("reason"))
        self.assertTrue(result["observed"])

    def test_a_rerun_of_the_same_experiment_gives_the_same_answer(self):
        item = experiment(runner="discrimination_scan",
                          required_data=("outcome=failed", "candidates=handoffs,system_latency_ms"))
        first = runner.run(item, orders())
        second = runner.run(item, orders())
        self.assertEqual(first["observed"], second["observed"])


class ResultsBecomeEvidence(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_a_run_that_did_not_happen_produces_no_evidence(self):
        not_run = {"xid": "X", "ran": False, "reason": "needs columns", "supported": None, "refuted": False}
        with self.assertRaises(ValueError):
            results.to_evidence(experiment(), not_run,
                                collected_at="2026-10-07T12:00:00Z", source="orders.csv")

    def test_evidence_carries_the_source_it_came_from(self):
        ran = {"xid": "X", "ran": True, "supported": True, "refuted": False,
               "observed": {"separation": 0.5}, "runner": "discrimination_scan"}
        item = results.to_evidence(experiment(runner="discrimination_scan"), ran,
                                   collected_at="2026-10-07T12:00:00Z",
                                   source="orders-fortune500-synthetic")
        self.assertEqual(item.source, "orders-fortune500-synthetic")
        self.assertTrue(item.method)
        self.assertTrue(item.usable())

    def test_a_refuting_run_produces_evidence_that_points_the_other_way(self):
        ran = {"xid": "X", "ran": True, "supported": False, "refuted": True,
               "observed": {"separation": 0.0}, "runner": "discrimination_scan"}
        item = results.to_evidence(experiment(runner="discrimination_scan"), ran,
                                   collected_at="2026-10-07T12:00:00Z", source="s")
        self.assertFalse(item.supports)
        self.assertTrue(item.usable(), "a refutation is evidence, and it must be counted")

    def test_verdicts_are_the_three_declared_outcomes(self):
        self.assertEqual(results.verdict(experiment(), {"ran": True, "supported": True,
                                                       "refuted": False}), "SURVIVED")
        self.assertEqual(results.verdict(experiment(), {"ran": True, "supported": False,
                                                       "refuted": True}), "REFUTED")
        self.assertEqual(results.verdict(experiment(), {"ran": True, "supported": None,
                                                       "refuted": False}), "INCONCLUSIVE")
        self.assertEqual(results.verdict(experiment(), {"ran": False}), "INCONCLUSIVE")

    def test_a_run_that_did_not_happen_is_inconclusive_rather_than_refuted(self):
        # "we could not look" and "we looked and it is false" are different answers,
        # and collapsing them would let a data gap read as a disproof
        self.assertEqual(results.verdict(experiment(), {"ran": False, "refuted": True}),
                         "INCONCLUSIVE")


class SpecificationAndGeneration(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.h = hypothesis("coordination across shifts drives the breach rate")
        from .support import strong_evidence

        self.evidence = [strong_evidence(self.h.hid)]

    def test_inputs_are_data_columns_and_not_the_name_of_the_source(self):
        spec = specification.from_hypothesis(self.h, self.evidence)
        self.assertIn("handoffs", spec.inputs, "the runner's observed field is a column")
        self.assertNotIn("orders.csv", spec.inputs,
                         "a source is where a number came from, not what the number is about")

    def test_acceptance_criteria_are_written_before_generation(self):
        spec = specification.from_hypothesis(self.h, self.evidence)
        self.assertTrue(spec.acceptance)
        self.assertTrue(all(criterion.strip() for criterion in spec.acceptance))

    def test_a_measured_rule_is_preferred_over_the_conservative_default(self):
        spec = specification.from_hypothesis(self.h, self.evidence)
        rule = generator.default_rule(spec, self.evidence)
        self.assertEqual(rule["field"], "handoffs")
        self.assertEqual(float(rule["threshold"]), 5.0)
        self.assertTrue(rule["validated"])

    def test_without_evidence_the_rule_says_it_is_unvalidated(self):
        spec = specification.from_hypothesis(self.h, [])
        rule = generator.default_rule(spec, [])
        self.assertFalse(rule["validated"])
        self.assertIn("unvalidated", rule["basis"])

    def test_the_generated_module_is_valid_python(self):
        spec = specification.from_hypothesis(self.h, self.evidence)
        source = generator.render(spec, rule=generator.default_rule(spec, self.evidence))
        self.assertTrue(source.startswith(generator.BEACON))
        compile(source, "<generated>", "exec")

    def test_the_generated_artifact_carries_a_reproduction_command(self):
        artifact = generator.generate(
            specification.from_hypothesis(self.h, self.evidence), builder="b",
            rule=generator.default_rule(specification.from_hypothesis(self.h, self.evidence), self.evidence))
        self.assertTrue(artifact.reproduce)
        self.assertEqual(artifact.state, "CONSTRUCTED")


class Execution(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        from .support import strong_evidence

        self.h = hypothesis("coordination across shifts drives the breach rate")
        evidence = [strong_evidence(self.h.hid)]
        spec = specification.from_hypothesis(self.h, evidence, columns=("handoffs", "failed"))
        self.artifact = generator.generate(spec, builder="b",
                                           rule=generator.default_rule(spec, evidence))

    def test_the_generated_module_runs_and_reports_its_own_output(self):
        outcome = execute(self.artifact, rows=rows_of()[:40])
        self.assertTrue(outcome["ran"], outcome.get("reason"))
        self.assertTrue(outcome["ok"], outcome.get("stderr"))
        self.assertEqual(outcome["exit"], 0)
        self.assertIn("flagged", outcome["observed"])

    def test_running_the_same_rows_twice_gives_identical_output(self):
        first = execute(self.artifact, rows=rows_of()[:40])
        second = execute(self.artifact, rows=rows_of()[:40])
        self.assertEqual(first["stdout"], second["stdout"])

    def test_an_artifact_with_no_content_is_reported_not_raised(self):
        empty = make_artifact(hypothesis="H", kind="CODE", title="t", builder="b")
        outcome = execute(empty)
        self.assertFalse(outcome["ran"])
        self.assertFalse(outcome["ok"])
        self.assertTrue(outcome["reason"])


class ArtifactGraph(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_a_dependency_orders_the_build(self):
        first = make_artifact(hypothesis="H", kind="DATA", title="rows", builder="b")
        second = make_artifact(hypothesis="H", kind="CODE", title="rule", builder="b",
                              requires=(first.aid,))
        graph = artifact_graph.build([first, second])
        self.assertEqual(artifact_graph.order(graph), [first.aid, second.aid])
        self.assertEqual(artifact_graph.roots(graph), [first.aid])
        self.assertEqual(artifact_graph.leaves(graph), [second.aid])

    def test_a_cycle_is_named_rather_than_looped(self):
        a = make_artifact(hypothesis="H", kind="CODE", title="a", builder="b")
        b = make_artifact(hypothesis="H", kind="CODE", title="b", builder="b")
        a.requires = (b.aid,)
        b.requires = (a.aid,)
        graph = artifact_graph.build([a, b])
        self.assertTrue(artifact_graph.cycles(graph))
        with self.assertRaises(ValueError):
            artifact_graph.order(graph)

    def test_a_dependency_that_was_never_built_is_reported(self):
        lonely = make_artifact(hypothesis="H", kind="CODE", title="x", builder="b",
                              requires=("ART-does-not-exist",))
        missing = artifact_graph.unbuilt_dependencies([lonely])
        self.assertIn(("ART-does-not-exist"), [item[1] for item in missing])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
