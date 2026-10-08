"""Question quality, and the shape every QSE metric reports in.

Question quality is a *profile*, not one number: five ambiguities matter
differently depending on how many are blocking and how many hypotheses rest on
them. So this module reports counts, carries ``value: None`` to say out loud
that no single scalar summarises it, and offers ``resolved_ratio`` for callers
that genuinely want one.

``measure`` and ``ratio`` live here because every other metric module imports
them; having one definition of the reporting shape is what keeps six metrics
comparable instead of six dialects.
"""

from __future__ import annotations

from typing import Any

from ..control.state import State
from ..core.question import SLOTS

__all__ = ["measure", "ratio", "question_quality"]


def ratio(numerator: float, denominator: float) -> float | None:
    """A ratio, or ``None`` when the denominator is zero.

    An empty denominator is UNKNOWN. It is not 0.0 (which reads as "none of them
    passed") and it is not 1.0 (which reads as "all of them passed"). Returning
    ``None`` forces the caller to decide what an empty sample means instead of
    inheriting a flattering default.
    """
    if not denominator:
        return None
    return numerator / denominator


def measure(value: Any, numerator: Any, denominator: Any, definition: str, **extra: Any) -> dict[str, Any]:
    """The one reporting shape. Every metric in QSE returns this."""
    out: dict[str, Any] = {
        "value": value,
        "numerator": numerator,
        "denominator": denominator,
        "definition": definition,
    }
    out.update(extra)
    return out


def question_quality(state: State) -> dict[str, Any]:
    """Counts of how well-formed the questions actually got."""
    records = [rec for bucket in state.ambiguities.values() for rec in bucket]
    blocking = [rec for rec in records if str(rec.get("severity", "")).upper() == "BLOCKING"]
    assumptions = list(state.assumptions.values())
    load_bearing = [a for a in assumptions if a.get("load_bearing")]

    unresolved = state.unresolved_slots()
    n_unresolved = sum(len(slots) for slots in unresolved.values())
    n_declared = len(state.questions) * len(SLOTS)
    n_resolved = n_declared - n_unresolved

    out = measure(
        None,
        None,
        None,
        "a profile metric: question quality is reported as counts, not one number",
        ambiguities=len(records),
        blocking=len(blocking),
        assumptions=len(assumptions),
        load_bearing=len(load_bearing),
        unresolved_slots=n_unresolved,
        unresolved_by_question=unresolved,
        revisions=len(state.mutations),
        questions=len(state.questions),
    )
    out["resolved_ratio"] = measure(
        ratio(n_resolved, n_declared),
        n_resolved,
        n_declared,
        "resolved_slots / declared_slots across every question in state",
    )
    return out
