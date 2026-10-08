"""The moonshot's own acceptance list, run against a real ledger.

This is the test that matters. Everything above it tests a part; this runs the
whole loop over the shipped synthetic company and then asks the seventeen
questions the brief demands, from the ledger alone.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from .. import cli
from ..control.controller import Engine
from ..control.state import State
from ..experiment.runner import Dataset
from ..ledger import chain
from .support import Workspace, pin_clock, scenario_payload


def dataset(payload: dict) -> Dataset:
    return Dataset(name=payload["name"], rows=payload["rows"])


class TheWholeLoop(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        cls.ws = Workspace()
        cls.ledger = cls.ws.ledger("accept.jsonl")
        cls.scenario = scenario_payload()
        cls.holdout = scenario_payload("orders_holdout.json")
        engine = Engine(cls.ledger)
        cls.report = engine.run(
            cls.scenario["question"],
            answers=cls.scenario["facts"],
            datasets=[dataset(cls.scenario), dataset(cls.holdout)],
            rows=cls.scenario["rows"],
            authority="VP of Operations",
        )
        cls.records = engine.records()
        cls.engine = engine

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ws.close()

    def test_it_runs_to_completion_rather_than_blocking(self):
        self.assertFalse(self.report.blocked)
        self.assertGreaterEqual(len(self.report.stages), 10)

    def test_the_operator_brief_is_stated_at_decomposition(self):
        # answers are facts about the question, not something to be discovered one
        # blocking slot per revision; anything supplied is STATED from the start
        state = State.replay(self.records)
        root = [q for q in state.questions.values() if not q.revision_of][0]
        self.assertEqual(root.unresolved(), [], "the brief answered every slot")
        self.assertTrue(all(root.slots[name].confidence == "STATED" for name in root.slots))

    def test_the_question_is_revised_and_the_revision_names_its_trigger(self):
        mutations = [r for r in self.records if r["ev"] == "mutation"]
        self.assertTrue(mutations)
        self.assertTrue(all((m.get("trigger") or "").strip() for m in mutations))

    def test_the_brief_closes_ambiguities_without_deleting_them(self):
        # the finding is kept and marked closed; a brief that answered everything
        # must not erase the defect the raw question actually had
        recorded = [r for r in self.records if r["ev"] == "ambiguity"]
        self.assertTrue(recorded, "the question as asked had ambiguities")
        self.assertTrue(all("closed" in r for r in recorded),
                        "every ambiguity says whether the brief answered it")
        closed = [r for r in recorded if r["closed"]]
        self.assertTrue(closed, "the brief's answers resolve the slots they cover")

    def test_an_open_ambiguity_stops_the_engine_and_is_recorded(self):
        scenario = scenario_payload()
        partial = {k: v for k, v in scenario["facts"].items()
                   if k in ("referential", "proposition", "scope", "authority")}
        report = Engine(self.ws.ledger("open.jsonl")).run(
            scenario["question"], answers=partial,
            datasets=[dataset(scenario)], rows=scenario["rows"][:60])
        self.assertFalse(report.blocked, "every blocking slot was answered")
        stages = [s["stage"] for s in report.stages]
        self.assertTrue(any(s.startswith("revise") for s in stages),
                        "an unanswered BLOCKING ambiguity must be asked about")
        self.assertTrue(any(s.startswith("ambiguity-open") for s in stages),
                        "and recorded as open, not dropped")

    def test_the_engine_closes_the_loop_by_asking_the_next_question(self):
        self.assertTrue(self.report.next_question)
        self.assertTrue(self.report.next_question.strip().endswith("?"))

    def test_the_artifact_reaches_verified(self):
        artifacts = list(State.replay(self.records).artifacts.values())
        self.assertEqual([a["state"] for a in artifacts], ["VERIFIED"])

    def test_the_headline_metrics_are_what_the_run_produced(self):
        metrics = self.report.metrics
        self.assertEqual(metrics["QBY"]["value"], 1.0)
        self.assertEqual(metrics["BC"]["value"], 1.0)
        self.assertEqual(metrics["VI"]["value"], 1.0)
        self.assertEqual(metrics["EC"]["value"], 1.0)
        self.assertGreater(metrics["BSR"]["value"], 0)

    def test_the_outcome_is_not_counted_as_real_world_when_it_was_not(self):
        metrics = self.report.metrics
        self.assertEqual(metrics["OC"]["numerator"], 0)
        self.assertEqual(metrics["OC"]["value"], 0.0)

    def test_every_metric_carries_its_own_definition(self):
        for key in ("QBY", "BSR", "EC", "BC", "VI", "OC"):
            self.assertTrue(self.report.metrics[key]["definition"], key)

    def test_the_run_states_what_its_numbers_cannot_see(self):
        self.assertTrue(self.report.metrics["limits"])


class TheAcceptanceList(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        cls.ws = Workspace()
        cls.ledger = cls.ws.ledger("accept.jsonl")
        scenario = scenario_payload()
        holdout = scenario_payload("orders_holdout.json")
        engine = Engine(cls.ledger)
        engine.run(scenario["question"], answers=scenario["facts"],
                   datasets=[dataset(scenario), dataset(holdout)],
                   rows=scenario["rows"], authority="VP of Operations")
        cls.records = engine.records()
        cls.checks = cli.acceptance(cls.records)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ws.close()

    def test_the_list_is_the_seventeen_declared_conditions(self):
        self.assertEqual(len(cli.ACCEPTANCE), 17)
        self.assertEqual(len(self.checks), 17)
        self.assertEqual([c["id"] for c in self.checks], [c[0] for c in cli.ACCEPTANCE])
        self.assertEqual([c["label"] for c in self.checks], [c[1] for c in cli.ACCEPTANCE])
        # `why` is the measured detail and `label` is the declared condition, so a
        # reader gets both the requirement and what was actually counted against it
        for check in self.checks:
            self.assertNotEqual(check["why"], check["label"])

    def test_every_condition_holds(self):
        failed = [c for c in self.checks if not c["ok"]]
        self.assertEqual(failed, [], f"unmet: {[c['id'] for c in failed]}")

    def test_every_check_shows_the_evidence_it_decided_from(self):
        for check in self.checks:
            self.assertIsInstance(check["evidence"], dict)
            self.assertTrue(check["evidence"], check["id"])

    def test_the_check_count_matches_the_ledger_it_read(self):
        by_id = {c["id"]: c for c in self.checks}
        self.assertEqual(by_id["A04"]["evidence"]["n"],
                         sum(1 for r in self.records if r["ev"] == "inversion"
                             and r.get("consequence")))
        self.assertEqual(by_id["A08"]["evidence"]["n"],
                         len({r["xid"] for r in self.records if r["ev"] == "experiment"}))

    def test_a_check_that_cannot_hold_fails_rather_than_being_skipped(self):
        empty = cli.acceptance([])
        self.assertTrue(all(check["ok"] is False for check in empty),
                        "an empty ledger satisfies nothing")

    def test_the_cli_command_agrees_with_the_function(self):
        buffer, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(buffer), redirect_stderr(errors):
            code = cli.main(["checks", "--ledger", self.ledger])
        printed, complaints = buffer.getvalue(), errors.getvalue()
        buffer.close()
        errors.close()
        self.assertEqual(code, 0, complaints)
        self.assertIn("17/17", printed)


class Auditability(unittest.TestCase):
    """The brief's final test: can another process say why these questions were asked?"""

    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        cls.ws = Workspace()
        cls.ledger = cls.ws.ledger("accept.jsonl")
        scenario = scenario_payload()
        engine = Engine(cls.ledger)
        engine.run(scenario["question"], answers=scenario["facts"],
                   datasets=[dataset(scenario)], rows=scenario["rows"][:200],
                   authority="VP of Operations")
        cls.records = engine.records()
        cls.engine = engine

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ws.close()

    def test_the_state_rebuilds_from_the_ledger_alone(self):
        state = State.replay(self.records)
        self.assertEqual(state.unknown, 0)
        self.assertEqual(state.errors, [])
        self.assertEqual(len(state.questions),
                         len({r["qid"] for r in self.records if r["ev"] == "question"}))
        # a revision is a new question linked to its parent, not a second version
        # of the root, so the chain is walkable from any question back to the text
        children = [q for q in state.questions.values() if q.revision_of]
        self.assertTrue(children, "the investigation produced a next question")
        self.assertTrue(all(c.revision_of in state.questions for c in children))
        self.assertEqual(len(state.questions),
                         sum(1 for r in self.records if r["ev"] == "question"))
        self.assertEqual(len(state.hypotheses),
                         sum(1 for r in self.records if r["ev"] == "hypothesis"))
        self.assertEqual(len(state.artifacts),
                         len({r["aid"] for r in self.records if r["ev"] == "artifact"}))

    def test_every_question_has_a_complete_reason_chain(self):
        state = State.replay(self.records)
        for qid in state.questions:
            answer = self.engine.why(qid)
            self.assertTrue(answer["found"], qid)
            self.assertTrue(answer["complete"], f"{qid}: {answer}")

    def test_the_reason_chain_names_the_ambiguity_that_caused_the_revision(self):
        state = State.replay(self.records)
        child = [q for q in state.questions.values() if q.revision_of]
        self.assertTrue(child, "the run should have revised at least one question")
        answer = self.engine.why(child[0].qid)
        self.assertEqual(answer["root"], answer["chain"][0]["qid"])
        self.assertTrue(answer["chain"][-1]["trigger"])

    def test_the_alternative_that_lost_is_in_the_ledger_with_the_reason(self):
        decisions = [r for r in self.records if r["ev"] == "decision"
                     and r.get("kind") == "QUESTION_MUTATION"]
        self.assertTrue(decisions)
        for row in decisions:
            self.assertIn("rejected:", row["why"])
            self.assertTrue(row.get("alternatives"))

    def test_the_question_the_engine_asked_is_the_one_the_gain_report_ranked_first(self):
        state = State.replay(self.records)
        decisions = {(r.get("subject"), r.get("chosen")) for r in self.records
                     if r["ev"] == "decision" and r.get("kind") == "QUESTION_MUTATION"}
        mutations = {(r.get("parent"), r.get("text")) for r in self.records
                     if r["ev"] == "mutation"}
        self.assertTrue(decisions <= mutations,
                        "a mutation was recorded that no decision chose")
        self.assertTrue(state.mutations)


