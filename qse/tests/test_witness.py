"""MOONSHOT-M: the continuity ledger, its gap classifier, and the OS power-log witness.

The tests are grouped the way the claim is: the record is tamper-evident, the gap
classifier tells a sleep from a death without trusting the machine, and a metric that
never moved is recorded as evidence rather than dropped as silence.
"""

from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from ..ledger import chain
from ..witness import continuity, power
from .support import Workspace, pin_clock


def _beat(path, index: int, *, boot: float = 500.0, watches=None, subject=None,
          progress=None, effect=None, effects=None) -> None:
    """A fully injected heartbeat, so a history can be replayed without waiting."""
    continuity.beat(path, wall=1_000.0 + index * 60.0, mono=index * 60.0,
                    boot=boot, pid=1, interval=60.0, watches=watches or {},
                    subject=subject, progress=progress, effect=effect, effects=effects)


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


class TheSubjectTheRecordIsAbout(unittest.TestCase):
    """The recorder staying up is not the same fact as the watched thing staying up."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("w.jsonl")

    def test_a_ledger_with_no_subject_is_still_continuous(self):
        # backward compatibility: watching nothing is not watching something that broke
        for i in range(3):
            _beat(self.path, i)
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["verdict"], "CONTINUOUS")
        self.assertEqual(report["subject_counts"], {"SUBJECT_UNWATCHED": 2})

    def test_a_subject_that_leaves_breaks_the_verdict_though_the_recorder_never_stopped(self):
        job = {"name": "job", "pid": 7, "started": "t0"}
        _beat(self.path, 0, subject=job)
        _beat(self.path, 1, subject=job)
        _beat(self.path, 2, subject=None)  # the process ended; the recorder beat on
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["counts"], {"CONTINUOUS": 2}, "the recorder never missed a beat")
        self.assertEqual(report["verdict"], "SUBJECT_BROKE")
        self.assertEqual(report["subject_counts"]["SUBJECT_MISSING"], 1)

    def test_a_subject_that_leaves_and_returns_is_a_restart(self):
        job = {"name": "job", "pid": 7, "started": "t0"}
        back = {"name": "job", "pid": 7, "started": "t0"}
        _beat(self.path, 0, subject=job)
        _beat(self.path, 1, subject=job)
        _beat(self.path, 2, subject=None)
        _beat(self.path, 3, subject=back)
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["verdict"], "SUBJECT_BROKE")
        self.assertEqual(report["subject_counts"]["SUBJECT_RESTARTED"], 1)

    def test_a_changed_identity_is_a_restart_and_the_same_one_is_not(self):
        a = {"subject": {"name": "job", "pid": 7, "started": "t0"}}
        same = {"subject": {"name": "job", "pid": 7, "started": "t0"}}
        restarted = {"subject": {"name": "job", "pid": 9, "started": "t1"}}
        self.assertEqual(continuity.classify_subject(a, same)["kind"], "SUBJECT_OK")
        self.assertEqual(continuity.classify_subject(a, restarted)["kind"], "SUBJECT_RESTARTED")

    def test_a_new_process_with_the_same_token_is_a_vouch_conflict(self):
        # a supervisor restarting a crashed job while preserving its run id
        a = {"subject": {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}}
        b = {"subject": {"name": "job", "pid": 99, "started": "t9", "token": "run-A"}}
        got = continuity.classify_subject(a, b)
        self.assertEqual(got["kind"], continuity.SUBJECT_VOUCH_CONFLICT)
        self.assertTrue(got["identity_changed"])
        self.assertFalse(got["token_changed"])

    def test_the_same_process_with_a_new_token_is_a_token_drift(self):
        a = {"subject": {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}}
        b = {"subject": {"name": "job", "pid": 10, "started": "t0", "token": "run-B"}}
        got = continuity.classify_subject(a, b)
        self.assertEqual(got["kind"], continuity.SUBJECT_TOKEN_DRIFT)
        self.assertFalse(got["identity_changed"])
        self.assertTrue(got["token_changed"])

    def test_a_new_process_and_a_new_token_agree_it_restarted(self):
        a = {"subject": {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}}
        b = {"subject": {"name": "job", "pid": 99, "started": "t9", "token": "run-B"}}
        self.assertEqual(continuity.classify_subject(a, b)["kind"], "SUBJECT_RESTARTED")

    def test_verify_counts_the_two_witnesses_and_their_disagreement_separately(self):
        run_a = {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}
        replaced = {"name": "job", "pid": 99, "started": "t9", "token": "run-A"}
        _beat(self.path, 0, subject=run_a)
        _beat(self.path, 1, subject=run_a)
        _beat(self.path, 2, subject=replaced)  # a new process vouching the same run
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["verdict"], "SUBJECT_BROKE")
        self.assertEqual(report["subject_witnesses"]["disagreements"], 1)
        self.assertEqual(report["subject_witnesses"]["identity_changes"], 1)
        self.assertEqual(report["subject_witnesses"]["token_changes"], 0)

    def _vouch(self, policy=None) -> None:
        """A ledger where a new process declares the same run id: SUBJECT_VOUCH_CONFLICT."""
        a = {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}
        b = {"name": "job", "pid": 99, "started": "t9", "token": "run-A"}
        continuity.beat(self.path, wall=1_000.0, mono=0.0, boot=500.0, pid=1, interval=60.0,
                        subject=a, policy=policy)
        continuity.beat(self.path, wall=1_060.0, mono=60.0, boot=500.0, pid=1, interval=60.0,
                        subject=b)

    def test_a_vouch_conflict_is_a_break_under_report_but_excused_under_token(self):
        self._vouch()
        self.assertEqual(continuity.verify(self.path, sleeps=[])["verdict"], "SUBJECT_BROKE")
        self.assertEqual(continuity.verify(self.path, sleeps=[], policy="token")["verdict"],
                         "CONTINUOUS")
        self.assertEqual(continuity.verify(self.path, sleeps=[], policy="probe")["verdict"],
                         "SUBJECT_BROKE")

    def test_a_token_drift_is_excused_under_probe_but_not_under_token(self):
        a = {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}
        b = {"name": "job", "pid": 10, "started": "t0", "token": "run-B"}
        continuity.beat(self.path, wall=1_000.0, mono=0.0, boot=500.0, pid=1, interval=60.0,
                        subject=a)
        continuity.beat(self.path, wall=1_060.0, mono=60.0, boot=500.0, pid=1, interval=60.0,
                        subject=b)
        self.assertEqual(continuity.verify(self.path, sleeps=[], policy="probe")["verdict"],
                         "CONTINUOUS")
        self.assertEqual(continuity.verify(self.path, sleeps=[], policy="token")["verdict"],
                         "SUBJECT_BROKE")

    def test_the_policy_declared_on_a_beat_is_what_verify_reads(self):
        self._vouch(policy="token")
        report = continuity.verify(self.path, sleeps=[])
        self.assertEqual(report["policy"], "token")
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_reader_can_restate_the_policy_and_change_the_verdict(self):
        self._vouch(policy="token")
        report = continuity.verify(self.path, sleeps=[], policy="report")
        self.assertEqual(report["policy"], "report")
        self.assertEqual(report["verdict"], "SUBJECT_BROKE")

    def test_an_unknown_policy_is_refused(self):
        self._vouch()
        with self.assertRaises(ValueError):
            continuity.verify(self.path, sleeps=[], policy="trust-everything")
        with self.assertRaises(ValueError):
            continuity.beat(self.path, wall=2_000.0, policy="trust-everything")

    def test_the_subject_probe_reads_a_live_process_and_none_once_it_ends(self):
        proc = subprocess.Popen(["sleep", "5"])
        self.addCleanup(lambda: proc.poll() is None and proc.kill())
        alive = continuity.subject_identity(proc.pid)
        self.assertIsNotNone(alive)
        self.assertEqual(alive["pid"], proc.pid)
        self.assertTrue(alive["started"], "a restart must not reproduce the start time")
        proc.terminate()
        proc.wait(timeout=5)
        self.assertIsNone(continuity.subject_identity(proc.pid))


class TheProgressSignal(unittest.TestCase):
    """Liveness is not progress: a subject can stay alive and advance nothing."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("w.jsonl")

    def _run(self, values, *, subject=None):
        for i, value in enumerate(values):
            _beat(self.path, i, subject=subject, progress=value)
        return continuity.verify(self.path, sleeps=[])

    def test_a_counter_that_advances_is_continuous(self):
        report = self._run([0.0, 1.0, 2.0, 5.0])
        self.assertEqual(report["progress_counts"], {"PROGRESS_ADVANCING": 3})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_counter_that_holds_flat_to_the_threshold_is_a_stall(self):
        # The subject is perfectly fine -- same identity every beat -- and it advances
        # nothing, which is the failure no gap or identity check can see.
        job = {"name": "job", "pid": 7, "started": "t0"}
        report = self._run([7.0, 7.0, 7.0, 7.0], subject=job)
        self.assertEqual(report["subject_counts"], {"SUBJECT_OK": 3})
        self.assertEqual(report["longest_flat"], 3)
        self.assertEqual(len(report["stalls"]), 1)
        self.assertEqual(report["verdict"], "SUBJECT_STALLED")

    def test_a_flat_pair_alone_is_not_yet_a_stall(self):
        report = self._run([3.0, 3.0, 3.0])
        self.assertEqual(report["longest_flat"], 2)
        self.assertEqual(report["stalls"], [])
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_the_stall_threshold_is_declarable(self):
        self.assertEqual(self._run([0.0, 0.0, 0.0])["verdict"], "CONTINUOUS")
        report = continuity.verify(self.path, sleeps=[], stall_after=2)
        self.assertEqual(report["stall_after"], 2)
        self.assertEqual(report["verdict"], "SUBJECT_STALLED")

    def test_a_counter_that_goes_backwards_is_a_break_not_a_stall(self):
        report = self._run([10.0, 20.0, 5.0])
        self.assertEqual(report["progress_counts"],
                         {"PROGRESS_ADVANCING": 1, "PROGRESS_REGRESSED": 1})
        self.assertEqual(len(report["regressions"]), 1)
        self.assertEqual(report["verdict"], "SUBJECT_BROKE")

    def test_a_beat_with_no_progress_carries_no_signal(self):
        report = self._run([1.0, None, None])
        self.assertEqual(report["progress_counts"], {"PROGRESS_NO_SIGNAL": 2})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_non_numeric_progress_is_refused(self):
        with self.assertRaises(ValueError):
            continuity.beat(self.path, wall=1.0, progress="lots")


