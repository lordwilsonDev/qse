"""The control arm, and the gate on whether a fixture can carry one.

The important test here is the last class: a fixture which *can* punish the naive
arm must be reported as separable, and the shipped one must not be. If both read
the same, the audit is decoration.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout

from .. import baseline as baseline_mod, cli
from ..experiment import runner
from .support import EXAMPLES, pin_clock


def spurious_fixture() -> tuple[list[dict], list[dict]]:
    """A fixture where one column predicts perfectly in-sample and not out.

    ``m`` is the mechanism: it holds in both samples. ``s`` is spurious: it is a
    perfect predictor on the fitting sample and carries nothing on the holdout.
    """
    fit = []
    for i in range(40):
        m = i % 10
        fit.append({"m": m, "s": 1 if m >= 5 else 0, "y": 1 if m >= 5 else 0})
    hold = []
    for i in range(40):
        m = i % 10
        # s is constant within each decade while y varies inside it, so s carries
        # no information about y on this sample
        hold.append({"m": m, "s": (i // 10) % 2, "y": 1 if m >= 5 else 0})
    return fit, hold


class TheRanking(unittest.TestCase):
    def test_columns_are_ranked_by_the_fitting_sample(self):
        fit, hold = spurious_fixture()
        ranked = baseline_mod.rank_correlates(fit, hold, outcome="y")
        self.assertEqual([r["column"] for r in ranked][0], "s")
        strengths = [abs(r["fit"]) for r in ranked]
        self.assertEqual(strengths, sorted(strengths, reverse=True))
        self.assertEqual(set(r["column"] for r in ranked), {"m", "s"})

    def test_a_hand_counted_correlation_comes_out_right(self):
        # x=[1,2,3,4], y=[0,0,1,1]: Sxy=2.0, Sxx=5.0, Syy=1.0 -> 2/sqrt(5) = 0.8944272
        # the audit reports 4 decimals on purpose, so that is the precision asserted
        rows = [{"x": x, "y": y} for x, y in zip([1, 2, 3, 4], [0, 0, 1, 1])]
        ranked = baseline_mod.rank_correlates(rows, None, outcome="y")
        self.assertEqual(len(ranked), 1)
        self.assertAlmostEqual(ranked[0]["fit"], 0.8944, places=4)
        self.assertLessEqual(len(str(ranked[0]["fit"]).split(".")[-1]), 4)

    def test_it_is_the_engines_own_statistic_not_a_second_opinion(self):
        fit, hold = spurious_fixture()
        ranked = {r["column"]: r for r in baseline_mod.rank_correlates(fit, hold, outcome="y")}
        for column in ("m", "s"):
            expected = runner._pearson(runner._xy_pairs(fit, column, "y"))
            self.assertAlmostEqual(ranked[column]["fit"], round(expected, 4), places=6)

    def test_a_missing_holdout_reads_as_not_measured_not_as_zero(self):
        fit, _ = spurious_fixture()
        ranked = baseline_mod.rank_correlates(fit, None, outcome="y")
        for row in ranked:
            self.assertIsNone(row["holdout"], "absence is not a zero correlation")
            self.assertEqual(row["n_holdout"], 0)

    def test_identifier_columns_are_not_measurements(self):
        fit, _ = spurious_fixture()
        fit[0]["order_id"] = "ORD-1"
        fit[1]["order_id"] = "ORD-2"
        names = {r["column"] for r in baseline_mod.rank_correlates(fit, None, outcome="y")}
        self.assertNotIn("order_id", names)

    def test_the_naive_pick_is_the_top_row(self):
        fit, hold = spurious_fixture()
        ranked = baseline_mod.rank_correlates(fit, hold, outcome="y")
        self.assertEqual(baseline_mod.naive_pick(ranked)["column"], "s")
        self.assertIsNone(baseline_mod.naive_pick([]))


class WhatTheAuditRefuses(unittest.TestCase):
    def setUp(self) -> None:
        self.fit, self.hold = spurious_fixture()

    def test_no_holdout_means_the_comparison_cannot_be_run(self):
        out = baseline_mod.audit(self.fit, None, outcome="y", driver="m")
        self.assertFalse(out["separable"])
        self.assertIn("cannot be run at all", out["reason"])

    def test_no_named_driver_means_nothing_to_measure_against(self):
        out = baseline_mod.audit(self.fit, self.hold, outcome="y")
        self.assertFalse(out["separable"])
        self.assertIn("no driver was named", out["reason"])

    def test_an_unknown_driver_is_refused_rather_than_assumed(self):
        out = baseline_mod.audit(self.fit, self.hold, outcome="y", driver="nope")
        self.assertFalse(out["separable"])
        self.assertIn("not a measurable column", out["reason"])

    def test_no_measurable_column_at_all_is_refused(self):
        out = baseline_mod.audit([{"y": 1}], [{"y": 1}], outcome="y", driver="m")
        self.assertFalse(out["separable"])
        self.assertIn("enough paired numbers", out["reason"])

    def test_a_fixture_whose_top_correlate_is_the_driver_credits_the_naive_arm(self):
        out = baseline_mod.audit(self.fit, self.hold, outcome="y", driver="s")
        self.assertFalse(out["separable"])
        self.assertIn("IS the named driver", out["reason"])


class TheSeparabilityVerdict(unittest.TestCase):
    def test_a_fixture_that_punishes_the_naive_arm_is_separable(self):
        fit, hold = spurious_fixture()
        out = baseline_mod.audit(fit, hold, outcome="y", driver="m")
        self.assertTrue(out["separable"], out["reason"])
        self.assertEqual(out["naive_pick"]["column"], "s")
        self.assertIn("collapses on the holdout", out["reason"])
        self.assertEqual([r["column"] for r in out["survivors"]], [])

    def test_a_surviving_non_driver_makes_the_fixture_unseparable(self):
        fit, hold = spurious_fixture()
        # make the spurious column hold out of sample too, by copying the driver
        for row in hold:
            row["s"] = row["y"]
        out = baseline_mod.audit(fit, hold, outcome="y", driver="m")
        self.assertFalse(out["separable"])
        self.assertIn("cannot tell a mechanism from a strong correlate", out["reason"])
        self.assertEqual([r["column"] for r in out["survivors"]], ["s"])

    def test_the_margin_is_named_and_used(self):
        fit, hold = spurious_fixture()
        tight = baseline_mod.audit(fit, hold, outcome="y", driver="m", margin=0.0)
        self.assertEqual(tight["margin"], 0.0)
        self.assertTrue(tight["separable"])

    def test_the_audit_is_deterministic(self):
        fit, hold = spurious_fixture()
        first = baseline_mod.audit(fit, hold, outcome="y", driver="m")
        second = baseline_mod.audit(fit, hold, outcome="y", driver="m")
        self.assertEqual(first, second)


class TheShippedFixture(unittest.TestCase):
    """The scenario QSE ships must be reported as unable to carry the comparison."""

    @classmethod
    def setUpClass(cls) -> None:
        pin_clock()
        import json
        cls.fit = json.loads((EXAMPLES / "orders_scenario.json").read_text(encoding="utf-8"))["rows"]
        cls.hold = json.loads((EXAMPLES / "orders_holdout.json").read_text(encoding="utf-8"))["rows"]

    def test_it_cannot_tell_a_mechanism_from_a_strong_correlate(self):
        out = baseline_mod.audit(self.fit, self.hold, driver="handoffs")
        self.assertFalse(out["separable"], out["reason"])
        self.assertEqual(out["naive_pick"]["column"], "staff_on_shift")
        self.assertNotEqual(out["naive_pick"]["column"], "handoffs")

    def test_it_names_the_columns_that_survive_out_of_sample(self):
        out = baseline_mod.audit(self.fit, self.hold, driver="handoffs")
        survivors = {r["column"] for r in out["survivors"]}
        self.assertIn("system_latency_ms", survivors)
        self.assertIn("staff_on_shift", survivors)


class TheVerdicts(unittest.TestCase):
    def _cli(self, argv: list[str]) -> int:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        out.close()
        err.close()
        return code

    def test_the_shipped_fixture_exits_non_zero_because_it_cannot_carry_the_test(self):
        self.assertEqual(self._cli([
            "fixture", "--scenario", (EXAMPLES / "orders_scenario.json").as_posix(),
            "--holdout", (EXAMPLES / "orders_holdout.json").as_posix(),
            "--driver", "handoffs"]), 1)

    def test_a_missing_scenario_is_unusable_input(self):
        self.assertEqual(self._cli(["fixture", "--scenario", "/tmp/does-not-exist.json"]), 2)

    def test_a_separable_fixture_exits_zero_and_prints_json(self):
        # the exit-0 path is the one that says "you may run the comparison", so it
        # is exercised rather than only asserted in prose
        import json
        import tempfile
        from pathlib import Path

        fit, hold = spurious_fixture()
        with tempfile.TemporaryDirectory(prefix="qse-fixture-") as tmp:
            scenario = Path(tmp) / "sep_scenario.json"
            holdout = Path(tmp) / "sep_holdout.json"
            scenario.write_text(json.dumps({"name": "separable", "rows": fit}), encoding="utf-8")
            holdout.write_text(json.dumps({"name": "separable-hold", "rows": hold}), encoding="utf-8")
            argv = ["fixture", "--scenario", scenario.as_posix(), "--holdout", holdout.as_posix(),
                    "--driver", "m", "--outcome", "y"]
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                code = cli.main(["--json"] + argv)
            payload = json.loads(out.getvalue())
            out.close()
            err.close()
            self.assertEqual(payload["separable"], True, payload["reason"])
            self.assertEqual(payload["naive_pick"]["column"], "s")
            self.assertEqual(self._cli(argv), 0, "a separable fixture must exit 0")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
