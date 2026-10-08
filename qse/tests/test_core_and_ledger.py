"""The core invariant and the ledger.

The invariant is the whole point: Answer != Hypothesis != Evidence != Artifact !=
Verified Artifact != Real-world Outcome. If any of these can be silently used as
another, QSE is a very confident pipeline, so each confusion is tested directly.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from ..control import policy
from ..core.artifact import make_artifact
from ..core.assumption import make_assumption
from ..core.evidence import make_evidence
from ..core.experiment import Experiment, make_experiment
from ..core.hypothesis import make_hypothesis
from ..core.outcome import make_outcome
from ..core.proposition import parse_proposition
from ..core.question import SLOTS, make_question
from ..ids import freeze
from ..ledger import chain, events, receipts
from .support import Workspace, pin_clock


def hypothesis(hid_text: str = "coordination", **over):
    fields = dict(
        question="Q-1", mechanism="COORDINATION", locus="SCHEDULING", timescale="HOURS",
        measurement_assumption="the recorded timestamps are correct", authority="ops-lead",
    )
    fields.update(over)
    return make_hypothesis(hid_text, **fields)


class LedgerChain(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.ledger = self.ws.ledger()
        for index in range(3):
            chain.append(self.ledger, {"ev": "hypothesis", "hid": f"H{index}", "text": f"h{index}",
                                       "question": "Q-1", "mechanism": "COORDINATION",
                                       "locus": "SCHEDULING", "timescale": "HOURS",
                                       "measurement_assumption": "ok", "authority": "ops"})

    def tearDown(self) -> None:
        self.ws.close()

    def test_a_fresh_ledger_chains_from_genesis(self):
        lines = chain.read_lines(self.ledger)
        first = json.loads(lines[0])
        self.assertEqual(first["prev"], chain.GENESIS)
        self.assertEqual(first["seq"], 1)
        self.assertEqual(len(chain.GENESIS), 64)

    def test_each_line_commits_to_the_exact_previous_line(self):
        lines = chain.read_lines(self.ledger)
        self.assertEqual(chain.line_sha(lines[0]), json.loads(lines[1])["prev"])
        self.assertEqual(chain.line_sha(lines[1]), json.loads(lines[2])["prev"])

    def test_an_intact_chain_verifies(self):
        count, bad, reason = chain.verify_chain(chain.read_lines(self.ledger))
        self.assertEqual((count, bad), (3, None))
        self.assertIn("intact", reason)

    def test_editing_a_middle_line_is_detected_at_the_next_link(self):
        lines = chain.read_lines(self.ledger)
        lines[1] = lines[1].replace("h1", "h9")
        count, bad, reason = chain.verify_chain(lines)
        # the edit is on line 2, and the FIRST break shows up on line 3, because
        # line 3 is the first line whose prev disagrees with what it points at
        self.assertEqual(bad, 3)
        self.assertIn("chain broken", reason)

    def test_deleting_a_line_is_detected_by_sequence(self):
        lines = chain.read_lines(self.ledger)
        del lines[1]
        count, bad, reason = chain.verify_chain(lines)
        self.assertEqual(bad, 2)
        self.assertIn("seq", reason)

    def test_swapping_two_lines_is_detected(self):
        lines = chain.read_lines(self.ledger)
        lines[0], lines[1] = lines[1], lines[0]
        _, bad, _ = chain.verify_chain(lines)
        self.assertEqual(bad, 1)

    def test_a_broken_ledger_is_refused_rather_than_read(self):
        path = self.ws.ledger("broken.jsonl")
        path_obj = self.ws.file("broken.jsonl")
        path_obj.write_text('{"ev":"hypothesis","seq":1,"prev":"nope"}\n', encoding="utf-8")
        with self.assertRaises(chain.LedgerCorrupt):
            chain.load(path)

    def test_a_broken_ledger_is_not_extended(self):
        path_obj = self.ws.file("tampered.jsonl")
        text = self.ws.file("ledger.jsonl").read_text(encoding="utf-8")
        path_obj.write_text(text.replace("h1", "h9"), encoding="utf-8")
        with self.assertRaises(chain.LedgerCorrupt):
            chain.append(str(path_obj), {"ev": "hypothesis", "hid": "H9"})
        self.assertEqual(path_obj.read_text(encoding="utf-8"), text.replace("h1", "h9"))

    def test_the_tail_hash_is_published_because_the_last_line_is_uncovered(self):
        lines = chain.read_lines(self.ledger)
        self.assertEqual(chain.tail(self.ledger), chain.line_sha(lines[-1]))
        # structural limit: editing the LAST line cannot be caught by a chain that
        # only links backwards. Recording it here so the limit stays visible.
        lines[-1] = lines[-1].replace("h2", "h9")
        _, bad, _ = chain.verify_chain(lines)
        self.assertIsNone(bad)

    def test_an_empty_ledger_has_no_tail(self):
        self.assertIsNone(chain.tail(self.ws.ledger("absent.jsonl")))

    def test_blank_lines_are_not_mistaken_for_corruption(self):
        path_obj = self.ws.file("blank.jsonl")
        path_obj.write_text(
            self.ws.file("ledger.jsonl").read_text(encoding="utf-8") + "\n\n", encoding="utf-8"
        )
        count, bad, _ = chain.verify_chain(chain.read_lines(str(path_obj)))
        self.assertEqual((count, bad), (3, None))


class EventSchema(unittest.TestCase):
    def test_every_declared_event_type_can_be_built(self):
        builders = {
            "question": dict(qid="Q", version=1, raw="r", slots={}),
            "ambiguity": dict(aid="A", qid="Q", slot="scope", term="t", kind="UNDEFINED_TERM",
                              severity="BLOCKING", resolving_question="?"),
            "assumption": dict(aid="A", text="t", source="s", load_bearing=False),
            "inversion": dict(iid="I", operator="axiom_inverter", target_axiom="A",
                              statement="s", consequence={"observation": "o"}),
            "expert": dict(operator="axiom_inverter", question="Q", unique_discoveries=[],
                           contradictions=[], blind_spots=[]),
            "hypothesis": dict(hid="H", text="t", question="Q", mechanism="CAPACITY",
                               locus="STAFFING", timescale="DAYS",
                               measurement_assumption="m", authority="a"),
            "experiment": dict(xid="X", hypothesis="H", question="Q", design="d", refuted_by="r"),
            "evidence": dict(eid="E", hypothesis="H", claim="c", kind="MEASURED",
                             source="s", method="m"),
            "artifact": dict(aid="A", hypothesis="H", kind="CODE", title="t", builder="b"),
            "attack": dict(atid="T", artifact="A", kind="attack_scope", severity="SERIOUS",
                           survives=False),
            "verification": dict(vid="V", artifact="A", builder="b", verifier="v",
                                 independent=True, ok=True),
            "mutation": dict(gid="G", parent="Q", text="t", kind="AMBIGUITY", trigger="why"),
            "outcome": dict(oid="O", artifact="A", kind="NO_OUTCOME", real_world=False),
            "decision": dict(did="D", kind="SYNTHESIS", subject="Q", chosen="c", why="w"),
        }
        self.assertEqual(set(builders), set(events.EVENT_TYPES))
        for name, fields in builders.items():
            with self.subTest(event=name):
                record = events.build(name, **fields)
                self.assertEqual(record["ev"], name)
                self.assertIn("ts", record)

    def test_a_missing_required_field_is_refused(self):
        with self.assertRaises(events.EventError) as caught:
            events.build("hypothesis", hid="H", text="t")
        self.assertIn("question", str(caught.exception))

    def test_an_unknown_event_type_is_refused(self):
        with self.assertRaises(events.EventError):
            events.build("vibes", hid="H")

    def test_a_none_valued_required_field_is_refused(self):
        with self.assertRaises(events.EventError):
            events.check({"ev": "outcome", "oid": None, "artifact": "A", "kind": "NO_OUTCOME",
                          "real_world": False})


class WhyReconstruction(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.records = [
            {"ev": "question", "seq": 1, "qid": "Q-root", "version": 1, "raw": "predict?",
             "slots": {}, "trigger": "operator request", "revision_of": None},
            {"ev": "mutation", "seq": 2, "gid": "G-1", "parent": "Q-root", "text": "what is a bottleneck?",
             "kind": "AMBIGUITY", "trigger": "BLOCKING UNDEFINED_TERM on 'bottleneck'", "produced": None},
            {"ev": "question", "seq": 3, "qid": "Q-child", "version": 1, "raw": "what is a bottleneck?",
             "slots": {}, "trigger": "BLOCKING UNDEFINED_TERM", "revision_of": "Q-root"},
        ]

    def tearDown(self) -> None:
        self.ws.close()

    def test_it_walks_back_to_the_root_and_reports_the_trigger(self):
        answer = receipts.why(self.records, "Q-child")
        self.assertTrue(answer["found"])
        self.assertTrue(answer["complete"])
        self.assertEqual(answer["root"], "Q-root")
        self.assertEqual([step["qid"] for step in answer["chain"]], ["Q-root", "Q-child"])
        self.assertEqual(answer["chain"][1]["trigger"], "BLOCKING UNDEFINED_TERM")

    def test_a_root_question_is_its_own_chain(self):
        answer = receipts.why(self.records, "Q-root")
        self.assertEqual(answer["root"], "Q-root")
        self.assertTrue(answer["complete"])

    def test_a_question_missing_from_the_ledger_is_reported_not_guessed(self):
        answer = receipts.why(self.records, "Q-absent")
        self.assertFalse(answer["found"])
        self.assertIn("no question event", answer["reason"])

    def test_a_missing_parent_makes_the_chain_incomplete_rather_than_short(self):
        records = self.records + [
            {"ev": "question", "seq": 4, "qid": "Q-orphan", "version": 1, "raw": "x",
             "slots": {}, "revision_of": "Q-nowhere"},
        ]
        answer = receipts.why(records, "Q-orphan")
        self.assertFalse(answer["complete"])
        self.assertTrue(any("absent from the ledger" in str(step.get("note", "")) for step in answer["chain"]))

    def test_a_cycle_is_detected_rather_than_looped(self):
        records = [
            {"ev": "question", "qid": "A", "version": 1, "raw": "a", "slots": {}, "revision_of": "B"},
            {"ev": "question", "qid": "B", "version": 1, "raw": "b", "slots": {}, "revision_of": "A"},
        ]
        answer = receipts.why(records, "A")
        self.assertFalse(answer["complete"])

    def test_referenced_by_finds_every_naming(self):
        hits = receipts.referenced_by(self.records, "Q-root")
        self.assertEqual({hit["ev"] for hit in hits}, {"question", "mutation"})


class TheInvariantBetweenTheTypes(unittest.TestCase):
    """Each of these is a way one type could masquerade as another. None may pass."""

    def test_a_model_proposal_is_evidence_but_never_usable_evidence(self):
        item = make_evidence("latency is the cause", hypothesis="H", kind="MODEL_PROPOSAL",
                             source="qse-llm", method="sampling", collected_at="2026-10-07T00:00:00Z")
        self.assertFalse(item.usable())
        self.assertEqual(item.weight(), 0.0)
        self.assertIn("MODEL_PROPOSAL", item.why_unusable())

    def test_evidence_without_a_source_is_not_usable(self):
        item = make_evidence("c", hypothesis="H", kind="MEASURED", source="", method="pearson",
                             collected_at="2026-10-07T00:00:00Z", strength="STRONG")
        self.assertFalse(item.usable())
        self.assertEqual(item.weight(), 0.0)
        self.assertIn("provenanced", item.why_unusable())

    def test_a_contradictory_observation_is_still_usable_evidence(self):
        item = make_evidence("c", hypothesis="H", kind="MEASURED", source="orders.csv",
                             method="pearson", collected_at="2026-10-07T00:00:00Z", supports=False)
        self.assertTrue(item.usable(), "throwing away disagreeing evidence is how a run lies to itself")

    def test_an_experiment_that_cannot_be_refuted_cannot_be_constructed(self):
        with self.assertRaises(ValueError) as caught:
            Experiment(xid="X", hypothesis="H", question="Q", design="look at it",
                       prediction_if_true="a", prediction_if_false="b", refuted_by="")
        self.assertIn("refute", str(caught.exception))

    def test_a_hypothesis_must_say_what_it_assumes_about_measurement(self):
        with self.assertRaises(ValueError):
            hypothesis("x", mechanism="MEASUREMENT", measurement_assumption="")

    def test_a_hypothesis_must_name_who_may_call_it_wrong(self):
        with self.assertRaises(ValueError):
            hypothesis("x", authority="")

    def test_a_load_bearing_assumption_needs_a_testable_consequence(self):
        with self.assertRaises(ValueError):
            make_assumption("the clocks agree", source="axiom", load_bearing=True)
        ok = make_assumption("the clocks agree", source="axiom", load_bearing=True,
                             testable_consequence="compare two independent clocks")
        self.assertTrue(ok.testable())

    def test_an_unknown_vocabulary_word_is_refused(self):
        with self.assertRaises(ValueError):
            hypothesis("x", mechanism="VIBES")
        with self.assertRaises(ValueError):
            hypothesis("x", locus="THE_MOON")
        with self.assertRaises(ValueError):
            hypothesis("x", timescale="FOREVER")

    def test_an_outcome_needs_evidence_unless_it_is_no_outcome(self):
        with self.assertRaises(ValueError):
            make_outcome(artifact="A", kind="MEASURED_CHANGE")
        make_outcome(artifact="A", kind="NO_OUTCOME")

    def test_a_real_world_outcome_cannot_be_an_absence(self):
        with self.assertRaises(ValueError):
            make_outcome(artifact="A", kind="NO_OUTCOME", real_world=True)

    def test_an_artifact_cannot_be_verified_just_by_being_declared(self):
        art = make_artifact(hypothesis="H", kind="DECISION_RULE", title="t", builder="b")
        self.assertFalse(art.verified())
        self.assertFalse(art.attacked())
        art.state = "VERIFIED"
        self.assertFalse(art.verified(), "VERIFIED with no verification id is not verified")

    def test_outcome_delta_is_none_when_the_numbers_are_not_there(self):
        self.assertIsNone(make_outcome(artifact="A", kind="NO_OUTCOME").delta())
        self.assertEqual(make_outcome(artifact="A", kind="NO_OUTCOME", before=10, after=4).delta(), -6.0)


class PropositionParsing(unittest.TestCase):
    def test_prediction_is_told_apart_from_detection(self):
        self.assertEqual(parse_proposition("Can we predict bottlenecks?").modality, "PREDICTABLE")
        self.assertEqual(parse_proposition("Can we detect bottlenecks early?").modality, "DETECTABLE")

    def test_a_causal_reframing_is_a_different_modality(self):
        # note: "precursor" is itself a prediction cue, so the causal phrasing here
        # deliberately avoids it -- otherwise this would be testing the cue table
        # rather than the distinction the cue table exists to draw.
        before = parse_proposition("Can we predict operational bottlenecks?")
        after = parse_proposition("Does acting on the signal reduce failure probability?")
        self.assertEqual(before.modality, "PREDICTABLE")
        self.assertEqual(after.modality, "CAUSAL")
        self.assertTrue(before.modality_changed(after))

    def test_an_absence_claim_is_marked(self):
        self.assertTrue(parse_proposition("There is no evidence that staffing matters.").absence)
        self.assertFalse(parse_proposition("Staffing is the largest driver.").absence)

    def test_the_cues_that_fired_are_recorded(self):
        self.assertIn("predict", parse_proposition("Can we predict bottlenecks?").cues)

    def test_empty_text_is_refused(self):
        with self.assertRaises(ValueError):
            parse_proposition("   ")


class TheSevenSlots(unittest.TestCase):
    def test_a_partial_question_leaves_the_rest_unresolved_rather_than_guessed(self):
        question = make_question("Can we predict bottlenecks?", {"proposition": "p", "scope": "s"})
        self.assertEqual(len(SLOTS), 7)
        self.assertEqual(sorted(question.filled()), ["proposition", "scope"])
        self.assertIn("authority", question.unresolved())

    def test_a_question_missing_a_slot_is_refused_at_construction(self):
        from ..core.question import Question

        with self.assertRaises(ValueError) as caught:
            Question(qid="Q", version=1, raw="x", slots={"proposition": "p"})
        self.assertIn("seven slots", str(caught.exception))

    def test_the_blocking_slots_are_the_ones_an_investigation_cannot_start_without(self):
        question = make_question("Can we predict bottlenecks?", {"referential": "r"})
        self.assertEqual(question.blocking(), ["proposition", "scope"])

    def test_the_fingerprint_ignores_bookkeeping_and_follows_content(self):
        a = make_question("q", {"scope": "s"}, version=1)
        b = make_question("q", {"scope": "s"}, version=7)
        c = make_question("q", {"scope": "different"}, version=1)
        self.assertEqual(a.fingerprint(), b.fingerprint())
        self.assertNotEqual(a.fingerprint(), c.fingerprint())

    def test_an_empty_question_is_refused(self):
        with self.assertRaises(ValueError):
            make_question("  ", {})


class PolicyRefusals(unittest.TestCase):
    def test_every_rule_id_is_unique_and_described(self):
        self.assertEqual(len(policy.RULES), len(set(policy.RULES)))
        for rule, text in policy.RULES.items():
            self.assertTrue(rule.startswith("R-"), rule)
            self.assertTrue(text.strip(), rule)

    def test_an_unknown_rule_id_cannot_be_raised(self):
        with self.assertRaises(KeyError):
            policy.Refusal("R-NOPE", "x")

    def test_a_refusal_carries_its_rule_id_in_its_message(self):
        with self.assertRaises(policy.Refusal) as caught:
            policy.require_independent("Builder-A", "builder-a")
        self.assertEqual(caught.exception.rule, "R-VER-1")
        self.assertIn("R-VER-1", str(caught.exception))

    def test_the_builder_cannot_verify_its_own_work_even_with_different_capitalisation(self):
        with self.assertRaises(policy.Refusal):
            policy.require_independent("QSE Builder", "qse builder")

    def test_an_unnamed_verifier_is_refused(self):
        with self.assertRaises(policy.Refusal):
            policy.require_independent("b", "   ")

    def test_an_unattacked_artifact_cannot_be_verified(self):
        art = make_artifact(hypothesis="H", kind="CODE", title="t", builder="b")
        art.state = "CONSTRUCTED"
        with self.assertRaises(policy.Refusal) as caught:
            policy.require_attacked(art)
        self.assertEqual(caught.exception.rule, "R-VER-2")

    def test_an_unreproduced_artifact_cannot_be_verified(self):
        with self.assertRaises(policy.Refusal) as caught:
            policy.require_reproduced([])
        self.assertEqual(caught.exception.rule, "R-VER-3")

    def test_a_head_count_cannot_select_a_hypothesis(self):
        with self.assertRaises(policy.Refusal) as caught:
            policy.forbid_majority_vote({"H1": 5, "H2": 1}, 6)
        self.assertEqual(caught.exception.rule, "R-SYN-1")

    def test_a_question_with_an_unresolved_blocking_slot_cannot_be_consumed(self):
        question = make_question("predict?", {"scope": "s"})
        with self.assertRaises(policy.Refusal) as caught:
            policy.require_scope(question)
        self.assertEqual(caught.exception.rule, "R-QUE-1")

    def test_two_hypotheses_that_are_the_same_explanation_are_refused(self):
        from ..core.hypothesis import Hypothesis

        first = hypothesis("a")
        # same five structural fields, different prose and a hand-made id, so the
        # only thing that could distinguish them is the structure -- which is the
        # point: differing sentences are not a difference
        second = Hypothesis(
            hid="HYP-hand-made", text="different prose entirely", question=first.question,
            mechanism=first.mechanism, locus=first.locus, timescale=first.timescale,
            measurement_assumption=first.measurement_assumption, authority=first.authority,
        )
        self.assertNotEqual(first.hid, second.hid)
        self.assertEqual(first.distance(second), 0)
        with self.assertRaises(policy.Refusal) as caught:
            policy.require_distinct(second, [first])
        self.assertEqual(caught.exception.rule, "R-HYP-1")

    def test_a_hypothesis_id_names_the_explanation_not_the_sentence(self):
        # The id is derived from question + the five structural fields, and NOT from
        # the prose. Two differently-worded statements of one explanation therefore
        # share an id and cannot both be registered -- R-HYP-1 expressed structurally,
        # rather than left to a comparison somebody could forget to call.
        self.assertEqual(hypothesis("a").hid, hypothesis("a").hid)
        self.assertEqual(hypothesis("a").hid, hypothesis("completely different words").hid)
        self.assertNotEqual(hypothesis("a").hid, hypothesis("a", locus="SOFTWARE").hid)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
