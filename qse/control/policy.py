"""The policy. Every refusal QSE makes lives here, named and testable.

A system that reports what it did without refusing anything is an activity log.
The refusals are the apparatus: each one is a rule with an id, each raises
``Refusal`` carrying that id, and each is covered by a test. If a rule is
relaxed later, the diff shows exactly which guarantee was traded away.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..core.evidence import Evidence
from ..core.experiment import Experiment
from ..core.hypothesis import Hypothesis
from ..core.question import Question

__all__ = [
    "Refusal", "RULES", "rule_ids",
    "require_testable_consequence", "require_falsifiable", "require_provenance",
    "require_usable_evidence", "require_independent", "require_attacked",
    "require_reproduced", "require_distinct", "require_scope", "forbid_majority_vote",
]

#: rule id -> what it protects. Printed by `qse.cli rules`.
RULES: dict[str, str] = {
    "R-INV-1": "an inversion without a testable consequence is not a hypothesis source",
    "R-EXP-1": "an experiment that cannot be refuted is not an experiment",
    "R-EVD-1": "evidence without provenance (source and method) is a recording, not evidence",
    "R-EVD-2": "a model proposal, report or contested claim never counts as usable evidence",
    "R-HYP-1": "two hypotheses that are the same explanation are one hypothesis",
    "R-SYN-1": "no hypothesis is selected by counting how many experts hold it",
    "R-VER-1": "the builder cannot verify its own artifact",
    "R-VER-2": "an artifact cannot be verified before it has been attacked",
    "R-VER-3": "an artifact cannot be verified without a reproduction that ran and matched",
    "R-QUE-1": "a question with an unresolved blocking slot cannot be consumed",
}


class Refusal(RuntimeError):
    """QSE declined to do something, and the rule id says which guarantee it was."""

    def __init__(self, rule: str, message: str) -> None:
        if rule not in RULES:
            raise KeyError(f"unknown rule id {rule!r}")
        super().__init__(f"{rule}: {message}")
        self.rule = rule
        self.message = message


def rule_ids() -> tuple[str, ...]:
    return tuple(RULES)


# --------------------------------------------------------------------------- #
# Inversion
# --------------------------------------------------------------------------- #

def require_testable_consequence(inversion: Any) -> None:
    """R-INV-1. Without a consequence AIL is philosophy, not an engine."""
    consequence = getattr(inversion, "consequence", None)
    if consequence is None:
        statement = getattr(inversion, "statement", inversion)
        raise Refusal("R-INV-1", f"inversion {statement!r} has no testable consequence")
    for field in ("observation", "if_true", "if_false", "discriminates"):
        if not str(getattr(consequence, field, "") or "").strip():
            raise Refusal("R-INV-1", f"consequence is missing '{field}', so it cannot be tested")


# --------------------------------------------------------------------------- #
# Experiments
# --------------------------------------------------------------------------- #

def require_falsifiable(experiment: Experiment) -> None:
    """R-EXP-1."""
    if not experiment.falsifiable():
        raise Refusal("R-EXP-1", f"experiment {experiment.xid} states nothing that would refute it")


# --------------------------------------------------------------------------- #
# Evidence
# --------------------------------------------------------------------------- #

def require_provenance(evidence: Evidence) -> None:
    """R-EVD-1."""
    missing = [name for name in ("source", "method") if not str(getattr(evidence, name, "") or "").strip()]
    if missing:
        raise Refusal("R-EVD-1", f"evidence {evidence.eid} has no {', '.join(missing)}")


def require_usable_evidence(evidence: Evidence) -> None:
    """R-EVD-2. Recorded either way; only some classes may be consumed."""
    require_provenance(evidence)
    if not evidence.usable():
        raise Refusal("R-EVD-2", f"evidence {evidence.eid} is not usable: {evidence.why_unusable()}")


# --------------------------------------------------------------------------- #
# Hypotheses
# --------------------------------------------------------------------------- #

def require_distinct(hypothesis: Hypothesis, existing: list[Hypothesis]) -> None:
    """R-HYP-1. Competing hypotheses must actually compete."""
    for other in existing:
        if other.hid == hypothesis.hid:
            continue
        if not hypothesis.structurally_differs(other):
            raise Refusal(
                "R-HYP-1",
                f"{hypothesis.hid} and {other.hid} are the same explanation "
                f"(identical {hypothesis.structure()}); differing prose is not a difference",
            )


# --------------------------------------------------------------------------- #
# Selection
# --------------------------------------------------------------------------- #

def forbid_majority_vote(tally: Mapping[str, int], total: int) -> None:
    """R-SYN-1. Called by synthesis before it weighs evidence, so that no code path
    can select a hypothesis from a head-count even by accident."""
    if total and any(count > total / 2 for count in tally.values()):
        raise Refusal(
            "R-SYN-1",
            "selection received a majority tally; QSE selects on evidence weight, "
            "never on how many experts hold a position",
        )


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def require_independent(builder: str, verifier: str, builder_identity: str = "",
                        verifier_identity: str = "") -> None:
    """R-VER-1. The builder cannot verify its own artifact.

    Names are compared folded, as before. When both sides attest an identity, a
    shared identity is refused even though the names differ -- two names are not
    two paths, and a session id the caller supplies closes that gap.
    """
    if not str(verifier).strip():
        raise Refusal("R-VER-1", "verification needs a named verifier")
    if str(verifier).strip().lower() == str(builder).strip().lower():
        raise Refusal("R-VER-1", f"{builder!r} built this artifact and cannot verify it")
    left = str(builder_identity or "").strip()
    right = str(verifier_identity or "").strip()
    if left and right and left == right:
        raise Refusal(
            "R-VER-1",
            f"builder and verifier attest the same identity {left!r}, so the verifier is "
            f"not a separate path even though the names differ",
        )


def require_attacked(artifact: Any) -> None:
    """R-VER-2."""
    if not artifact.constructed():
        raise Refusal("R-VER-2", f"artifact {artifact.aid} has not been constructed")
    if not artifact.attacks:
        raise Refusal("R-VER-2", f"artifact {artifact.aid} has not been attacked; verification would be a formality")


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #

def require_reproduced(reproductions: Any) -> None:
    """R-VER-3. A green test in one process is not reproducibility."""
    ran = [r for r in reproductions if getattr(r, "ran", False)]
    matched = [r for r in ran if getattr(r, "ok", False)]
    if not ran:
        raise Refusal("R-VER-3", "no reproduction was executed")
    if not matched:
        raise Refusal("R-VER-3", "every reproduction that ran disagreed with the first run")


def require_scope(question: Question) -> None:
    """R-QUE-1."""
    blocking = question.blocking()
    if blocking:
        raise Refusal(
            "R-QUE-1",
            f"question {question.qid} cannot be consumed: blocking slot(s) unresolved "
            f"({', '.join(blocking)})",
        )