class TheSideEffectWitness(unittest.TestCase):
    """Progress checked against the world, not only reported by the subject."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("w.jsonl")

    def _run(self, declared, observed, **kw):
        for i, (decl, eff) in enumerate(zip(declared, observed)):
            _beat(self.path, i, progress=decl, effect=eff)
        return continuity.verify(self.path, sleeps=[], **kw)

    def test_a_claimed_advance_the_world_does_not_show_is_unsubstantiated(self):
        report = self._run([1, 2, 3, 4], [10, 10, 10, 10], stall_after=3)
        self.assertEqual(report["effect_counts"], {"EFFECT_UNSUBSTANTIATED": 3})
        self.assertEqual(report["longest_unsubstantiated"], 3)
        self.assertEqual(report["verdict"], "SUBJECT_UNSUBSTANTIATED")

    def test_a_single_unsubstantiated_beat_may_be_lag_and_is_not_yet_a_finding(self):
        # One beat of divergence is not declared a lie: only a sustained run is.
        report = self._run([1, 2, 3], [10, 10, 30], stall_after=3)
        self.assertEqual(report["effect_counts"], {"EFFECT_UNSUBSTANTIATED": 1,
                                                    "EFFECT_AGREES": 1})
        self.assertEqual(report["unsubstantiated"], [])
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_an_unclaimed_advance_is_reported_but_does_not_stall(self):
        # The counter is flat -- which alone would be a stall -- but the world shows the
        # work advancing, so the subject is silent, not stalled. The second witness refutes
        # the false stall.
        report = self._run([1, 1, 1, 1], [10, 20, 30, 40], stall_after=3)
        self.assertEqual(report["effect_counts"], {"EFFECT_UNREPORTED": 3})
        self.assertEqual(report["stalls"], [])
        self.assertEqual(report["longest_flat"], 0)
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_counter_and_a_world_that_both_advance_agree(self):
        report = self._run([1, 2, 3, 4], [10, 20, 30, 40], stall_after=3)
        self.assertEqual(report["effect_counts"], {"EFFECT_AGREES": 3})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_missing_effect_carries_no_side_effect_signal(self):
        report = self._run([1, 2, 3], [None, None, None])
        self.assertEqual(report["effect_counts"], {"EFFECT_NO_SIGNAL": 2})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_the_file_effect_reads_a_real_side_effect(self):
        produced = self.ws.path / "produced.log"
        produced.write_bytes(b"")
        self.assertEqual(continuity.file_effect(produced), 0.0)
        produced.write_bytes(b"tick\n" * 32)
        self.assertEqual(continuity.file_effect(produced), 160.0)
        self.assertIsNone(continuity.file_effect(self.ws.path / "nope.log"))

    def test_a_non_numeric_effect_is_refused(self):
        with self.assertRaises(ValueError):
            continuity.beat(self.path, wall=1.0, effect="lots")


class TheCorroborationOfSources(unittest.TestCase):
    """Independence is counted, not asserted: a claim is only as strong as the sources."""

    def setUp(self) -> None:
        pin_clock()
        self.ws = Workspace()
        self.addCleanup(self.ws.close)
        self.path = self.ws.ledger("w.jsonl")

    def _run(self, declared, sources, **kw):
        names = list(sources)
        for i, decl in enumerate(declared):
            _beat(self.path, i, progress=decl,
                  effects={n: sources[n][i] for n in names})
        return continuity.verify(self.path, sleeps=[], **kw)

    def test_two_sources_that_agree_corroborate_the_advance(self):
        report = self._run([1, 2, 3, 4], {"db_rows": [10, 20, 30, 40],
                                          "files": [5, 6, 7, 8]}, stall_after=3)
        self.assertEqual(report["effect_sources"], 2)
        self.assertEqual(report["corroboration_counts"], {"CORROBORATION_CORROBORATED": 3})
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_an_advance_only_one_source_witnesses_is_uncorroborated(self):
        report = self._run([1, 2, 3, 4], {"db_rows": [10, 20, 30, 40],
                                          "files": [5, 5, 5, 5]}, stall_after=3)
        self.assertEqual(report["corroboration_counts"], {"CORROBORATION_SINGLE_SOURCE": 3})
        self.assertEqual(report["verdict"], "SUBJECT_UNCORROBORATED")

    def test_sources_that_contradict_each_other_are_a_split(self):
        report = self._run([1, 2, 3, 4], {"db_rows": [10, 20, 30, 40],
                                          "files": [8, 7, 6, 5]}, stall_after=3)
        self.assertEqual(report["corroboration_counts"], {"CORROBORATION_SPLIT": 3})
        self.assertEqual(report["verdict"], "SUBJECT_WITNESSES_SPLIT")

    def test_no_source_advancing_makes_a_claimed_advance_unsubstantiated(self):
        # The subject claims an advance and none of the named sources moves: the claim is
        # contradicted by every witness the record reads.
        report = self._run([1, 2, 3, 4], {"db_rows": [5, 5, 5, 5],
                                          "files": [9, 9, 9, 9]}, stall_after=3)
        self.assertEqual(report["corroboration_counts"], {"CORROBORATION_NONE": 3})
        self.assertEqual(report["verdict"], "SUBJECT_UNSUBSTANTIATED")

    def test_a_single_source_ledger_does_not_engage_the_corroboration_verdicts(self):
        # Backward compatibility: with one source read, an advancing subject keeps its
        # existing reading; independence is simply not claimed either way.
        report = self._run([1, 2, 3, 4], {"db_rows": [10, 20, 30, 40]}, stall_after=3)
        self.assertEqual(report["effect_sources"], 1)
        self.assertEqual(report["verdict"], "CONTINUOUS")
        self.assertEqual(report["uncorroborated"], [])

    def test_a_single_source_is_not_uncorroborated_when_nothing_was_claimed(self):
        # A flat counter with one source advancing is unclaimed work, not a false claim.
        report = self._run([1, 1, 1, 1], {"db_rows": [10, 20, 30, 40],
                                          "files": [5, 5, 5, 5]}, stall_after=3)
        self.assertEqual(report["uncorroborated"], [])
        self.assertEqual(report["verdict"], "CONTINUOUS")

    def test_a_non_numeric_named_source_is_refused(self):
        with self.assertRaises(ValueError):
            continuity.beat(self.path, wall=1.0, effects={"db_rows": "lots"})


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
