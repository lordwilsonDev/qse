"""AIL, MoIE and the reasoning layer.

Two claims are load-bearing here and both are tested directly: an inversion
without a testable consequence never becomes a hypothesis source, and no
hypothesis is ever selected by counting how many experts hold it.
"""

from __future__ import annotations

import unittest

from ..core.evidence import make_evidence
from ..core.hypothesis import MECHANISMS, STRUCTURE_FIELDS, make_hypothesis
from ..core.question import make_question
from ..inversion import axiom as axiom_mod
from ..inversion import moie, operators
from ..inversion.ail import AILEngine
from ..reasoning import disagreement as disagreement_mod
from ..reasoning import hypothesis as hypothesis_mod
from ..reasoning import synthesis
from ..reasoning.uncertainty import load as uncertainty_load
from ..reasoning.uncertainty import survey as uncertainty_survey
from .support import FORTUNE, pin_clock

TS = "2026-10-07T12:00:00Z"


def question(answers=None):
    base = {"proposition": FORTUNE, "scope": "one plant, three shifts"}
    base.update(answers or {})
    return make_question(FORTUNE, base)


def hypothesis(text, **over):
    fields = dict(question="Q-1", mechanism="COORDINATION", locus="SCHEDULING",
                  timescale="HOURS", measurement_assumption="the timestamps are correct",
                  authority="ops-lead")
    fields.update(over)
    return make_hypothesis(text, **fields)


def paper(hypothesis_id, *, strength="STRONG", supports=True, kind="MEASURED", claim="c"):
    return make_evidence(claim, hypothesis=hypothesis_id, kind=kind, source="orders.csv",
                         method="pearson on complete pairs", collected_at=TS,
                         supports=supports, strength=strength)