class TheBlockedPath(unittest.TestCase):
    """When a blocking slot cannot be answered, the loop must stop, not guess."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.ledger = self.ws.ledger("blocked.jsonl")
        scenario = scenario_payload()
        self.engine = Engine(self.ledger)
        self.report = self.engine.run(scenario["question"], answers={},
                                      datasets=[dataset(scenario)],
                                      rows=scenario["rows"][:60])

    def tearDown(self) -> None:
        self.ws.close()

    def test_it_blocks_rather_than_inventing_the_answer(self):
        self.assertTrue(self.report.blocked)

    def test_it_says_which_question_would_have_unblocked_it(self):
        self.assertTrue(self.report.next_question)

    def test_the_refusal_is_recorded_under_the_right_rule(self):
        blocked = [r for r in self.engine.records() if r["ev"] == "decision"
                   and r.get("kind") == "BLOCKED"]
        self.assertTrue(blocked)
        self.assertIn("R-QUE-1", blocked[0]["why"])

    def test_no_inversion_was_run_while_the_question_was_unanswerable(self):
        kinds = {r["ev"] for r in self.engine.records()}
        self.assertNotIn("inversion", kinds,
                         "nothing may be consumed while a blocking slot is open")

    def test_a_partial_brief_still_blocks_on_what_it_did_not_answer(self):
        scenario = scenario_payload()
        partial = {k: v for k, v in scenario["facts"].items() if k != "scope"}
        ledger = self.ws.ledger("partial.jsonl")
        report = Engine(ledger).run(scenario["question"], answers=partial,
                                    datasets=[dataset(scenario)], rows=scenario["rows"][:60])
        self.assertTrue(report.blocked, "scope was never supplied and must not be invented")
        stages = [s["stage"] for s in report.stages]
        self.assertIn("blocked", stages)


class Determinism(unittest.TestCase):
    """A run is only reproducible if the same input produces the same ledger."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        scenario = scenario_payload()
        self.rows = scenario["rows"][:150]
        self.answers = scenario["facts"]
        self.question = scenario["question"]

    def tearDown(self) -> None:
        self.ws.close()

    def _run(self, name: str) -> str:
        ledger = self.ws.ledger(name)
        engine = Engine(ledger)
        engine.run(self.question, answers=self.answers,
                   datasets=[Dataset(name="orders", rows=self.rows)],
                   rows=self.rows, authority="VP of Operations")
        return ledger

    def test_the_same_input_produces_a_byte_identical_ledger(self):
        first = self._run("one.jsonl")
        second = self._run("two.jsonl")
        self.assertEqual(chain.read_lines(first), chain.read_lines(second))

    def test_the_same_input_produces_the_same_metrics(self):
        first = Engine(self._run("three.jsonl")).metrics()
        second = Engine(self._run("four.jsonl")).metrics()
        self.assertEqual(first["QBY"], second["QBY"])
        self.assertEqual(first["BSR"], second["BSR"])

    def test_a_different_authority_changes_the_result(self):
        # the authority is written into every assumption's source, so a different
        # authority must not produce the same bytes -- otherwise it is not recorded
        first = self._run("five.jsonl")
        ledger = self.ws.ledger("six.jsonl")
        Engine(ledger).run(self.question, answers=self.answers,
                           datasets=[Dataset(name="orders", rows=self.rows)],
                           rows=self.rows, authority="Someone Else")
        self.assertNotEqual(chain.read_lines(first), chain.read_lines(ledger))


