"""MOONSHOT-M: the continuity ledger, its gap classifier, and the OS power-log witness.

The tests are grouped the way the claim is: the record is tamper-evident, the gap
classifier tells a sleep from a death without trusting the machine, and a metric that
never moved is recorded as evidence rather than dropped as silence.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ..ledger import chain
from ..witness import continuity, power
from .support import Workspace, pin_clock


def _beat(path, index: int, *, boot: float = 500.0, watches=None) -> None:
    """A fully injected heartbeat, so a history can be replayed without waiting."""
    continuity.beat(path, wall=1_000.0 + index * 60.0, mono=index * 60.0,
                    boot=boot, pid=1, interval=60.0, watches=watches or {})


class TheBeatLedger(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("witness.jsonl")

    def test_a_chain_of_regular_beats_verifies_as_continuous(self):
        for i in range(5):
            _beat(self.path, i)
        report = continuity.verify(self.path, sleeps=[])
        self.assertTrue(report["chain_ok"], report["chain_reason"])
        self.assertEqual(report["beats"], 5)
        self.assertEqual(report["counts"], {"CONTINUOUS": 4})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_tampering_with_a_beaten_line_is_detected(self):
        for i in range(5):
            _beat(self.path, i)
        lines = chain.read_lines(self.path)
        # Edit a NON-final line: the chain cannot cover the last line by design, and
        # editing it would be the wrong test.
        lines[1] = lines[1].replace('"wall": 1060.0', '"wall": 9999.0')
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        report = continuity.verify(self.path, sleeps=[])
        self.assertFalse(report["chain_ok"])
        self.assertEqual(report["verdict"], "TAMPERED")

    def test_an_empty_ledger_is_empty_and_not_continuous(self):
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["verdict"], "EMPTY")
        self.assertEqual(report["beats"], 0)


class TheGapClassifier(unittest.TestCase):
    """A gap is a claim. Three independent things can explain it; nothing is assumed."""

    def setUp(self) -> None:
        pin_clock()

    def test_a_gap_within_one_interval_is_continuous(self):
        prev = {"wall": 1_000.0, "boot": 500.0, "interval": 60.0}
        now = {"wall": 1_030.0, "boot": 500.0, "interval": 60.0}
        self.assertEqual(continuity.classify(prev, now, sleeps=[])["kind"], "CONTINUOUS")

    def test_a_gap_the_power_log_covers_is_a_sleep_not_a_death(self):
        prev = {"wall": 1_000.0, "boot": 500.0, "interval": 60.0}
        now = {"wall": 4_600.0, "boot": 500.0, "interval": 60.0}  # one hour later
        slept = [power.Sleep(entered=1_010.0, woke=4_540.0, reason="test")]
        got = continuity.classify(prev, now, sleeps=slept)
        self.assertEqual(got["kind"], "SLEPT")
        self.assertEqual(len(got["sleeps"]), 1)

    def test_a_gap_nothing_explains_is_reported_as_lost(self):
        prev = {"wall": 1_000.0, "boot": 500.0, "interval": 60.0}
        now = {"wall": 4_600.0, "boot": 500.0, "interval": 60.0}
        got = continuity.classify(prev, now, sleeps=[])
        self.assertEqual(got["kind"], "HEARTBEAT_LOST")
        self.assertIn("no sleep", got["why"])

    def test_a_changed_boot_time_is_a_reboot_even_when_a_sleep_covers_the_gap(self):
        prev = {"wall": 1_000.0, "boot": 500.0, "interval": 60.0}
        now = {"wall": 1_600.0, "boot": 4_000.0, "interval": 60.0}
        covering = [power.Sleep(entered=1_010.0, woke=1_590.0, reason="test")]
        self.assertEqual(continuity.classify(prev, now, sleeps=covering)["kind"], "REBOOT")

    def test_a_lost_heartbeat_makes_the_whole_verdict_broken(self):
        ws = Workspace()
        self.addCleanup(ws.close)
        path = ws.ledger("w.jsonl")
        _beat(path, 0)
        _beat(path, 1)
        continuity.beat(path, wall=1_000.0 + 10 * 60.0, mono=600.0, boot=500.0, pid=1,
                        interval=60.0)  # a 9-minute hole with nothing to explain it
        report = continuity.verify(path, sleeps=[])
        self.assertEqual(report["verdict"], "BROKEN")
        self.assertEqual(len(report["lost"]), 1)
        self.assertIn("HEARTBEAT_LOST", report["counts"])


class TheAbsenceRecord(unittest.TestCase):
    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("w.jsonl")

    def test_a_metric_that_never_moved_is_reported_as_evidence_of_absence(self):
        for i in range(4):
            _beat(self.path, i, watches={"disk_free_gb": 100.0, "load": float(i)})
        rows = {row["metric"]: row for row in continuity.absences(self.path)}
        self.assertFalse(rows["disk_free_gb"]["changed"])
        self.assertIn("evidence", rows["disk_free_gb"]["note"])
        self.assertTrue(rows["load"]["changed"])


class ThePowerLogWitness(unittest.TestCase):
    def test_sleep_and_wake_lines_become_one_interval(self):
        sample = (
            "2026-10-01 23:00:00 -0500 Sleep               Entering Sleep state due to 'Idle Sleep': Using AC\n"
            "2026-10-01 23:00:01 -0500 Assertions          PID 1(x) Created Foo\n"
            "2026-10-02 07:00:00 -0500 Wake                Wake from Normal Sleep [CDNVA] due to EHC1/HID Activity\n"
        )
        got = power.parse(sample)
        self.assertEqual(len(got), 1)
        self.assertIsNotNone(got[0].woke)
        self.assertLess(got[0].entered, got[0].woke)

    def test_a_sleep_with_no_wake_is_left_open_rather_than_guessed(self):
        sample = "2026-10-01 23:00:00 -0500 Sleep               Entering Sleep state due to 'Idle Sleep'\n"
        got = power.parse(sample)
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0].woke)

    def test_an_empty_power_log_is_an_empty_witness_not_an_error(self):
        self.assertEqual(power.parse(""), [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