class AxiomExtraction(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = question()
        self.axioms = axiom_mod.extract(self.question)

    def test_it_extracts_something_to_invert(self):
        self.assertTrue(self.axioms)

    def test_every_axiom_uses_the_declared_vocabulary(self):
        for item in self.axioms:
            self.assertIn(item.kind, axiom_mod.KINDS, item.aid)
            self.assertTrue(item.text.strip())
            self.assertTrue(item.because.strip(), "an axiom with no reason cannot be argued with")

    def test_axiom_ids_are_unique_and_stable(self):
        again = axiom_mod.extract(self.question)
        self.assertEqual([a.aid for a in self.axioms], [a.aid for a in again])
        self.assertEqual(len({a.aid for a in self.axioms}), len(self.axioms))

    def test_the_measurement_axiom_refers_to_the_question_it_came_from(self):
        for item in self.axioms:
            self.assertEqual(item.source_question, self.question.qid)


class TheAILGate(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.engine = AILEngine(question())

    def test_every_operator_exists_and_is_a_different_function(self):
        self.assertEqual(set(operators.OPERATORS), set(operators.OPERATOR_FUNCTIONS))
        self.assertEqual(len(operators.OPERATORS), 7)
        self.assertEqual(len({id(fn) for fn in operators.OPERATOR_FUNCTIONS.values()}), 7)

    def test_every_accepted_inversion_carries_a_testable_consequence(self):
        accepted = self.engine.invert()
        self.assertTrue(accepted)
        for item in accepted:
            self.assertIsNotNone(item.consequence, item.iid)
            self.assertTrue(item.consequence.observation.strip())
            self.assertTrue(item.consequence.if_true.strip())
            self.assertTrue(item.consequence.if_false.strip())
            self.assertTrue(item.consequence.discriminates.strip())

    def test_an_inversion_with_no_consequence_is_refused_and_recorded(self):
        rejected = self.engine.rejected()
        self.assertTrue(rejected, "the gate must have something reachable to refuse")
        for row in rejected:
            self.assertEqual(row["rule"], "R-INV-1")
            self.assertTrue(row["reason"])

    def test_accepted_plus_refused_accounts_for_every_candidate(self):
        self.assertEqual(len(self.engine.invert()) + len(self.engine.rejected()),
                         len(self.engine.candidates()))

    def test_the_gate_never_silently_drops_one(self):
        statements = {i.statement for i in self.engine.candidates()}
        kept = {i.statement for i in self.engine.invert()}
        dropped = {r["statement"] for r in self.engine.rejected()}
        self.assertEqual(statements, kept | dropped)

    def test_the_consequence_serialises_for_the_ledger(self):
        payload = self.engine.invert()[0].to_dict()
        self.assertIsInstance(payload["consequence"], dict)

    def test_inversion_ids_are_stable(self):
        first = [i.iid for i in AILEngine(question()).invert()]
        second = [i.iid for i in AILEngine(question()).invert()]
        self.assertEqual(first, second)


class MoIEExperts(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = question()
        self.engine = AILEngine(self.question)
        self.reports = moie.convene(self.question, self.engine)

    def test_there_are_seven_experts_and_each_uses_a_different_operator(self):
        self.assertEqual(len(moie.EXPERTS), 7)
        self.assertEqual(len(self.reports), 7)
        self.assertEqual({r.operator for r in self.reports}, set(operators.OPERATORS))

    def test_the_experts_do_not_all_find_the_same_thing(self):
        signatures = {tuple(sorted(i.kind for i in r.inversions)) for r in self.reports}
        self.assertGreater(len(signatures), 1,
                           "seven experts producing one view is one expert with seven names")

    def test_measurement_reports_disagreement(self):
        measured = moie.measure(self.reports)
        self.assertTrue(measured["disagreement"])
        self.assertEqual(measured["experts"], 7)

    def test_measurement_carries_no_vote_tally(self):
        measured = moie.measure(self.reports)
        self.assertIsNone(measured.get("vote"), "a tally would be the thing R-SYN-1 forbids")
        self.assertIn("never tallies", str(measured.get("vote_note", "")).lower())

    def test_unique_discoveries_are_carried_per_expert(self):
        measured = moie.measure(self.reports)
        for operator, discoveries in measured["unique"].items():
            self.assertIn(operator, operators.OPERATORS)
            self.assertIsInstance(discoveries, list)


class CompetingHypotheses(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = question()
        self.inversions = AILEngine(self.question).invert()
        self.hypotheses = hypothesis_mod.from_inversions(
            self.inversions, self.question, authority="ops-lead")

    def test_more_than_one_explanation_is_generated(self):
        self.assertGreaterEqual(len(self.hypotheses), 2)

    def test_the_explanations_are_structurally_different(self):
        signatures = {h.signature() for h in self.hypotheses}
        self.assertGreaterEqual(len(signatures), 2,
                                "structurally identical hypotheses are one hypothesis")

    def test_every_structural_field_is_from_the_declared_vocabulary(self):
        for item in self.hypotheses:
            self.assertIn(item.mechanism, MECHANISMS)
            self.assertEqual(len(item.structure()), len(STRUCTURE_FIELDS))

    def test_register_refuses_a_restatement(self):
        from ..control import policy
        from ..core.hypothesis import Hypothesis

        first = self.hypotheses[0]
        restatement = Hypothesis(
            hid="HYP-restatement", text="other words, same explanation", question=first.question,
            mechanism=first.mechanism, locus=first.locus, timescale=first.timescale,
            measurement_assumption=first.measurement_assumption, authority=first.authority)
        with self.assertRaises(policy.Refusal):
            hypothesis_mod.register([first], restatement)

    def test_register_returns_a_new_list_and_never_mutates_the_input(self):
        existing = list(self.hypotheses)
        added = hypothesis_mod.register(existing, self.hypotheses[0])
        self.assertEqual(existing, added)
        self.assertIsNot(existing, added)

    def test_coverage_reports_the_vocabularies_actually_used(self):
        coverage = hypothesis_mod.coverage(self.hypotheses)
        self.assertEqual(coverage["n"], len(self.hypotheses))
        self.assertTrue(coverage["signatures"])

    def test_the_result_is_deterministic(self):
        again = hypothesis_mod.from_inversions(self.inversions, self.question, authority="ops-lead")
        self.assertEqual([h.hid for h in self.hypotheses], [h.hid for h in again])


class DisagreementIsPreserved(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.a = hypothesis("the measurement is wrong", mechanism="MEASUREMENT", locus="TELEMETRY")
        self.b = hypothesis("coordination is the cause", mechanism="COORDINATION", locus="SCHEDULING")

    def test_opposing_evidence_produces_a_disagreement(self):
        # the documented rule: both explanations have usable support AND something
        # usable contradicts one of them. Evidence that merely lacks support for one
        # side is not yet a disagreement -- it is an evidence gap, which is A07.
        found = disagreement_mod.find(
            [self.a, self.b],
            [paper(self.a.hid, supports=True), paper(self.b.hid, supports=True),
             paper(self.a.hid, supports=False)])
        self.assertTrue(found)
        self.assertTrue(all(item.positions for item in found))

    def test_agreement_produces_no_disagreement(self):
        found = disagreement_mod.find(
            [self.a, self.b], [paper(self.a.hid, supports=True), paper(self.b.hid, supports=True)])
        self.assertEqual(found, [])

    def test_a_disagreement_is_preserved_rather_than_resolved(self):
        found = disagreement_mod.find(
            [self.a, self.b],
            [paper(self.a.hid, supports=True), paper(self.b.hid, supports=True),
             paper(self.a.hid, supports=False)])
        for item in disagreement_mod.preserve(found):
            self.assertTrue(item.preserved)
            self.assertIsNone(item.resolved_by)
        self.assertEqual(disagreement_mod.unresolved(found), found)


class SynthesisWithoutAVote(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.a = hypothesis("the measurement is wrong", mechanism="MEASUREMENT", locus="TELEMETRY")
        self.b = hypothesis("coordination is the cause", mechanism="COORDINATION", locus="SCHEDULING")

    def test_a_head_count_cannot_select(self):
        from ..control import policy

        with self.assertRaises(policy.Refusal) as caught:
            synthesis.select([self.a, self.b], [paper(self.a.hid)],
                             holders={self.a.hid: 5, self.b.hid: 1})
        self.assertEqual(caught.exception.rule, "R-SYN-1")

    def test_only_usable_evidence_moves_a_score(self):
        table = synthesis.weigh([self.a, self.b], [paper(self.a.hid, kind="MODEL_PROPOSAL")])
        for row in table:
            self.assertEqual(row["net"], 0.0)
            self.assertEqual(row["usable"], 0)

    def test_strength_beats_count_so_a_minority_can_win(self):
        # A has one STRONG observation (weight 3). B has two WEAK ones (weight 2).
        # A holds the top net with fewer items, so the count-based answer loses.
        evidence = [paper(self.a.hid, strength="STRONG"),
                    paper(self.b.hid, strength="WEAK"), paper(self.b.hid, strength="WEAK")]
        chosen = synthesis.select([self.a, self.b], evidence)
        self.assertEqual(chosen["winner"], self.a.hid)
        self.assertTrue(chosen["minority_wins"])
        self.assertGreater(chosen["margin"], 0)

    def test_no_winner_when_nothing_reaches_the_bar(self):
        chosen = synthesis.select([self.a, self.b], [], minimum_evidence=1)
        self.assertIsNone(chosen["winner"])
        self.assertTrue(chosen["why"])

    def test_the_reason_is_written_down_with_the_numbers(self):
        chosen = synthesis.select([self.a, self.b], [paper(self.a.hid)])
        self.assertIn(self.a.hid, chosen["why"])
        self.assertTrue(chosen["table"])


class Uncertainty(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = question()
        self.a = hypothesis("the measurement is wrong", mechanism="MEASUREMENT", locus="TELEMETRY")

    def test_survey_names_what_would_reduce_each_uncertainty(self):
        found = uncertainty_survey(self.question, hypotheses=[self.a], evidence=[])
        self.assertTrue(found)
        for item in found:
            self.assertTrue(item.reduces_with.strip())
            self.assertTrue(item.kind.strip())

    def test_the_load_is_reported_as_ordinal_and_says_so(self):
        from ..reasoning import uncertainty as uncertainty_mod

        found = uncertainty_survey(self.question, hypotheses=[self.a], evidence=[])
        loaded = uncertainty_load(found)
        self.assertEqual(loaded["n"], len(found))
        self.assertIn("ordinal", loaded)
        # deliberately not an integer and deliberately not a probability: nothing
        # here is calibrated, and reporting one would claim otherwise
        self.assertIsInstance(loaded["ordinal"], float)
        self.assertGreater(loaded["ordinal"], 0.0)
        self.assertLessEqual(loaded["ordinal"], 3.0)
        self.assertIn("ordinal", (uncertainty_mod.__doc__ or "").lower())

    def test_an_empty_survey_loads_as_zero_rather_than_dividing_by_zero(self):
        loaded = uncertainty_load([])
        self.assertEqual(loaded["n"], 0)
        self.assertEqual(loaded["ordinal"], 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
