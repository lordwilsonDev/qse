"""Staged claims, and the mechanical check that keeps them honest.

QSE makes claims about itself -- in README.md, in docs/LIMITS.md, in the command
line. This module turns them into rows that a machine can check, so a claim is a
thing that is *verified* rather than a thing that is *written down*.

It follows the discipline of the BlackSwanLabz Research Lab CLAIMS file: every
claim names its evidence and how to check it, and its status is one of three:

    verified   checked, and the check passed
    pending    not yet checked -- never restate as fact
    retracted  checked and found wrong -- kept, not deleted

Standard library only. No claim is ever upgraded by prose; the status changes only
when the check changes.
"""

from __future__ import annotations

import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

__all__ = ["STATUSES", "Claim", "parse", "check", "run_checks", "verify"]

STATUSES = ("verified", "pending", "retracted")

_ID = re.compile(r"^C-\d{3}$")
_ROW = re.compile(r"^\|.*\|$")
_URL_OR_PATH = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class Claim:
    id: str
    claim: str
    evidence: str
    how_to_check: str
    expected: str
    status: str
    checked: str
    line: int = 0

    @property
    def runnable(self) -> bool:
        """A check the verifier may execute, with a declared exit code."""
        return self.how_to_check.startswith("python3") and self.expected.isdigit()


def _cells(line: str) -> list[str]:
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|"):
        text = text[:-1]
    return [cell.strip() for cell in text.split("|")]


def parse(text: str) -> tuple[list[Claim], list[str]]:
    """Read the claim table. Returns the claims and any structural problems."""
    claims: list[Claim] = []
    problems: list[str] = []
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not _ROW.match(line):
            continue
        cells = _cells(line)
        first = cells[0] if cells else ""
        if not _ID.match(first):
            # header row, separator row, or prose -- not a claim
            if first and first.startswith("C-"):
                problems.append(f"line {number}: {first!r} is not a C-### id")
            continue
        if len(cells) != 7:
            problems.append(f"line {number}: claim {first} has {len(cells)} cells, expected 7")
            continue
        cid, claim, evidence, how, expected, status, checked = (c.strip() for c in cells)
        if cid in seen:
            problems.append(f"line {number}: duplicate claim id {cid}")
        seen.add(cid)
        if status not in STATUSES:
            problems.append(f"line {number}: {cid} status {status!r} is not one of {STATUSES}")
        if not claim:
            problems.append(f"line {number}: {cid} states no claim")
        if not how:
            problems.append(f"line {number}: {cid} has no 'how to check' -- an unchecked "
                            "claim is not a claim")
        if not checked:
            problems.append(f"line {number}: {cid} has no checked date")
        claims.append(Claim(id=cid, claim=claim, evidence=evidence, how_to_check=how,
                            expected=expected, status=status, checked=checked, line=number))
    if not claims:
        problems.append("no claim rows found")
    return claims, problems


def _evidence_paths(evidence: str) -> list[str]:
    """Repo-relative paths named in the evidence cell (backticked), if any."""
    if evidence.strip() in ("", "-"):
        return []
    return _URL_OR_PATH.findall(evidence) or [evidence.strip()]


def check(claims: Sequence[Claim], root: Path) -> dict[str, Any]:
    """Structural check: does each claim name resolvable evidence and a check?"""
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for claim in claims:
        missing = [p for p in _evidence_paths(claim.evidence)
                   if not (root / p).exists() and not p.startswith(("http://", "https://"))]
        ok = not missing
        if missing:
            problems.append(f"{claim.id}: evidence not found: {', '.join(missing)}")
        rows.append({"id": claim.id, "status": claim.status, "evidence_missing": missing,
                     "ok": ok, "runnable": claim.runnable})
    return {"rows": rows, "problems": problems, "ok": not problems}


def run_checks(claims: Sequence[Claim], root: Path) -> dict[str, Any]:
    """Execute every runnable check and compare its exit code to the declared one.

    Only commands that start with ``python3`` and declare a numeric expected exit
    are executed -- the verifier does not run arbitrary prose. A mismatch is a
    problem with the claim, not with the command.
    """
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for claim in claims:
        if not claim.runnable:
            continue
        try:
            argv = shlex.split(claim.how_to_check)
        except ValueError as exc:
            problems.append(f"{claim.id}: check command does not parse ({exc})")
            continue
        completed = subprocess.run(argv, cwd=str(root), capture_output=True, text=True)
        want = int(claim.expected)
        ok = completed.returncode == want
        if not ok:
            problems.append(f"{claim.id}: check exited {completed.returncode}, expected {want}")
        rows.append({"id": claim.id, "expected": want, "got": completed.returncode, "ok": ok})
    return {"rows": rows, "problems": problems, "ok": not problems}


def verify(file: Path, root: Path, *, run: bool = False) -> dict[str, Any]:
    """Parse, structurally check, and optionally execute a claims file."""
    text = file.read_text(encoding="utf-8")
    claims, problems = parse(text)
    structure = check(claims, root) if claims else {"rows": [], "problems": [], "ok": True}
    problems += structure["problems"]
    execution = {"rows": [], "problems": [], "ok": True}
    if run and claims:
        execution = run_checks(claims, root)
        problems += execution["problems"]
    return {
        "file": str(file),
        "root": str(root),
        "claims": len(claims),
        "structure": structure,
        "execution": execution,
        "problems": problems,
        "ok": not problems,
    }
