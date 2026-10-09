"""MOONSHOT-M: the one-command script builds the inverse capability and holds.

The script is a script, not a module in the package, so it is loaded from its path and
driven through ``main`` -- the same entry point a person runs. The demonstration is
deterministic (injected histories), so it does not depend on this machine's clock.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout

from .support import REPO, pin_clock

_spec = importlib.util.spec_from_file_location("moonshot_machine", REPO / "moonshot_machine.py")
moonshot = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(moonshot)


class TheMoonshotMachine(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()

    def test_the_script_builds_the_capability_and_every_demonstration_holds(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = moonshot.main(["--json"])
        self.assertEqual(code, 0, out.getvalue())
        payload = json.loads(out.getvalue())
        self.assertTrue(payload["verdict_ok"])
        self.assertEqual(payload["axioms"], 7)
        self.assertGreater(payload["inversions_accepted"], 0)
        # Every axiom contributes exactly one untestable candidate, and the gate
        # refuses all of them rather than dropping them silently.
        self.assertEqual(payload["inversions_refused"], 7)
        self.assertEqual(payload["demo"]["real"]["verdict"], "CONTINUOUS")
        self.assertEqual(payload["demo"]["tamper"]["verdict"], "TAMPERED")
        self.assertEqual(payload["demo"]["injected"], {
            "a machine that slept": "SLEPT",
            "a machine that rebooted": "REBOOT",
            "a recorder that died": "HEARTBEAT_LOST",
        })
        # The subject: a real process we started and ended. The recorder never stopped,
        # and the record still reports the subject break -- the moonshot's whole point.
        subject = payload["demo"]["subject"]
        self.assertEqual(subject["verdict"], "SUBJECT_BROKE")
        self.assertEqual(subject["injected"], subject["expected"])
        self.assertEqual(subject["injected"]["a new process, the same token"],
                         "SUBJECT_VOUCH_CONFLICT")
        self.assertEqual(subject["injected"]["same process, a new token"],
                         "SUBJECT_TOKEN_DRIFT")
        self.assertIn("SUBJECT_MISSING", subject["kinds"])
        # The declared policy fixes the verdict by a rule, and the reader can restate it.
        pol = payload["demo"]["policy"]
        self.assertEqual(pol["declared"], "token")
        self.assertEqual(pol["default_verdict"], "CONTINUOUS")
        self.assertEqual(pol["reattributed_verdict"], "SUBJECT_BROKE")
        self.assertEqual(pol["vouch_conflict_break"],
                         {"report": True, "probe": True, "token": False, "both": True})
        # Liveness is not progress: a subject that stays alive and advances nothing is
        # reported SUBJECT_STALLED, while an advancing one stays CONTINUOUS.
        prog = payload["demo"]["progress"]
        self.assertEqual(prog["stalled_verdict"], "SUBJECT_STALLED")
        self.assertEqual(prog["stalled_beats"], prog["stall_after"])
        self.assertEqual(prog["advancing_verdict"], "CONTINUOUS")
        # Progress checked against the world: a real growing file backs the real ledger; a
        # claimed advance nothing substantiates is unsubstantiated; an unclaimed advance is
        # benign (and must not be misread as a stall).
        eff = payload["demo"]["effect"]
        self.assertEqual(eff["agrees_verdict"], "CONTINUOUS")
        self.assertEqual(eff["unsubstantiated_verdict"], "SUBJECT_UNSUBSTANTIATED")
        self.assertEqual(eff["unreported_verdict"], "CONTINUOUS")
        # Independence counted, not asserted: two sources that agree corroborate, one source
        # is uncorroborated, and sources that contradict each other are a split.
        co = payload["demo"]["corroboration"]
        self.assertEqual(co["corroborated_verdict"], "CONTINUOUS")
        self.assertEqual(co["corroborated_sources"], 2)
        self.assertEqual(co["uncorroborated_verdict"], "SUBJECT_UNCORROBORATED")
        self.assertEqual(co["split_verdict"], "SUBJECT_WITNESSES_SPLIT")
        # One level deeper: agreement is not independence. The same corroborated ledger
        # is independent only when its sources declare a reason they are beyond reach.
        ind = payload["demo"]["independence"]
        self.assertEqual(ind["independent_verdict"], "CONTINUOUS")
        self.assertEqual(ind["independent_sources"], ["db_rows", "files"])
        self.assertEqual(ind["unproven_verdict"], "SUBJECT_INDEPENDENCE_UNPROVEN")
        self.assertEqual(ind["unproven_sources"], [])
        # And one level past the declaration: a reach the recorder *checks* for itself.
        # Two read-only sources are attested; a writable source marked read-only is
        # caught by the check and reported, not believed.
        self.assertEqual(ind["attested_verdict"], "CONTINUOUS")
        self.assertEqual(ind["attested_sources"], ["db_rows", "files"])
        self.assertEqual(ind["contradicted_verdict"], "SUBJECT_INDEPENDENCE_CONTRADICTED")
        self.assertEqual(ind["contradicted_sources"], ["db_rows", "files"])
        # And the value itself, measured not reported: the recorder reads the bytes, so the
        # number the advance rests on is a function of the file. Two read-only sources it
        # both checks and reads reach the strongest kind; a reported number the bytes refute
        # is caught; and an advance resting on reported values is named, not promoted.
        val = payload["demo"]["values"]
        self.assertEqual(val["measured_verdict"], "CONTINUOUS")
        self.assertEqual(val["measured_sources"], ["db_rows", "files"])
        self.assertGreaterEqual(val["measured_independence"], 1)
        self.assertEqual(val["contradicted_verdict"], "SUBJECT_VALUES_CONTRADICTED")
        self.assertEqual(val["contradicted_values"], ["db_rows", "files"])
        self.assertEqual(val["reported_verdict"], "SUBJECT_VALUES_REPORTED")
        self.assertEqual(val["reported_sources"], ["db_rows", "files"])

    def test_the_page_names_the_moonshot_and_its_verdict(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = moonshot.main([])
        page = out.getvalue()
        self.assertEqual(code, 0, page)
        self.assertIn("MOONSHOT-M", page)
        self.assertIn("THE INVERSE CAPABILITY HOLDS", page)
        self.assertIn("SUBJECT_BROKE", page)
        self.assertIn("SUBJECT_STALLED", page)
        self.assertIn("SUBJECT_UNSUBSTANTIATED", page)
        self.assertIn("SUBJECT_UNCORROBORATED", page)
        self.assertIn("SUBJECT_WITNESSES_SPLIT", page)
        self.assertIn("SUBJECT_INDEPENDENCE_UNPROVEN", page)
        self.assertIn("SUBJECT_VALUES_CONTRADICTED", page)
        self.assertIn("SUBJECT_VALUES_REPORTED", page)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
