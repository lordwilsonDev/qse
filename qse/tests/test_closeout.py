"""The close-out asked the moonshot's own terminal questions.

These tests care about one thing: that the close-out refuses to upgrade a claim.
The dangerous failure is not a crash -- it is a close-out that reports SUCCESS,
or "independently verified", on evidence that does not carry it.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from .. import cli, closeout as closeout_mod
from ..control.controller import Engine
from ..control.state import State
from ..experiment.runner import Dataset
from ..ledger import chain
from .support import Workspace, pin_clock, scenario_payload


def dataset(payload: dict) -> Dataset:
    return Dataset(name=payload["name"], rows=payload["rows"])


class TheClockIsPinned(unittest.TestCase):
    """Shared base: a pinned clock, a workspace, and a run helper."""

    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        cls.ws = Workspace()
        cls.payload = scenario_payload()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.ws.close()

    @classmethod
    def _run(cls, name: str, *, holdout: bool = True, answers: dict | None = None,
             authority: str = "VP of Operations") -> str:
        ledger = cls.ws.ledger(name)
        frames = [dataset(cls.payload)]
        if holdout:
            frames.append(dataset(scenario_payload("orders_holdout.json")))
        Engine(ledger).run(cls.payload["question"],
                           answers=cls.payload["facts"] if answers is None else answers,
                           datasets=frames, rows=cls.payload["rows"],
                           authority=authority)
        return ledger


class TheFifteenAnswers(TheClockIsPinned):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.ledger = cls._run("closeout.jsonl")
        cls.out = closeout_mod.closeout(cls.ledger)

    def test_all_fifteen_are_answered(self):
        self.assertEqual([r["id"] for r in self.out["answers"]],
                         [f"Q{n}" for n in range(1, 16)])

    def test_every_answer_carries_a_label_from_the_set(self):
        for row in self.out["answers"]:
            self.assertIn(row["label"], closeout_mod.LABELS, row["id"])
            self.assertTrue(row["answer"].strip(), row["id"])

    def test_labels_are_counted_not_averaged(self):
        self.assertEqual(sum(self.out["label_counts"].values()), 15)
        self.assertEqual(set(self.out["label_counts"]), set(closeout_mod.LABELS))

    def test_most_answers_cite_the_records_they_were_read_from(self):
        with_basis = [r for r in self.out["answers"] if r["basis"]]
        self.assertGreaterEqual(len(with_basis), 13,
                                "an answer with no record id cannot be checked")

    def test_the_adversarial_answer_does_not_pass_severity_off_as_probability(self):
        # the question asks which attack has the highest *probability* of exposing a
        # failure; only a severity band is recorded, and the answer must say so
        row = next(r for r in self.out["answers"] if r["id"] == "Q9")
        self.assertIn("cannot answer the question as put", row["answer"])
        self.assertIn("Severity is not probability", row["answer"])

    def test_the_unanswerable_part_of_q9_is_reported_as_unanswerable(self):
        records = chain.load(self.ledger)
        state = State.replay(records)
        part = closeout_mod.q9_highest_probability_attack(state, records)
        self.assertFalse(part["answerable"])
        self.assertIsNone(part["kind"])
        self.assertIn("without inventing a number", part["reason"])

    def test_the_referential_answer_names_the_terms_the_rules_questioned(self):
        row = next(r for r in self.out["answers"] if r["id"] == "Q1")
        self.assertEqual(row["label"], "PROVEN")
        self.assertIn("millions", row["answer"])
        self.assertTrue(all(b.startswith("AMB-") for b in row["basis"]),
                        "an ambiguity must be cited by its own id, not its question's")


class TheIndependenceRefusal(TheClockIsPinned):
    """Q10 is the load-bearing one: a name is not an independent path."""

    def test_a_verification_strung_from_two_names_is_still_unknown(self):
        out = closeout_mod.closeout(self._run("indep.jsonl"))
        row = next(r for r in out["answers"] if r["id"] == "Q10")
        self.assertEqual(row["label"], "UNKNOWN")
        self.assertIn("NOT established", row["answer"])
        self.assertIn("must not be represented as independently verified", row["answer"])

    def test_no_verification_at_all_is_also_unknown_and_says_so(self):
        out = closeout_mod.closeout(self._run("nover.jsonl", holdout=False))
        row = next(r for r in out["answers"] if r["id"] == "Q10")
        self.assertEqual(row["label"], "UNKNOWN")
        self.assertIn("No independent verification was performed", row["answer"])

    def test_the_refusal_is_what_keeps_success_unreachable(self):
        out = closeout_mod.closeout(self._run("succ.jsonl"))
        self.assertFalse(out["terminal"]["conditions"]["SUCCESS"]["holds"])
        self.assertIn("independence is not established",
                      out["terminal"]["conditions"]["SUCCESS"]["why"])


class TheTerminalCondition(TheClockIsPinned):
    def test_the_shipped_run_does_not_reach_success(self):
        out = closeout_mod.closeout(self._run("term.jsonl"))
        self.assertNotEqual(out["terminal"]["state"], "SUCCESS")

    def test_a_rejected_artifact_is_refuted_not_converted_into_a_pass(self):
        # nobody named as having the standing to be wrong, and no authority in the
        # brief, so attack_authority lands and the artifact must not read as live
        answers = {k: v for k, v in self.payload["facts"].items() if k != "authority"}
        out = closeout_mod.closeout(
            self._run("rejected.jsonl", answers=answers, authority=""))
        row = next(r for r in out["answers"] if r["id"] == "Q8")
        self.assertEqual(row["label"], "REFUTED")
        self.assertIn("REJECTED", row["answer"])
        self.assertFalse(out["terminal"]["conditions"]["SUCCESS"]["holds"])

    def test_the_same_run_with_an_authority_is_not_refuted(self):
        # the pair is the point: the refusal turns on the authority, not on noise
        out = closeout_mod.closeout(self._run("authorised.jsonl"))
        row = next(r for r in out["answers"] if r["id"] == "Q8")
        self.assertEqual(row["label"], "PROVEN")

    def test_no_state_is_silently_converted_into_another(self):
        out = closeout_mod.closeout(self._run("conv.jsonl"))
        term = out["terminal"]
        self.assertIn(term["state"], closeout_mod.TERMINALS + ("UNRESOLVED",))
        for name in term["also_hold"]:
            self.assertTrue(term["conditions"][name]["holds"],
                            "a reported condition must actually hold")
        self.assertEqual(term["precedence"], list(closeout_mod.TERMINALS))

    def test_a_run_with_no_real_world_outcome_cannot_be_success(self):
        out = closeout_mod.closeout(self._run("norw.jsonl"))
        why = out["terminal"]["conditions"]["SUCCESS"]["why"]
        self.assertIn("real-world outcome", why)

    def test_the_question_is_reported_replaced_when_a_mutation_exists(self):
        out = closeout_mod.closeout(self._run("mut.jsonl"))
        self.assertTrue(out["terminal"]["conditions"]["QUESTION_REPLACED"]["holds"])

    def test_an_unrunnable_test_alone_does_not_block_a_supported_artifact(self):
        # a planned test that cannot fire is a planning defect (Q14), not proof
        # that required evidence was unobtainable, so BLOCKED must not hold
        out = closeout_mod.closeout(self._run("blocked.jsonl"))
        self.assertFalse(out["terminal"]["conditions"]["BLOCKED"]["holds"])
        row = next(r for r in out["answers"] if r["id"] == "Q14")
        self.assertIn("could never run", row["answer"])


class TheOutcomeAndAuthority(TheClockIsPinned):
    def test_an_outcome_that_is_not_real_keeps_the_claim_untested(self):
        out = closeout_mod.closeout(self._run("out.jsonl"))
        row = next(r for r in out["answers"] if r["id"] == "Q13")
        self.assertEqual(row["label"], "UNTESTED")
        self.assertIn("benefit is unknown", row["answer"])

    def test_the_tempting_claim_is_named_as_unsupported(self):
        out = closeout_mod.closeout(self._run("auth.jsonl"))
        row = next(r for r in out["answers"] if r["id"] == "Q15")
        self.assertIn("tempting but unsupported", row["answer"])
        self.assertIn("no real-world outcome", row["answer"])

    def test_self_critique_names_the_gaps_this_ledger_cannot_answer(self):
        out = closeout_mod.closeout(self._run("crit.jsonl"))
        row = next(r for r in out["answers"] if r["id"] == "Q14")
        self.assertIn("cost, adoption and feasibility were not modelled", row["answer"])
        self.assertIn("could never run", row["answer"])


class TheNextQuestion(TheClockIsPinned):
    def test_it_is_ranked_and_carries_the_five_factors(self):
        out = closeout_mod.closeout(self._run("next.jsonl"))
        nq = out["next_question"]
        self.assertIsNotNone(nq["chosen"])
        self.assertIn("testability", nq["factors"])
        self.assertIn("evidence availability", nq["factors"])
        scores = [c["score"] for c in nq["ranked"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_it_says_what_would_make_it_unnecessary(self):
        out = closeout_mod.closeout(self._run("unnecessary.jsonl"))
        text = out["next_question"]["would_make_it_unnecessary"]
        self.assertIn("Nothing else makes it unnecessary", text)

    def test_the_ranking_is_declared_ordinal(self):
        out = closeout_mod.closeout(self._run("ordinal.jsonl"))
        self.assertIn("not a probability", out["next_question"]["scale_note"])


class TheVerdicts(TheClockIsPinned):
    def _cli(self, argv: list[str]) -> int:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        out.close()
        err.close()
        return code

    def test_a_run_that_did_not_succeed_exits_non_zero(self):
        ledger = self._run("verdict.jsonl")
        self.assertEqual(self._cli(["closeout", "--ledger", ledger]), 1)

    def test_a_missing_ledger_is_unusable_input(self):
        self.assertEqual(
            self._cli(["closeout", "--ledger", self.ws.file("nope.jsonl").as_posix()]), 2)

    def test_json_output_is_the_whole_closeout(self):
        ledger = self._run("json.jsonl")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            cli.main(["--json", "closeout", "--ledger", ledger])
        payload = json.loads(out.getvalue())
        out.close()
        err.close()
        self.assertEqual(len(payload["answers"]), 15)
        self.assertIn(payload["terminal"]["state"], closeout_mod.TERMINALS)
        self.assertIn("next_question", payload)


class TheEmptyLedger(unittest.TestCase):
    """Nothing to read must not read as everything being fine."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.ledger = self.ws.ledger("empty.jsonl")
        chain.append(self.ledger, {"ev": "note", "ts": "2026-10-07T00:00:00Z"})

    def tearDown(self) -> None:
        self.ws.close()

    def test_every_answer_admits_it_has_nothing(self):
        out = closeout_mod.closeout(self.ledger)
        for row in out["answers"]:
            self.assertNotIn(row["label"], ("PROVEN", "SUPPORTED"),
                             f"{row['id']} claimed {row['label']} with no records")
        self.assertEqual(out["label_counts"]["PROVEN"], 0)
        self.assertEqual(out["label_counts"]["SUPPORTED"], 0)

    def test_it_does_not_reach_success(self):
        out = closeout_mod.closeout(self.ledger)
        self.assertNotEqual(out["terminal"]["state"], "SUCCESS")

    def test_a_tampered_ledger_is_refused_rather_than_read(self):
        # a non-final line, because the chain structurally cannot vouch for the last
        # one (docs/LIMITS.md) -- tampering the tail would prove nothing
        chain.append(self.ledger, {"ev": "note", "ts": "2026-10-07T00:00:01Z"})
        lines = chain.read_lines(self.ledger)
        lines[0] = lines[0].replace("note", "nout", 1)
        bad = self.ws.file("tampered.jsonl")
        bad.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(chain.LedgerCorrupt):
            closeout_mod.closeout(str(bad))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
