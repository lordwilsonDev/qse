"""The scorecard: question, knowledge, experiment, artifact, verification, outcome.

Six numbers, each carrying its own numerator, denominator and definition, because
a ratio without its denominator is how a metric gets gamed:

    QBY  question-to-build yield     validated_artifacts / initial_questions
    BSR  blindspot reduction         blindspots_before - blindspots_after
    EC   evidence conversion         usable_evidence / generated_evidence
    BC   build conversion            executable_artifacts / proposed_artifacts
    VI   verification independence   independently_verified / total_artifacts
    OC   outcome conversion          real_world_outcomes / verified_artifacts

``limits`` is part of the report, not an afterthought. Every one of these numbers
is blind to something specific, and a scorecard that does not say what it cannot
see invites the reader to assume it sees everything.
"""

from __future__ import annotations

from typing import Any

from ..control.state import State
from ..ids import iso, utcnow
from .blindspots import blindspots
from .build_quality import build_quality
from .question_quality import measure, question_quality, ratio
from .verification import verification

__all__ = ["LIMITS", "scorecard", "qby", "oc", "bsr", "ec", "bc", "vi"]

LIMITS: tuple[str, ...] = (
    "QBY divides validated artifacts by initial questions, so one question that yields several "
    "artifacts can push it above 1.0. It is a yield, not a probability.",
    "OC counts only Outcome records flagged real_world, and only those written to this ledger. "
    "A real outcome nobody recorded is invisible here, which makes OC a floor, not a rate.",
    "VI is exactly as strong as the verifier identity: two names are two verifiers. The ledger "
    "cannot tell whether they were one person, one model, or one process.",
    "BSR can be negative. A revision that opens more slots than it closes has made the question "
    "worse, and the sign is the point.",
    "Information gain is ordinal, so this scorecard ranks work; it does not price it.",
    "Nothing here measures whether the original question was worth asking. QSE can convert a "
    "foolish question into a verified artifact and every number above will look healthy.",
)


def _real_world_outcomes(state: State) -> list[str]:
    return sorted(oid for oid, rec in state.outcomes.items() if rec.get("real_world") is True)


def qby(state: State) -> dict[str, Any]:
    initial = state.root_questions()
    validated = state.verified_artifacts()
    return measure(
        ratio(len(validated), len(initial)),
        len(validated),
        len(initial),
        "validated_artifacts / initial_questions",
        validated=[str(a.get("aid")) for a in validated],
        initial_questions=[str(q.get("qid")) for q in initial],
    )


def oc(state: State) -> dict[str, Any]:
    verified = state.verified_artifacts()
    real = _real_world_outcomes(state)
    return measure(
        ratio(len(real), len(verified)),
        len(real),
        len(verified),
        "real_world_outcomes / verified_artifacts",
        real_world_outcomes=real,
        recorded_outcomes=sorted(state.outcomes),
    )


def bsr(state: State) -> dict[str, Any]:
    return blindspots(state)


def ec(state: State) -> dict[str, Any]:
    return verification(state)["EC"]


def bc(state: State) -> dict[str, Any]:
    report = build_quality(state)
    return {k: v for k, v in report.items() if k != "states"}


def vi(state: State) -> dict[str, Any]:
    report = verification(state)
    return {k: v for k, v in report.items() if k != "EC"}


def scorecard(state: State) -> dict[str, Any]:
    """All six metrics plus the limits of all six."""
    return {
        "QBY": qby(state),
        "BSR": blindspots(state),
        "EC": verification(state)["EC"],
        "BC": build_quality(state),
        "VI": {k: v for k, v in verification(state).items() if k != "EC"},
        "OC": oc(state),
        "question_quality": question_quality(state),
        "generated_at": iso(utcnow()),
        "n_events": len(state.records),
        "summary": state.summary(),
        "limits": list(LIMITS),
    }
