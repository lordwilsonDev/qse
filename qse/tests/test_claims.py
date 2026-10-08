"""The staged claims file, and the verifier that keeps it from drifting.

The important tests are the ones that make a bad claim fail: a missing evidence
path, an unknown status, a duplicate id, a check whose exit code disagrees with the
claim. A claims file nobody can fail is decoration.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from .. import claims as claims_mod, cli
from .support import REPO

HEADER = ("| ID | Claim | Evidence | How to check | Expected | Status | Checked |\n"
          "|---|---|---|---|---|---|---|\n")


def row(cid="C-001", claim="a thing is true", evidence="-", how="python3 -c pass",
        expected="0", status="verified", checked="2026-10-08") -> str:
    return f"| {cid} | {claim} | {evidence} | {how} | {expected} | {status} | {checked} |\n"


class Parsing(unittest.TestCase):
    def test_a_well_formed_row_becomes_a_claim(self):
        claims, problems = claims_mod.parse(HEADER + row())
        self.assertEqual(problems, [])
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0].id, "C-001")
        self.assertTrue(claims[0].runnable)

    def test_a_wrong_cell_count_is_reported(self):
        text = HEADER + "| C-001 | too few |\n"
        claims, problems = claims_mod.parse(text)
        self.assertFalse(claims)
        self.assertTrue(any("no claim rows" in p or "cells" in p for p in problems))

    def test_an_unknown_status_is_reported(self):
        _, problems = claims_mod.parse(HEADER + row(status="probably"))
        self.assertTrue(any("status" in p for p in problems))

    def test_a_duplicate_id_is_reported(self):
        _, problems = claims_mod.parse(HEADER + row() + row())
        self.assertTrue(any("duplicate" in p for p in problems))

    def test_a_claim_with_no_check_is_reported(self):
        _, problems = claims_mod.parse(HEADER + row(how=""))
        self.assertTrue(any("how to check" in p for p in problems))


class EvidenceResolution(unittest.TestCase):
    def test_missing_evidence_is_a_problem(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claims, _ = claims_mod.parse(HEADER + row(evidence="`does/not/exist.md`"))
            out = claims_mod.check(claims, root)
            self.assertFalse(out["ok"])
            self.assertIn("does/not/exist.md", out["problems"][0])

    def test_present_evidence_resolves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "thing.md").write_text("x", encoding="utf-8")
            claims, _ = claims_mod.parse(HEADER + row(evidence="`thing.md`"))
            self.assertTrue(claims_mod.check(claims, root)["ok"])

    def test_a_dash_evidence_cell_is_not_a_path(self):
        claims, _ = claims_mod.parse(HEADER + row(evidence="-"))
        self.assertTrue(claims_mod.check(claims, Path("/nonexistent-root-xyz"))["ok"])


class RunningChecks(unittest.TestCase):
    def test_a_check_that_exits_its_declared_code_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            claims, _ = claims_mod.parse(HEADER + row(
                how="python3 -c \"import sys; sys.exit(0)\"", expected="0"))
            self.assertTrue(claims_mod.run_checks(claims, Path(tmp))["ok"])

    def test_a_check_that_disagrees_with_its_claim_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            claims, _ = claims_mod.parse(HEADER + row(
                how="python3 -c \"import sys; sys.exit(0)\"", expected="1"))
            out = claims_mod.run_checks(claims, Path(tmp))
            self.assertFalse(out["ok"])
            self.assertIn("exited 0, expected 1", out["problems"][0])

    def test_prose_checks_are_not_executed(self):
        claims, _ = claims_mod.parse(HEADER + row(how="read the file", expected="-"))
        self.assertFalse(claims[0].runnable)
        self.assertEqual(claims_mod.run_checks(claims, Path("/tmp"))["rows"], [])


class TheVerifierCommand(unittest.TestCase):
    def _cli(self, argv: list[str]) -> int:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(argv)
        out.close()
        err.close()
        return code

    def test_a_missing_file_is_unusable_input(self):
        self.assertEqual(self._cli(["verify-claims", "--file", "/tmp/nope-claims.md"]), 2)

    def test_a_malformed_claim_file_is_a_defect(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAIMS.md").write_text(HEADER + row(status="maybe"), encoding="utf-8")
            self.assertEqual(self._cli(["verify-claims", "--root", str(root)]), 1)

    def test_a_good_file_with_run_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAIMS.md").write_text(
                HEADER + row(how="python3 -c \"import sys; sys.exit(0)\"", expected="0"),
                encoding="utf-8")
            self.assertEqual(self._cli(["verify-claims", "--root", str(root), "--run"]), 0)

    def test_the_shipped_claims_file_is_structurally_sound(self):
        # structure and evidence only -- --run would recurse into the whole suite
        out = claims_mod.verify(REPO / "CLAIMS.md", REPO)
        self.assertTrue(out["ok"], out["problems"])
        self.assertGreaterEqual(out["claims"], 5)

    def test_json_output_is_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAIMS.md").write_text(HEADER + row(evidence="-"), encoding="utf-8")
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                cli.main(["--json", "verify-claims", "--root", str(root)])
            payload = json.loads(buf.getvalue())
            buf.close()
            err.close()
            self.assertTrue(payload["ok"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
