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
        self.assertEqual(subject["injected_restart"], "SUBJECT_RESTARTED")
        self.assertIn("SUBJECT_MISSING", subject["kinds"])

    def test_the_page_names_the_moonshot_and_its_verdict(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = moonshot.main([])
        page = out.getvalue()
        self.assertEqual(code, 0, page)
        self.assertIn("MOONSHOT-M", page)
        self.assertIn("THE INVERSE CAPABILITY HOLDS", page)
        self.assertIn("SUBJECT_BROKE", page)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
