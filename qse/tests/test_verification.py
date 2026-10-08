"""The adversarial layer and the independent gate.

Verification is the difference between QSE and a system that congratulates
itself, so both directions are tested: the gate must reach VERIFIED when the
evidence really does support the artifact, and it must refuse for each specific
reason when it does not.
"""

from __future__ import annotations

import unittest

from ..build import generator, specification
from ..core.artifact import make_artifact
from ..core.hypothesis import make_hypothesis
from ..experiment import results as result_mod
from ..ids import iso, utcnow
from ..control import policy
from ..verification import adversary, evidence as evidence_mod, provenance, reproducibility
from ..verification import verifier as verifier_mod
from ..verification.verifier import explain, gate
from .support import pin_clock, rows_of, strong_evidence


def hypothesis(**over):
    fields = dict(question="Q-1", mechanism="COORDINATION", locus="SCHEDULING", timescale="HOURS",
                  measurement_assumption="the timestamps are correct", authority="VP of Operations")
    fields.update(over)
    return make_hypothesis("coordination across shifts drives the breach rate", **fields)


def artifact(**over):
    fields = dict(hypothesis="HYP-1", kind="DECISION_RULE", title="escalate on the precursor",
                  builder="qse-builder", content="print('{}')", reproduce="python3 rule.py rows.json")
    fields.update(over)
    return make_artifact(**fields)


def reproduction(ok=True, ran=True):
    return reproducibility.Reproduction(
        rid="REP-1", artifact="ART-1", command="python3 rule.py rows.json", ran=ran, ok=ok,
        observed_hash="a" * 16, expected_hash="a" * 16, detail="twice, identical")


