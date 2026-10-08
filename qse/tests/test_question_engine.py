"""The seven-slot decomposition, ambiguity detection and question mutation."""

from __future__ import annotations

import unittest

from ..core.question import SLOTS, make_question
from ..question_engine import ambiguity as ambiguity_mod
from ..question_engine import decomposer, dependency, question_generator, resolver
from ..question_engine.provenance import lossless, provenance_summary, unprovenanced
from .support import FORTUNE, pin_clock


class AmbiguityDetection(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = make_question(FORTUNE, {"proposition": FORTUNE, "scope": "Fortune 500 companies"})

    def test_every_rule_is_well_formed(self):
        self.assertTrue(ambiguity_mod.RULES)
        for rule in ambiguity_mod.RULES:
            self.assertTrue(rule.id.startswith("AMB-"), rule.id)
            self.assertIn(rule.slot, SLOTS, rule.id)
            self.assertIn(rule.kind, ambiguity_mod.KINDS, rule.id)
            self.assertIn(rule.severity, ambiguity_mod.SEVERITIES, rule.id)
            self.assertTrue(rule.resolving_question.endswith("?"), rule.id)
            self.assertTrue(rule.why.strip(), rule.id)

    def test_an_underspecified_question_yields_blocking_ambiguities(self):
        found = ambiguity_mod.detect(self.question)
        self.assertTrue(any(item.severity == "BLOCKING" for item in found))

    def test_the_undefined_verbs_and_nouns_are_caught(self):
        kinds = {item.kind for item in ambiguity_mod.detect(self.question)}
        self.assertIn("UNDEFINED_TERM", kinds)
        self.assertIn("RELATIVE_TIME", kinds)
        self.assertIn("MISSING_AUTHORITY", kinds)

    def test_the_specific_terms_that_are_undefined_are_named(self):
        terms = {item.term for item in ambiguity_mod.detect(self.question)}
        self.assertIn("bottleneck", terms)
        self.assertIn("predict", terms)
        self.assertIn("before", terms)

    def test_results_are_ordered_with_the_blocking_ones_first(self):
        order = {"BLOCKING": 0, "MATERIAL": 1, "MINOR": 2}
        found = ambiguity_mod.detect(self.question)
        severities = [order[item.severity] for item in found]
        self.assertEqual(severities, sorted(severities))

    def test_every_ambiguity_carries_a_question_that_would_resolve_it(self):
        for item in ambiguity_mod.detect(self.question):
            self.assertTrue(item.resolving_question.strip().endswith("?"))
            self.assertNotIn("'None'", item.resolving_question)

    def test_an_ambiguity_id_is_stable_for_the_same_question(self):
        first = [item.aid for item in ambiguity_mod.detect(self.question)]
        second = [item.aid for item in ambiguity_mod.detect(self.question)]
        self.assertEqual(first, second)

    def test_detection_does_not_mutate_the_question(self):
        before = self.question.to_dict()
        ambiguity_mod.detect(self.question)
        self.assertEqual(before, self.question.to_dict())

    def test_an_answered_slot_does_not_get_its_structural_ambiguity(self):
        answered = make_question(FORTUNE, {"proposition": "p", "scope": "one plant",
                                          "authority": "the VP of operations owns failure"})
        kinds = [item.kind for item in ambiguity_mod.detect(answered)]
        self.assertNotIn("MISSING_AUTHORITY", kinds)


class Decomposition(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_inference_only_fills_a_slot_when_a_named_cue_fired(self):
        slots = decomposer.infer_slots(FORTUNE)
        self.assertTrue(slots["referential"].filled)
        self.assertEqual(slots["referential"].confidence, "INFERRED")
        self.assertTrue(slots["referential"].provenance)
        self.assertFalse(slots["scope"].filled, "a scale illustration is not a scope bound")

    def test_operator_answers_win_over_inference_and_are_marked_stated(self):
        question = decomposer.decompose(FORTUNE, answers={"scope": "one plant, three shifts"})
        self.assertEqual(question.value("scope"), "one plant, three shifts")
        self.assertEqual(question.slots["scope"].confidence, "STATED")
        self.assertEqual(question.slots["scope"].provenance, "operator")

    def test_the_fortune_question_still_blocks_on_scope(self):
        question = decomposer.decompose(FORTUNE)
        self.assertEqual(question.blocking(), ["scope"])
        self.assertIn("referential", question.filled())
        self.assertIn("proposition", question.filled())

    def test_an_unknown_slot_in_answers_is_refused(self):
        with self.assertRaises(ValueError):
            decomposer.decompose(FORTUNE, answers={"vibes": "good"})

    def test_a_blank_answer_is_refused_rather_than_stored(self):
        with self.assertRaises(ValueError):
            decomposer.decompose(FORTUNE, answers={"scope": "   "})

    def test_the_seven_slot_report_has_exactly_the_seven_slots_in_order(self):
        report = decomposer.seven_slot_report(decomposer.decompose(FORTUNE))
        self.assertEqual(list(report), list(SLOTS))
        for name, row in report.items():
            self.assertEqual(set(row), {"slot_question", "value", "confidence", "provenance", "note", "filled"})
            self.assertTrue(row["slot_question"].endswith("?"))

    def test_the_report_marks_what_is_filled_and_what_is_not(self):
        report = decomposer.seven_slot_report(decomposer.decompose(FORTUNE))
        self.assertTrue(report["proposition"]["filled"])
        self.assertFalse(report["consumption"]["filled"])
        self.assertEqual(report["consumption"]["confidence"], "UNRESOLVED")

    def test_revision_links_are_carried_through(self):
        question = decomposer.decompose(FORTUNE, parent="Q-parent", revision_of="Q-parent",
                                        revision_reason="too vague")
        self.assertEqual(question.parent, "Q-parent")
        self.assertEqual(question.revision_of, "Q-parent")
        self.assertEqual(question.revision_reason, "too vague")


class Resolution(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = decomposer.decompose(FORTUNE)

    def test_resolving_makes_a_new_version_of_the_same_question(self):
        after = resolver.resolve(self.question, {"scope": "one plant"}, reason="operator answered AMB")
        self.assertEqual(after.qid, self.question.qid)
        self.assertEqual(after.version, self.question.version + 1)
        self.assertEqual(after.parent, self.question.qid)
        self.assertEqual(after.value("scope"), "one plant")
        self.assertEqual(after.trigger, "operator answered AMB")

    def test_resolving_does_not_mutate_the_original(self):
        before = self.question.to_dict()
        resolver.resolve(self.question, {"scope": "one plant"})
        self.assertEqual(before, self.question.to_dict())

    def test_resolving_an_unknown_slot_is_refused(self):
        with self.assertRaises(ValueError):
            resolver.resolve(self.question, {"nonsense": "x"})

    def test_resolving_with_a_blank_answer_is_refused(self):
        with self.assertRaises(ValueError):
            resolver.resolve(self.question, {"scope": "  "})

    def test_enough_answers_clear_the_blocking_list(self):
        after = resolver.resolve(self.question, {"scope": "one plant, three shifts"})
        self.assertEqual(after.blocking(), [])


class Provenance(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_every_filled_slot_has_a_named_provenance(self):
        question = decomposer.decompose(FORTUNE, answers={"scope": "one plant"})
        self.assertTrue(lossless(question))
        summary = provenance_summary(question)
        self.assertEqual(sorted(summary), ["inferred", "stated", "unresolved"])
        self.assertIn("scope", summary["stated"])
        self.assertIn("referential", summary["inferred"])

    def test_an_unfilled_slot_is_not_treated_as_provenanced(self):
        question = decomposer.decompose(FORTUNE)
        self.assertFalse(unprovenanced(question, "referential"))
        self.assertFalse(unprovenanced(question, "consumption"))


class SlotDependencies(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_the_dependency_table_only_names_real_slots(self):
        for slot, deps in dependency.SLOT_DEPENDENCIES.items():
            self.assertIn(slot, SLOTS)
            for dep in deps:
                self.assertIn(dep, SLOTS)

    def test_the_table_has_no_cycles(self):
        question = decomposer.decompose(FORTUNE)
        self.assertEqual(dependency.cycles(question), [])
        self.assertEqual(dependency.circular(question), [])

    def test_an_unresolved_slot_reports_what_it_waits_on(self):
        question = decomposer.decompose(FORTUNE)
        waiting = dependency.blocked_by(question)
        self.assertIn("authority", waiting)


class QuestionGeneration(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.question = decomposer.decompose(FORTUNE)
        self.found = ambiguity_mod.detect(self.question)

    def test_each_ambiguity_produces_a_candidate_question(self):
        candidates = question_generator.from_ambiguities(self.question, self.found)
        self.assertEqual(len(candidates), len(self.found))
        for item in candidates:
            self.assertEqual(item.parent, self.question.qid)

    def test_candidates_are_ranked_by_first_estimate_gain(self):
        candidates = question_generator.next_questions(self.question, ambiguities=self.found)
        gains = [item.information_gain for item in candidates]
        self.assertEqual(gains, sorted(gains, reverse=True))

    def test_the_first_estimate_is_documented_as_an_estimate(self):
        candidate = question_generator.from_ambiguities(self.question, self.found[:1])[0]
        payload = candidate.to_dict()
        self.assertIn("gain_basis", payload)
        self.assertIn("estimate", str(payload["gain_basis"]).lower())

    def test_the_gain_of_a_blocking_ambiguity_is_the_highest_weight(self):
        blocking = [item for item in self.found if item.severity == "BLOCKING"]
        minor = [item for item in self.found if item.severity == "MINOR"]
        self.assertTrue(blocking)
        top = question_generator.from_ambiguities(self.question, blocking)[0]
        self.assertEqual(top.information_gain, 3.0)
        if minor:
            low = question_generator.from_ambiguities(self.question, minor)[0]
            self.assertLess(low.information_gain, top.information_gain)

    def test_ranking_is_deterministic_and_deduplicated(self):
        first = [item.gid for item in question_generator.next_questions(
            self.question, ambiguities=self.found)]
        second = [item.gid for item in question_generator.next_questions(
            self.question, ambiguities=self.found)]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(
            item.text for item in question_generator.next_questions(
                self.question, ambiguities=self.found))))

    def test_a_knowledge_gap_becomes_a_candidate(self):
        candidates = question_generator.from_gaps(self.question, ["nobody has measured the true wait"])
        self.assertEqual(candidates[0].kind, "KNOWLEDGE_GAP")
        self.assertEqual(candidates[0].information_gain, 1.5)

    def test_a_discriminating_experiment_becomes_a_candidate_weighted_by_what_it_separates(self):
        class FakeExperiment:
            xid = "EXP-1"
            design = "one run, five candidates"
            discriminates = ("H1", "H2", "H3")

        candidates = question_generator.from_discrimination(self.question, [FakeExperiment()])
        self.assertEqual(candidates[0].kind, "DISCRIMINATION")
        self.assertEqual(candidates[0].information_gain, 3)

    def test_no_candidates_is_an_empty_list_rather_than_an_error(self):
        self.assertEqual(question_generator.next_questions(self.question), [])

    def test_mutation_events_can_be_built_from_a_candidate(self):
        from ..ledger import events

        candidate = question_generator.next_questions(self.question, ambiguities=self.found)[0]
        record = events.build("mutation", **candidate.to_dict())
        self.assertEqual(record["gid"], candidate.gid)
        self.assertEqual(record["parent"], self.question.qid)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
