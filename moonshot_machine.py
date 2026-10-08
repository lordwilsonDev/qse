#!/usr/bin/env python3
"""MOONSHOT-M -- the machine that can attest its own continuity.

One command. One page. The exit code is the answer.

    python3 moonshot_machine.py
    python3 moonshot_machine.py --json

The method is the one that is already here: **AIL (Axiom Inversion Logic)** and **MoIE**.
Nobody's moonshot for an always-on Mac mini is *attestation*; every moonshot is more
compute -- local models, agents, media. So the settled belief is inverted, and what falls
out is the opposite capability:

    the machine's value is not the work it does, it is the continuity it can *prove*,
    which no machine can honestly prove about itself.

That is the whole moonshot, and the script then *runs* it, because a claim that is only
printed is a claim nobody can fail.

What it does, in order, and stops at the first thing it cannot do honestly:

1. **Reverse-engineer the machine.** Read the mini's real state (model, cores, RAM,
   uptime, boot time, disk) -- the facts the axioms below are about. Nothing is guessed;
   an unreadable value is reported as unreadable rather than filled in.
2. **Invert the axioms.** The settled beliefs of the "Mac mini = compute server" story
   are handed to AIL's seven operators and every inversion is pushed through the gate
   (``R-INV-1``: an inversion with no testable consequence is refused and *reported*).
3. **Run the witness.** Heartbeat the machine for real, then prove the record does the
   one thing a log of its own changes could never do: name the interval between two
   beats as ``CONTINUOUS``, ``SLEPT``, ``REBOOT`` or ``HEARTBEAT_LOST`` -- using an
   independent witness (the OS power log, the boot time) rather than trusting itself --
   and record what did *not* change as evidence.

Exit codes: `0` the inverse capability was built and every demonstration held; `1` one
did not; `2` input the script cannot use. Standard library only; macOS-aware but not
macOS-only, and it changes nothing outside the ledger directory it is given.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qse.control.policy import Refusal, require_testable_consequence  # noqa: E402
from qse.core.question import make_question  # noqa: E402
from qse.ids import new_id  # noqa: E402
from qse.inversion.axiom import Axiom  # noqa: E402
from qse.inversion.operators import OPERATOR_FUNCTIONS, OPERATORS  # noqa: E402
from qse.ledger import chain  # noqa: E402
from qse.witness import continuity, power  # noqa: E402

OK, DEFECT, UNUSABLE = 0, 1, 2

QUESTION = ("Should this always-on Mac mini's value be measured by what it computes, or "
            "by what it can prove about itself?")

#: The settled beliefs the "Mac mini = compute server" story rests on. These are the
#: axioms AIL exists to invert; each is a real thing people assume about a home node.
AXIOMS: tuple[tuple[str, str], ...] = (
    ("MEASUREMENT", "a Mac mini is worth running because it computes: it serves models, "
                    "media and agents"),
    ("MEASUREMENT", "the machine's health can be read from the machine's own reports"),
    ("TEMPORAL", "a machine that is always on is one continuous process whose history is "
                 "its log"),
    ("AUTHORITY", "the machine's own log is evidence of what the machine did"),
    ("COORDINATION", "an idle machine is wasted capacity"),
    ("FAILURE", "the failures that matter are the failures the machine observed"),
    ("SCOPE", "what a fleet gives in continuity, one node cannot"),
)

#: Inversion kinds that feed the moonshot. The rest are produced and kept; these are the
#: ones whose consequences the witness is the answer to.
DRIVING_KINDS = ("TEMPORAL_DRIFT", "AUTHORITY_GAP", "UNOBSERVED_FAILURE",
                 "SELECTION_EFFECT", "DATA_INSUFFICIENT", "MEASUREMENT_ARTIFACT")


def _run(argv: list[str], timeout: float = 5.0) -> str:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _sysctl(name: str) -> str:
    return _run(["sysctl", "-n", name])


def _sleep_setting() -> str:
    for line in _run(["pmset", "-g"], timeout=10).splitlines():
        stripped = line.strip()
        if stripped.startswith("sleep") and "(" in stripped:
            return stripped
    return "not readable on this platform"


def profile() -> dict[str, Any]:
    """The machine, read from the machine. An unreadable value stays unreadable."""
    mem = _sysctl("hw.memsize")
    try:
        ram = round(int(mem) / 1073741824, 1) if mem else None
    except ValueError:
        ram = None
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
    return {
        "model": _sysctl("machdep.cpu.brand_string") or platform.processor() or "unknown",
        "arch": platform.machine(),
        "cores": os.cpu_count(),
        "ram_gb": ram,
        "os": platform.mac_ver()[0] or platform.platform(),
        "kernel": platform.release(),
        "load1": round(load[0], 2),
        "boot": continuity.boot_time(),
        "disk_free_gb": round(shutil.disk_usage("/").free / 1073741824, 1),
        "sleep_setting": _sleep_setting(),
        "power_sleeps_recorded": len(power.load()),
    }


def invert() -> tuple[list[Any], list[dict[str, Any]]]:
    """Run all seven operators over every axiom, and gate every candidate.

    Returns the accepted inversions and the refusals, with the rule that refused each.
    The refusals are returned, not dropped: an engine that silently discards an
    unconsequenced inversion is indistinguishable from one that never produced it.
    """
    question = make_question(QUESTION, {})
    accepted: list[Any] = []
    refused: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kind, text in AXIOMS:
        axiom = Axiom(aid=new_id("AXI", text, kind), text=text, kind=kind,
                      source_question=question.qid,
                      because="a settled belief about why an always-on Mac mini is run")
        for name in OPERATORS:
            for inversion in OPERATOR_FUNCTIONS[name](axiom, question, proposition=None):
                if inversion.iid in seen:
                    continue
                seen.add(inversion.iid)
                try:
                    require_testable_consequence(inversion)
                except Refusal as exc:
                    refused.append({"operator": name, "rule": exc.rule,
                                    "statement": inversion.statement})
                    continue
                accepted.append(inversion)
    return accepted, refused


def _witness_demo(directory: Path) -> dict[str, Any]:
    """Run the witness for real, then on injected histories the machine cannot stage."""
    real = str(directory / "witness.jsonl")
    interval = 1.0
    for _ in range(4):
        continuity.beat(real, interval=interval,
                        watches={"disk_free_gb": round(shutil.disk_usage("/").free / 1073741824, 1),
                                 "load1": round(os.getloadavg()[0], 2)})
        time.sleep(0.05)
    report = continuity.verify(real, sleeps=[], slack=0.1)

    # A tamper: rewrite a non-final line and prove the chain notices.
    tampered = str(directory / "tampered.jsonl")
    Path(tampered).write_text(Path(real).read_text(encoding="utf-8"), encoding="utf-8")
    lines = chain.read_lines(tampered)
    # Rewrite a NON-final line. The chain cannot cover the last line by design, so
    # editing that one would be the wrong demonstration.
    lines[1] = lines[1] + " "
    Path(tampered).write_text("\n".join(lines) + "\n", encoding="utf-8")
    tamper_report = continuity.verify(tampered, sleeps=[])

    # Injected histories: the classifier's three non-continuous outcomes, deterministic.
    prev = {"wall": 1000.0, "boot": 500.0, "interval": 60.0}
    cases = {
        "a machine that slept": ({"wall": 4600.0, "boot": 500.0, "interval": 60.0},
                                 [power.Sleep(entered=1010.0, woke=4540.0, reason="injected")]),
        "a machine that rebooted": ({"wall": 1600.0, "boot": 4000.0, "interval": 60.0}, []),
        "a recorder that died": ({"wall": 4600.0, "boot": 500.0, "interval": 60.0}, []),
    }
    injected = {name: continuity.classify(prev, now, sleeps=sleeps)["kind"]
                for name, (now, sleeps) in cases.items()}

    # A REAL subject: watch a process we own, then catch it leaving. The recorder never
    # misses a beat, so the ledger stays continuous while the thing it was watching dies
    # -- which is the discrepancy the whole moonshot turns on.
    subject_ledger = str(directory / "subject.jsonl")
    proc = subprocess.Popen(["sleep", "5"])
    try:
        for _ in range(2):
            continuity.beat(subject_ledger, interval=1.0,
                            subject=continuity.subject_identity(proc.pid))
            time.sleep(0.05)
        proc.terminate()
        proc.wait(timeout=5)
        time.sleep(0.05)
        continuity.beat(subject_ledger, interval=1.0,
                        subject=continuity.subject_identity(proc.pid))
    finally:
        if proc.poll() is None:  # pragma: no cover - only if terminate/wait raced
            proc.kill()
    subject_report = continuity.verify(subject_ledger, sleeps=[], slack=0.1)

    # The two witnesses, and the four ways they can move. Deterministic, so this half does
    # not depend on timing. "a new process, the same token" is the case a supervisor
    # produces: a crashed job restarted with its run id preserved -- a false vouch.
    base_subject = {"name": "job", "pid": 10, "started": "t0", "token": "run-A"}
    subject_cases = {
        "nothing changed": ({**base_subject}, "SUBJECT_OK"),
        "a new process, the same token": ({**base_subject, "pid": 99, "started": "t9"},
                                          "SUBJECT_VOUCH_CONFLICT"),
        "same process, a new token": ({**base_subject, "token": "run-B"},
                                       "SUBJECT_TOKEN_DRIFT"),
        "a new process, a new token": ({**base_subject, "pid": 99, "started": "t9",
                                        "token": "run-B"}, "SUBJECT_RESTARTED"),
    }
    subject_injected = {
        name: continuity.classify_subject({"subject": base_subject}, {"subject": now})["kind"]
        for name, (now, _kind) in subject_cases.items()
    }
    subject_expected = {name: kind for name, (_now, kind) in subject_cases.items()}

    return {
        "real": {"ledger": real, "verdict": report["verdict"], "beats": report["beats"],
                 "chain_ok": report["chain_ok"], "counts": report["counts"],
                 "tail": report["tail"]},
        "tamper": {"verdict": tamper_report["verdict"], "chain_ok": tamper_report["chain_ok"]},
        "injected": injected,
        "subject": {"ledger": subject_ledger, "verdict": subject_report["verdict"],
                    "counts": subject_report["subject_counts"],
                    "witnesses": subject_report["subject_witnesses"],
                    "kinds": [row["kind"] for row in subject_report["subject_transitions"]],
                    "injected": subject_injected, "expected": subject_expected},
        "absences": continuity.absences(real),
        "power_sleeps_recorded": len(power.load()),
    }


def receipt(prof: Mapping[str, Any], accepted: list[Any], refused: list[dict[str, Any]],
            demo: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    driving = [inv for inv in accepted if inv.kind in DRIVING_KINDS]
    by_kind: dict[str, int] = {}
    for inv in accepted:
        by_kind[inv.kind] = by_kind.get(inv.kind, 0) + 1

    ok = (demo["real"]["verdict"] == "CONTINUOUS"
          and demo["tamper"]["verdict"] == "TAMPERED"
          and demo["injected"] == {"a machine that slept": "SLEPT",
                                   "a machine that rebooted": "REBOOT",
                                   "a recorder that died": "HEARTBEAT_LOST"}
          and demo["subject"]["verdict"] == "SUBJECT_BROKE"
          and demo["subject"]["injected"] == demo["subject"]["expected"]
          and "SUBJECT_OK" in demo["subject"]["kinds"])

    lines: list[str] = []
    lines.append("MOONSHOT-M  the machine that can attest its own continuity")
    lines.append("")
    lines.append(f"  host     {prof['model']}, {prof['arch']}, {prof['cores']} cores, "
                 f"{prof['ram_gb']} GB RAM")
    lines.append(f"  os       macOS {prof['os']} (kernel {prof['kernel']})  load1 {prof['load1']}")
    lines.append(f"  disk     {prof['disk_free_gb']} GB free    sleep: {prof['sleep_setting']}")
    lines.append("")

    lines.append("1. THE MACHINE, READ FROM THE MACHINE  (the axioms are about these facts)")
    lines.append(f"   boot time {prof['boot']}   OS power-log sleep intervals recorded: "
                 f"{prof['power_sleeps_recorded']}")
    lines.append("   the seven settled beliefs being inverted are in AXIOMS (moonshot_machine.py)")
    lines.append("")

    lines.append("2. AXIOM INVERSION  (AIL: 7 operators x 7 axioms, every one gated)")
    lines.append(f"   {len(AXIOMS)} axioms -> {len(accepted)} inversions passed the gate, "
                 f"{len(refused)} refused")
    for kind, n in sorted(by_kind.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"     {kind:<22} {n}")
    for row in refused:
        lines.append(f"     REFUSED  {row['rule']}  {row['statement'][:70]}")
    lines.append(f"   {len(driving)} inversion(s) drive the moonshot:")
    for inv in driving[:4]:
        lines.append(f"     [{inv.kind}] {inv.statement[:88]}")
        if inv.consequence:
            lines.append(f"       observe: {inv.consequence.observation[:84]}")
    lines.append("")

    lines.append("3. THE MOONSHOT")
    lines.append("   Invert the axiom that an always-on node's value is what it COMPUTES.")
    lines.append("   Its value is what it can ATTEST: continuity a long job or a customer")
    lines.append("   can lean on, which the machine cannot honestly produce about itself.")
    lines.append("   So the node keeps a hash-chained heartbeat and treats every gap as a")
    lines.append("   claim: the OS power log (not the process) says whether it slept, the")
    lines.append("   boot time says whether it restarted, and anything else is recorded as")
    lines.append("   HEARTBEAT_LOST rather than rounded to fine. It beats FOR a subject, and")
    lines.append("   records the subject's identity at every beat, so 'the ledger never")
    lines.append("   stopped' and 'the job never stopped' are told apart -- the recorder can")
    lines.append("   stay continuous while the subject dies. What did NOT change is recorded")
    lines.append("   too, because 'the disk did not fill' is evidence a log of changes cannot.")
    lines.append("")

    lines.append("4. THE WITNESS, RUN")
    lines.append(f"   real ledger: {demo['real']['beats']} beats, verdict "
                 f"{demo['real']['verdict']}, chain_ok {demo['real']['chain_ok']}, "
                 f"counts {demo['real']['counts']}")
    lines.append(f"   tampered line rewritten -> verdict {demo['tamper']['verdict']} "
                 f"(chain_ok {demo['tamper']['chain_ok']})")
    for name, kind in demo["injected"].items():
        lines.append(f"   injected history, {name:<26} -> {kind}")
    lines.append("   subject, witnessed twice (the machine's probe vs the subject's token):")
    lines.append(f"     a real process we started, then ended -> verdict "
                 f"{demo['subject']['verdict']} from counts {demo['subject']['counts']}")
    for name, kind in demo["subject"]["injected"].items():
        lines.append(f"     injected: {name:<30} -> {kind}")
    wit = demo["subject"]["witnesses"]
    lines.append(f"     witnesses on the real ledger: {wit['identity_changes']} identity "
                 f"change(s), {wit['token_changes']} token change(s), "
                 f"{wit['disagreements']} disagreement(s)")
    lines.append("   absences (what did not change):")
    for row in demo["absences"]:
        state = "held steady" if not row["changed"] else "changed"
        lines.append(f"     {row['metric']:<16} {state:<12} first {row['first']} last {row['last']}")
    lines.append(f"   OS power witness: {demo['power_sleeps_recorded']} sleep interval(s) in the log "
                 "(empty is a fact about the witness, not about continuity)")
    lines.append("")

    lines.append("VERDICT")
    if ok:
        lines.append("   THE INVERSE CAPABILITY HOLDS: the record is tamper-evident, tells a")
        lines.append("   sleep from a death from a reboot without trusting itself, and keeps")
        lines.append("   absence as evidence. Read section 3 before repeating the claim.")
    else:
        lines.append("   NOT YET: one of the demonstrations did not hold; see section 4.")
    lines.append("")
    lines.append("   honest limits: it attests a DECLARED SUBJECT's continuity, watched through")
    lines.append("   an independent probe (a process identity, or whatever the caller supplies);")
    lines.append("   it does not attest that the subject did anything, and a subject the probe")
    lines.append("   cannot see reads as SUBJECT_MISSING. The sleep witness is the OS power log,")
    lines.append("   so a rotated or suppressed log turns a sleep into HEARTBEAT_LOST -- an")
    lines.append("   honest 'unknown', never a false 'continuous'. See docs/moonshot-m.md.")

    payload = {
        "profile": dict(prof),
        "axioms": len(AXIOMS),
        "inversions_accepted": len(accepted),
        "inversions_refused": len(refused),
        "by_kind": by_kind,
        "driving": [inv.to_dict() for inv in driving],
        "demo": demo,
        "verdict_ok": ok,
    }
    return "\n".join(lines), payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="moonshot_machine.py",
        description="MOONSHOT-M: invert the axioms of an always-on Mac mini and build the "
                    "capability that falls out -- a machine that can attest its continuity.",
    )
    parser.add_argument("--ledger-dir", help="where the demonstration ledger is written "
                                             "(default: a temp dir)")
    parser.add_argument("--json", action="store_true", help="print the machine-readable object")
    args = parser.parse_args(argv)

    scratch = Path(args.ledger_dir) if args.ledger_dir else Path(tempfile.mkdtemp(prefix="moonshot-m-"))
    scratch.mkdir(parents=True, exist_ok=True)
    try:
        prof = profile()
        accepted, refused = invert()
        demo = _witness_demo(scratch)
        page, payload = receipt(prof, accepted, refused, demo)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        else:
            print(page)
        return OK if payload["verdict_ok"] else DEFECT
    finally:
        if not args.ledger_dir:
            shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