class Provenance(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.h = hypothesis()

    def test_a_fully_provenanced_observation_is_complete(self):
        self.assertTrue(provenance.complete(strong_evidence(self.h.hid)))

    def test_a_missing_method_is_reported_field_by_field(self):
        from ..core.evidence import make_evidence

        item = make_evidence("c", hypothesis=self.h.hid, kind="MEASURED", source="orders.csv",
                             method="", collected_at="2026-10-07T12:00:00Z")
        self.assertEqual(provenance.missing(item), ["method"])
        self.assertFalse(provenance.complete(item))

    def test_the_audit_separates_complete_from_usable(self):
        from ..core.evidence import make_evidence

        good = strong_evidence(self.h.hid)
        proposal = make_evidence("c", hypothesis=self.h.hid, kind="MODEL_PROPOSAL",
                                 source="llm", method="sampling", collected_at="2026-10-07T12:00:00Z")
        report = provenance.audit([good, proposal])
        self.assertEqual(report["complete"], [good.eid, proposal.eid])
        self.assertEqual(report["usable"], [good.eid])
        self.assertIn(proposal.eid, report["unusable"])

    def test_the_trace_names_where_a_number_came_from(self):
        trace = provenance.trace(strong_evidence(self.h.hid))
        self.assertEqual(trace["source"], "orders.csv")
        self.assertTrue(trace["method"])


class Sufficiency(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.a = hypothesis()
        self.b = hypothesis(mechanism="MEASUREMENT", locus="TELEMETRY")

    def test_an_unsupported_hypothesis_is_named_rather_than_omitted(self):
        report = evidence_mod.sufficiency([self.a, self.b], [strong_evidence(self.a.hid)])
        self.assertTrue(report[self.a.hid]["sufficient"])
        self.assertFalse(report[self.b.hid]["sufficient"])
        self.assertEqual(evidence_mod.unsupported([self.a, self.b], [strong_evidence(self.a.hid)]),
                         [self.b.hid])

    def test_unusable_evidence_is_counted_and_contributes_no_weight(self):
        from .support import model_proposal

        report = evidence_mod.sufficiency([self.a], [model_proposal(self.a.hid)])
        self.assertEqual(report[self.a.hid]["usable"], 0)
        self.assertEqual(report[self.a.hid]["unusable"], 1)
        self.assertEqual(report[self.a.hid]["weight"], 0.0)

    def test_evidence_in_both_directions_marks_a_hypothesis_contested(self):
        both = [strong_evidence(self.a.hid, supports=True), strong_evidence(self.a.hid, supports=False)]
        self.assertIn(self.a.hid, [row["hid"] for row in evidence_mod.contested(both)])


class Reproducibility(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.art = artifact()

    @staticmethod
    def runner(stdout="same output"):
        def run(_artifact):
            return {"ran": True, "ok": True, "stdout": stdout, "exit": 0}
        return run

    def test_the_first_run_establishes_the_reference_and_says_it_is_weaker(self):
        first = reproducibility.check(self.art, execute=self.runner())
        self.assertTrue(first.ran)
        self.assertTrue(first.ok)
        self.assertIn("first run", first.detail)

    def test_two_identical_runs_are_a_reproduction(self):
        first = reproducibility.check(self.art, execute=self.runner())
        second = reproducibility.check(
            self.art, execute=self.runner(),
            expected_hash=reproducibility.content_hash(self.art),
            expected_output_hash=first.observed_hash)
        self.assertTrue(second.ok)
        self.assertIn("identical output", second.detail)

    def test_the_same_source_that_produces_different_output_does_not_reproduce(self):
        first = reproducibility.check(self.art, execute=self.runner())
        second = reproducibility.check(
            self.art, execute=self.runner("something else entirely"),
            expected_hash=reproducibility.content_hash(self.art),
            expected_output_hash=first.observed_hash)
        self.assertTrue(second.ran)
        self.assertFalse(second.ok, "running twice is not reproducing twice")
        self.assertIn("does not reproduce", second.detail)

    def test_bytes_that_changed_are_not_covered_by_the_earlier_run(self):
        stale = reproducibility.check(self.art, execute=self.runner(), expected_hash="0" * 64)
        self.assertFalse(stale.ran)
        self.assertIn("changed since it was verified", stale.detail)

    def test_an_artifact_that_never_ran_is_not_reported_as_ok(self):
        result = reproducibility.check(
            self.art, execute=lambda _a: {"ran": False, "reason": "no interpreter"})
        self.assertFalse(result.ran)
        self.assertFalse(result.ok)
        self.assertIn("no interpreter", result.detail)

    def test_the_rate_is_unknown_when_nothing_ran(self):
        self.assertIsNone(reproducibility.record([])["rate"])

    def test_the_rate_is_over_clean_runs_only(self):
        summary = reproducibility.record([reproduction(ok=True), reproduction(ok=False)])
        self.assertEqual(summary["rate"], 0.5)
        self.assertEqual(len(summary["reproduced"]), 1)


class TheSevenAttacks(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.h = hypothesis()
        self.art = artifact(hypothesis=self.h.hid)
        self.art.state = "CONSTRUCTED"

    def test_all_seven_attacks_are_run_in_catalogue_order(self):
        attacks = adversary.attack(self.art, hypothesis=self.h)
        self.assertEqual([a.kind for a in attacks], list(adversary.catalogue()))
        self.assertEqual(len(attacks), 7)

    def test_every_attack_says_what_would_repair_it(self):
        for item in adversary.attack(self.art, hypothesis=self.h):
            self.assertTrue(item.response.strip(), item.kind)
            self.assertIn(item.severity, adversary.SEVERITIES)

    def test_the_finding_states_the_verdict_in_words(self):
        # `claim` is the accusation and reads as one whether or not it succeeded, so
        # the verdict has to be rendered explicitly or a reader has to infer it from
        # the tense of a sentence
        payload = adversary.attack(self.art, hypothesis=self.h)[0].to_dict()
        self.assertTrue(payload["finding"].startswith(("CLEARED", "LANDED")), payload["finding"])
        self.assertIn(payload["severity"], payload["finding"])
        self.assertIn("LANDED" if payload["landed"] else "CLEARED", payload["finding"])

    def test_a_named_authority_clears_the_authority_attack(self):
        good = [a for a in adversary.attack(self.art, hypothesis=self.h,
                                            evidence_for=[strong_evidence(self.h.hid)])
                if a.kind == "attack_authority"]
        self.assertTrue(good[0].survives, good[0].claim)

    def test_a_placeholder_authority_lands_the_authority_attack(self):
        vague = hypothesis(authority="unnamed")
        found = [a for a in adversary.attack(self.art, hypothesis=vague) if a.kind == "attack_authority"]
        self.assertFalse(found[0].survives)
        self.assertEqual(found[0].severity, "SERIOUS")

    def test_a_rule_supported_by_one_source_lands_the_scope_attack(self):
        found = [a for a in adversary.attack(self.art, hypothesis=self.h,
                                             evidence_for=[strong_evidence(self.h.hid, source="one.csv")])
                 if a.kind == "attack_scope"]
        self.assertFalse(found[0].survives, "a rule applied more than once cannot rest on one source")

    def test_a_rule_supported_by_two_sources_clears_the_scope_attack(self):
        both = [strong_evidence(self.h.hid, source="orders.csv"),
                strong_evidence(self.h.hid, source="holdout.csv")]
        found = [a for a in adversary.attack(self.art, hypothesis=self.h, evidence_for=both)
                 if a.kind == "attack_scope"]
        self.assertTrue(found[0].survives, found[0].claim)

    def test_evidence_that_points_the_other_way_lands_the_direction_attack(self):
        against = [strong_evidence(self.h.hid, supports=False) for _ in range(3)]
        found = [a for a in adversary.attack(self.art, hypothesis=self.h, evidence_against=against)
                 if a.kind == "attack_direction"]
        self.assertFalse(found[0].survives)

    def test_a_run_that_did_not_happen_lands_the_assumption_attack(self):
        found = [a for a in adversary.attack(self.art, hypothesis=self.h, results=[])
                 if a.kind == "attack_assumption"]
        self.assertFalse(found[0].survives)

    def test_a_supported_run_clears_the_assumption_attack(self):
        ran = [{"ran": True, "supported": True, "refuted": False, "runner": "discrimination_scan",
                "discriminates": ["H1", "H2"]}]
        found = [a for a in adversary.attack(self.art, hypothesis=self.h, results=ran,
                                            evidence_for=[strong_evidence(self.h.hid)])
                 if a.kind == "attack_assumption"]
        self.assertTrue(found[0].survives, found[0].claim)

    def test_a_landed_decisive_attack_rejects_the_artifact(self):
        attacks = adversary.attack(self.art, hypothesis=hypothesis(authority="unnamed"))
        self.assertFalse(adversary.survived(attacks))
        self.assertEqual(adversary.verdict(attacks), "REJECTED")
        self.assertTrue(adversary.landed(attacks))


class TheGate(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.h = hypothesis()
        self.art = artifact(hypothesis=self.h.hid)
        self.art.state = "ATTACKED"
        self.art.attacks = ["ATK-1", "ATK-2"]
        self.surviving = [
            adversary.Attack(atid=f"ATK-{index}", artifact=self.art.aid, kind=kind, claim="cleared",
                             severity="MINOR", survives=True, response="nothing required")
            for index, kind in enumerate(adversary.catalogue())
        ]
        self.evidence = [strong_evidence(self.h.hid)]

    def test_the_builder_cannot_verify_its_own_artifact(self):
        outcome = gate(self.art, verifier="qse-builder", attacks=self.surviving,
                       reproductions=[reproduction()], evidence_for=self.evidence)
        self.assertFalse(outcome["ok"])
        self.assertIn("R-VER-1", outcome["refusals"])

    def test_an_unattacked_artifact_cannot_be_verified(self):
        fresh = artifact(hypothesis=self.h.hid)
        fresh.state = "CONSTRUCTED"
        outcome = gate(fresh, verifier="someone-else", attacks=[], reproductions=[reproduction()],
                       evidence_for=self.evidence)
        self.assertFalse(outcome["ok"])
        self.assertIn("R-VER-2", outcome["refusals"])

    def test_an_unreproduced_artifact_cannot_be_verified(self):
        outcome = gate(self.art, verifier="someone-else", attacks=self.surviving,
                       reproductions=[], evidence_for=self.evidence)
        self.assertFalse(outcome["ok"])
        self.assertIn("R-VER-3", outcome["refusals"])

    def test_the_gate_refuses_by_reporting_and_never_by_raising(self):
        # unattacked and unreproduced as well as self-verified, so all three rules
        # have something to say and none of them short-circuits the others
        self.art.attacks = []
        outcome = gate(self.art, verifier="qse-builder", attacks=[], reproductions=[],
                       evidence_for=[])
        self.assertFalse(outcome["ok"])
        self.assertEqual(set(outcome["refusals"]), {"R-VER-1", "R-VER-2", "R-VER-3"},
                         "every rule is evaluated, not just the first")
        self.assertEqual(outcome["state_after"], "REJECTED")
        self.assertTrue(outcome["reasons"])

    def test_a_landed_decisive_attack_blocks_verification(self):
        landed = list(self.surviving)
        landed[0] = adversary.Attack(atid="ATK-fatal", artifact=self.art.aid,
                                     kind=adversary.catalogue()[0], claim="landed",
                                     severity="FATAL", survives=False, response="repair it")
        outcome = gate(self.art, verifier="someone-else", attacks=landed,
                       reproductions=[reproduction()], evidence_for=self.evidence)
        self.assertFalse(outcome["ok"])

    def test_an_artifact_without_usable_support_cannot_be_verified(self):
        outcome = gate(self.art, verifier="someone-else", attacks=self.surviving,
                       reproductions=[reproduction()], evidence_for=[])
        self.assertFalse(outcome["ok"])

    def test_the_gate_reaches_verified_when_everything_holds(self):
        outcome = gate(self.art, verifier="someone-else", attacks=self.surviving,
                       reproductions=[reproduction()], evidence_for=self.evidence)
        self.assertTrue(outcome["ok"], outcome["reasons"])
        self.assertEqual(outcome["refusals"], [])
        self.assertEqual(outcome["state_after"], "VERIFIED")
        self.assertTrue(outcome["verification"].independent)

    def test_the_explanation_is_written_from_the_gates_own_result(self):
        good = gate(self.art, verifier="someone-else", attacks=self.surviving,
                    reproductions=[reproduction()], evidence_for=self.evidence)
        bad = gate(self.art, verifier="qse-builder", attacks=[], reproductions=[])
        self.assertNotEqual(explain(good), explain(bad))
        self.assertTrue(explain(bad))


class TheGateAndTheRealAdversary(unittest.TestCase):
    """The two halves wired together, so the verdict is not a fixture's opinion."""

    def setUp(self) -> None:
        pin_clock()
        self.h = hypothesis()
        rows = rows_of()
        self.art = artifact(hypothesis=self.h.hid)
        self.art.state = "ATTACKED"

    def test_a_reproduced_artifact_with_two_sources_survives_the_real_attacks(self):
        both = [strong_evidence(self.h.hid, source="orders.csv"),
                strong_evidence(self.h.hid, source="holdout.csv")]
        # a REPRODUCED observation clears the measurement attack too
        from ..core.evidence import make_evidence

        measured = make_evidence("handoffs predict the breach", hypothesis=self.h.hid,
                                 kind="REPRODUCED", source="orders.csv",
                                 method="independent re-measurement",
                                 collected_at=iso(utcnow()), observed={"field": "handoffs"},
                                 strength="STRONG")
        evidence_for = both + [measured]
        ran = [{"ran": True, "supported": True, "refuted": False, "runner": "discrimination_scan",
                "discriminates": ["H1", "H2"]}]
        rep = reproduction()
        attacks = adversary.attack(self.art, hypothesis=self.h, evidence_for=evidence_for,
                                   results=ran, reproductions=[rep])
        self.art.attacks = [a.atid for a in attacks]
        outcome = gate(self.art, verifier="someone-else", attacks=attacks,
                       reproductions=[rep], evidence_for=evidence_for)
        self.assertTrue(outcome["ok"], [a.kind for a in adversary.landed(attacks)])
        self.assertEqual(outcome["state_after"], "VERIFIED")

    def test_the_same_artifact_without_a_reproduction_is_refused(self):
        both = [strong_evidence(self.h.hid, source="orders.csv"),
                strong_evidence(self.h.hid, source="holdout.csv")]
        attacks = adversary.attack(self.art, hypothesis=self.h, evidence_for=both,
                                   results=[{"ran": True, "supported": True, "refuted": False}])
        self.art.attacks = [a.atid for a in attacks]
        outcome = gate(self.art, verifier="someone-else", attacks=attacks,
                       reproductions=[], evidence_for=both)
        self.assertFalse(outcome["ok"])
        self.assertIn("R-VER-3", outcome["refusals"])


class IndependenceIsAPathNotAName(unittest.TestCase):
    """A name is not an independent path; an attested identity can be."""

    def test_differing_names_with_no_identity_are_independent_but_say_so(self):
        ok, basis = verifier_mod.independence("builder", "verifier")
        self.assertTrue(ok)
        self.assertIn("not attested", basis)

    def test_differing_identities_establish_independence(self):
        ok, basis = verifier_mod.independence("builder", "verifier",
                                              builder_identity="session:A",
                                              verifier_identity="session:B")
        self.assertTrue(ok)
        self.assertEqual(basis, "names and identities differ")

    def test_a_shared_identity_is_not_a_separate_path_even_with_two_names(self):
        ok, basis = verifier_mod.independence("builder", "verifier",
                                              builder_identity="session:A",
                                              verifier_identity="session:A")
        self.assertFalse(ok)
        self.assertIn("identities are equal", basis)

    def test_r_ver_1_refuses_a_shared_identity(self):
        with self.assertRaises(policy.Refusal) as ctx:
            policy.require_independent("builder", "verifier", "session:A", "session:A")
        self.assertEqual(ctx.exception.rule, "R-VER-1")

    def test_the_gate_records_the_basis_and_refuses_a_shared_identity(self):
        art = artifact()
        art.attacks = ["ATK-1"]
        rep = reproduction()
        evidence_for = [strong_evidence("HYP-1", source="orders.csv"),
                        strong_evidence("HYP-1", source="holdout.csv")]
        attack = [{"atid": "ATK-1", "kind": "SCOPE", "severity": "MINOR",
                   "landed": False, "claim": "the rule may not generalise"}]
        shared = gate(art, verifier="someone-else", attacks=attack,
                      reproductions=[rep], evidence_for=evidence_for,
                      builder_identity="session:A", verifier_identity="session:A")
        self.assertIn("R-VER-1", shared["refusals"])
        self.assertFalse(shared["ok"])
        attested = gate(artifact(title="escalate v2"), verifier="someone-else",
                        attacks=attack, reproductions=[rep],
                        evidence_for=evidence_for,
                        builder_identity="session:A", verifier_identity="session:B")
        self.assertEqual(attested["independence_basis"], "names and identities differ")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