class TheCliVerdicts(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.ledger = self.ws.ledger("cli.jsonl")
        scenario = scenario_payload()
        Engine(self.ledger).run(scenario["question"], answers=scenario["facts"],
                                datasets=[dataset(scenario)], rows=scenario["rows"][:200],
                                authority="VP of Operations")

    def tearDown(self) -> None:
        self.ws.close()

    def _run_cli(self, argv: list[str]) -> int:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        self.assertIn(code, (0, 1, 2))
        out.close()
        err.close()
        return code

    def test_rules_prints_every_refusal(self):
        self.assertEqual(self._run_cli(["rules"]), 0)

    def test_replay_rebuilds_without_losing_an_event(self):
        self.assertEqual(self._run_cli(["replay", "--ledger", self.ledger]), 0)

    def test_receipt_renders_one_line_per_event(self):
        self.assertEqual(self._run_cli(["receipt", "--ledger", self.ledger]), 0)

    def test_metrics_exits_clean(self):
        self.assertEqual(self._run_cli(["metrics", "--ledger", self.ledger]), 0)

    def test_why_answers_for_a_real_question(self):
        state = State.replay(chain.load(self.ledger))
        self.assertEqual(self._run_cli(["why", next(iter(state.questions)), "--ledger", self.ledger]), 0)

    def test_why_reports_a_question_it_does_not_have(self):
        self.assertEqual(self._run_cli(["why", "Q-not-in-this-ledger", "--ledger", self.ledger]), 1)

    def test_a_missing_ledger_is_unusable_input(self):
        self.assertEqual(self._run_cli(["checks", "--ledger", self.ws.file("nope.jsonl").as_posix()]), 2)

    def test_a_tampered_ledger_is_a_defect_not_a_missing_file(self):
        lines = chain.read_lines(self.ledger)
        lines[1] = lines[1].replace("a", "b", 1)
        tampered = self.ws.file("tampered.jsonl")
        tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertEqual(self._run_cli(["replay", "--ledger", str(tampered)]), 1)

    def test_ask_and_invert_run_on_a_bare_question(self):
        self.assertEqual(self._run_cli(["ask", "Can we predict bottlenecks?"]), 0)
        self.assertEqual(self._run_cli(["invert", "Can we predict bottlenecks?"]), 0)

    def test_json_output_is_valid_json(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cli.main(["--json", "ask", "Can we predict bottlenecks?"])
        payload = json.loads(out.getvalue())
        out.close()
        err.close()
        self.assertEqual(len(payload["seven_slots"]), 7)


class TheHonestRefusal(unittest.TestCase):
    """A brief that names nobody must not end in a verified artifact.

    The point is not that the run crashes -- it is that the run says no, in
    public, and that the acceptance list reflects the refusal rather than
    passing on a count that happens to look full.
    """

    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        cls.ws = Workspace()
        payload = scenario_payload()
        cls.answers = {k: v for k, v in payload["facts"].items() if k != "authority"}
        engine = Engine(cls.ws.ledger("refused.jsonl"))
        cls.report = engine.run(
            payload["question"], answers=cls.answers,
            datasets=[dataset(payload)], rows=payload["rows"],
        )
        cls.records = engine.records()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ws.close()

    def test_the_artifact_is_rejected_rather_than_verified(self):
        states = [r["state"] for r in self.records if r["ev"] == "artifact"]
        self.assertIn("REJECTED", states)
        self.assertNotIn("VERIFIED", states)

    def test_the_refusal_names_the_attack_that_caused_it(self):
        landed = [r for r in self.records if r["ev"] == "attack" and r["landed"]]
        self.assertTrue(landed, "with no authority named, something must land")
        refused = [r for r in self.records if r.get("kind") == "VERIFICATION_REFUSED"]
        self.assertTrue(refused)
        self.assertIn(landed[0]["kind"], refused[0]["why"])

    def test_the_acceptance_list_does_not_pass_a_rejected_run(self):
        rows = {r["id"]: r for r in cli.acceptance(self.records)}
        self.assertFalse(rows["A10"]["ok"], "nothing reached a usable artifact state")
        self.assertFalse(rows["A12"]["ok"], "no independent verification passed")

    def test_an_experiment_that_cannot_run_is_a_decision_and_not_evidence(self):
        not_run = [r for r in self.records if r.get("kind") == "EXPERIMENT_NOT_RUN"]
        if not not_run:
            self.skipTest("every planned test ran on this dataset")
        unran = {str(r["subject"]).split("@")[0] for r in not_run}
        used = {str(e.get("experiment", "")) for e in self.records if e["ev"] == "evidence"}
        self.assertFalse(unran & used, "a test that never ran must not produce evidence")


class TheClockDoesNotDecide(unittest.TestCase):
    """The verdict must come from the ledger, not from what day it happens to be."""

    def setUp(self) -> None:
        self.ws = Workspace()
        self.scenario = scenario_payload()

    def tearDown(self) -> None:
        self.ws.close()

    def _verdicts(self, moment: str, name: str):
        pin_clock(moment)
        engine = Engine(self.ws.ledger(name))
        engine.run(self.scenario["question"], answers=self.scenario["facts"],
                   datasets=[dataset(self.scenario)],
                   rows=self.scenario["rows"][:150], authority="VP of Operations")
        rows = [(r["id"], r["ok"]) for r in cli.acceptance(engine.records())]
        metrics = engine.metrics()
        values = {k: v.get("value") for k, v in metrics.items() if isinstance(v, dict)}
        return rows, values

    def test_two_different_clocks_produce_the_same_verdict(self):
        first, m1 = self._verdicts("2026-10-07T00:00:00Z", "clock-a.jsonl")
        second, m2 = self._verdicts("2031-03-04T09:00:00Z", "clock-b.jsonl")
        self.assertEqual(first, second, "the acceptance verdict moved with the clock")
        self.assertEqual(m1, m2, "a metric moved with the clock")

    def test_the_clock_is_still_written_into_the_ledger(self):
        # portable and reproducible pull in opposite directions: the verdict is
        # clock-free, and the record of when it was reached is not
        self._verdicts("2029-01-01T00:00:00Z", "clock-c.jsonl")
        records = chain.load(self.ws.ledger("clock-c.jsonl"))
        self.assertTrue(all(r.get("ts", "").startswith("2029-") for r in records))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
