"""Turning inversions into competing hypotheses, without producing synonyms.

An inversion is a denial of an axiom; a hypothesis is an *explanation* that can
be tested. The translation is the ``KIND_TO_STRUCTURE`` table: each inversion
kind names how the world would have to work for that denial to be true — a
mechanism, a locus, and a timescale.

Because ``Hypothesis`` compares five structural fields and every hypothesis
here shares two of them (the measurement assumption and the authority), two
hypotheses are the same explanation exactly when their (mechanism, locus,
timescale) triples agree. Nine kinds, nine distinct triples, so nine structurally
different explanations — which is what "multiple structurally different
hypotheses" has to mean if it is to mean anything.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

from ..control.policy import require_distinct
from ..core.hypothesis import Hypothesis, make_hypothesis
from ..core.question import Question

#: Inversion kind -> (mechanism, locus, timescale), using the vocabularies in
#: qse/core/hypothesis.py. Every entry is distinct as a triple.
KIND_TO_STRUCTURE: dict[str, tuple[str, str, str]] = {
    "DATA_INSUFFICIENT": ("MEASUREMENT", "TELEMETRY", "WEEKS"),
    "SCOPE_COLLAPSE": ("AGGREGATION", "PROCESS", "DAYS"),
    "REVERSE_CAUSATION": ("SEQUENCING", "PROCESS", "HOURS"),
    "TEMPORAL_DRIFT": ("POLICY", "PROCESS", "MONTHS"),
    "AUTHORITY_GAP": ("POLICY", "COMMUNICATION", "WEEKS"),
    "MEASUREMENT_ARTIFACT": ("MEASUREMENT", "TELEMETRY", "MINUTES"),
    "AGGREGATION": ("AGGREGATION", "TELEMETRY", "DAYS"),
    "UNOBSERVED_FAILURE": ("EXTERNAL", "SUPPLIER", "WEEKS"),
    "SELECTION_EFFECT": ("VARIANCE", "TELEMETRY", "HOURS"),
}

#: Used when an operator invents a kind this table has not been taught. The
#: hypothesis is still built, and carries a note saying its structure was
#: defaulted, so the gap is visible rather than silent.
DEFAULT_STRUCTURE: tuple[str, str, str] = ("MEASUREMENT", "PROCESS", "DAYS")

DEFAULT_MEASUREMENT_ASSUMPTION = "the recorded timestamps and counts are correct"


def structure_for(kind: str) -> tuple[str, str, str]:
    return KIND_TO_STRUCTURE.get(kind, DEFAULT_STRUCTURE)


def from_inversions(
    inversions: Iterable[Any],
    question: Question,
    *,
    authority: str,
    measurement_assumption: str = DEFAULT_MEASUREMENT_ASSUMPTION,
) -> list[Hypothesis]:
    """One hypothesis per structurally distinct inversion, in production order.

    Deduped by hypothesis id, so two inversions that assert the same *structure*
    from the same question collapse into one explanation instead of two.
    """
    if not authority.strip():
        raise ValueError("hypotheses need a named authority: somebody must be able to call them wrong")

    out: list[Hypothesis] = []
    seen: set[str] = set()
    for inversion in inversions:
        kind = str(getattr(inversion, "kind", ""))
        mechanism, locus, timescale = structure_for(kind)
        hypothesis = make_hypothesis(
            str(inversion.statement),
            question=question.qid,
            mechanism=mechanism,
            locus=locus,
            timescale=timescale,
            measurement_assumption=measurement_assumption,
            authority=authority,
            from_inversion=str(getattr(inversion, "iid", "")) or None,
        )
        if hypothesis.hid in seen:
            continue
        seen.add(hypothesis.hid)
        if kind not in KIND_TO_STRUCTURE:
            hypothesis.notes = hypothesis.notes + (
                f"structure defaulted: no declared structure for inversion kind {kind!r}",
            )
        out.append(hypothesis)
    return out


def register(
    existing: Sequence[Hypothesis],
    new: Hypothesis,
    *,
    allow_duplicate: bool = False,
) -> list[Hypothesis]:
    """Add a hypothesis, refusing one that restates an existing explanation.

    Returns a new list; the input is never mutated. Registering a hypothesis that
    is already present by id is a no-op rather than an error, so a replay can
    re-run this step without producing duplicates.
    """
    if any(h.hid == new.hid for h in existing):
        return list(existing)
    if not allow_duplicate:
        require_distinct(new, list(existing))
    return [*existing, new]


def groups(hypotheses: Iterable[Hypothesis]) -> dict[str, list[str]]:
    """Structural signature -> the hypotheses that share it."""
    found: dict[str, list[str]] = {}
    for hypothesis in hypotheses:
        found.setdefault(hypothesis.signature(), []).append(hypothesis.hid)
    return found


def distinct_pairs(hypotheses: Sequence[Hypothesis]) -> list[tuple[str, str, int]]:
    """Every pair with the number of structural fields on which they differ."""
    pairs: list[tuple[str, str, int]] = []
    for i, left in enumerate(hypotheses):
        for right in hypotheses[i + 1 :]:
            pairs.append((left.hid, right.hid, left.distance(right)))
    return pairs


def coverage(hypotheses: Iterable[Hypothesis]) -> dict[str, Any]:
    """How much of the explanation space the set actually occupies."""
    rows = list(hypotheses)
    return {
        "n": len(rows),
        "signatures": len({h.signature() for h in rows}),
        "mechanisms": dict(Counter(h.mechanism for h in rows)),
        "loci": dict(Counter(h.locus for h in rows)),
        "timescales": dict(Counter(h.timescale for h in rows)),
        "from_inversions": sum(1 for h in rows if h.from_inversion),
        "open": sum(1 for h in rows if h.status == "OPEN"),
    }
