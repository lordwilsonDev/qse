"""MoIE — Mixture of Inversion Experts.

The failure this avoids: asking seven instances the same question and calling the
overlap "confidence". Here every expert runs a **different operator**, so the
experts disagree because they are looking for different things, not because they
are noisy.

There is no vote anywhere in this module, and that is a design constraint rather
than an omission. Agreement is *reported*; it is never *counted* into a decision.
``measure()`` returns what the experts found, including the disagreements, and
stops there. Selection happens in ``qse.reasoning.synthesis``, on evidence.

Two opposition detectors run, and they are deliberately different in kind:

* ``KIND_OPPOSITION`` — a declared, symmetric relation between inversion kinds.
  It is small because it lists only oppositions QSE can actually produce; a
  longer table with entries that can never both fire would be decoration.
* ``TEXT_OPPOSITION`` — word-level pairs searched with word boundaries, so
  "insufficient" does not match "sufficient" and "unobserved" does not match
  "observed".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from ..core.question import Question
from ..ids import canon
from .ail import AILEngine
from .operators import OPERATORS, OPERATOR_FUNCTIONS, Inversion

#: operator -> what this perspective structurally cannot see. The blind spot is
#: a property of the operator, not of the run, so it is the same every time.
BLIND_SPOTS: dict[str, str] = {
    "axiom_inverter": "whether the axiom is false for a reason the available data could show",
    "scope_attacker": "mechanisms that act identically inside and outside the declared scope",
    "causal_attacker": "mechanisms that have no directional story to reverse",
    "temporal_attacker": "regime changes that happened before the data window opens",
    "authority_attacker": "mechanisms that no party has an interest in defining either way",
    "measurement_attacker": "effects the measurement cannot observe at all, at any resolution",
    "failure_attacker": "failure modes that produced no record and left no trace to count",
}

#: operator -> the assumptions its inversions rely on.
NEW_ASSUMPTIONS: dict[str, tuple[str, ...]] = {
    "axiom_inverter": ("the held-out period is comparable to the fitting period",),
    "scope_attacker": ("workflows can be separated cleanly enough to estimate an effect in each",),
    "causal_attacker": ("timestamps are recorded with less error than the interval being measured",),
    "temporal_attacker": ("a regime change leaves a distributional signature",),
    "authority_attacker": ("a second, independent definition of failure can be obtained",),
    "measurement_attacker": ("the instrument's true resolution is knowable from its records",),
    "failure_attacker": ("record counts are a usable proxy for activity",),
}

#: operator -> the experiment its perspective implies.
NEW_EXPERIMENTS: dict[str, tuple[str, ...]] = {
    "axiom_inverter": ("hold out the most recent third of history and score the rule on it",),
    "scope_attacker": ("estimate the effect per workflow and compare with the pooled effect",),
    "causal_attacker": ("count cases where the effect's timestamp precedes the cause's",),
    "temporal_attacker": ("scan candidate change points and test the split",),
    "authority_attacker": ("recompute the ranking under two independently supplied definitions",),
    "measurement_attacker": (
        "recompute the statistic on timestamps rounded to the instrument's real resolution",
        "recompute the association within each group and compare signs with the pooled value",
    ),
    "failure_attacker": (
        "count records per step per period against the downstream outcome",
        "compare recorded failure rate with reporting load at constant demand",
    ),
}

#: Declared symmetric opposition between kinds QSE can actually produce.
KIND_OPPOSITION: tuple[tuple[str, str], ...] = (
    ("DATA_INSUFFICIENT", "UNOBSERVED_FAILURE"),
)

#: Word-level oppositions. Searched with word boundaries so that "insufficient"
#: and "unobserved" do not match their own opposites.
TEXT_OPPOSITION: tuple[tuple[str, str], ...] = (
    ("insufficient", "sufficient"),
    ("cannot be detected", "can be detected"),
    ("does not generalise", "generalises"),
    ("artifact", "real"),
    ("stale", "current"),
    ("reversed", "forward"),
    ("unobserved", "observed"),
    ("unrecorded", "recorded"),
)


@dataclass
class ExpertReport:
    operator: str
    question: str
    inversions: list[Inversion] = field(default_factory=list)
    unique_discoveries: list[str] = field(default_factory=list)
    new_assumptions: list[str] = field(default_factory=list)
    new_experiments: list[str] = field(default_factory=list)
    blind_spots: list[str] = field(default_factory=list)
    contradictions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "question": self.question,
            "inversions": [i.to_dict() for i in self.inversions],
            "unique_discoveries": list(self.unique_discoveries),
            "new_assumptions": list(self.new_assumptions),
            "new_experiments": list(self.new_experiments),
            "blind_spots": list(self.blind_spots),
            "contradictions": list(self.contradictions),
            "kinds": sorted({i.kind for i in self.inversions}),
        }


#: The seven experts. Each entry is a DIFFERENT operator function; no two experts
#: run the same one, which is the whole point.
EXPERTS: dict[str, Any] = {name: OPERATOR_FUNCTIONS[name] for name in OPERATORS}


def _opposes(a: str, b: str) -> tuple[str, str] | None:
    """Return the opposition that fires between two statements, or None."""
    low_a, low_b = canon(a), canon(b)
    for left, right in TEXT_OPPOSITION:
        if re.search(rf"\b{re.escape(left)}\b", low_a) and re.search(rf"\b{re.escape(right)}\b", low_b):
            return (left, right)
        if re.search(rf"\b{re.escape(right)}\b", low_a) and re.search(rf"\b{re.escape(left)}\b", low_b):
            return (right, left)
    return None


def _kind_opposes(a: str, b: str) -> tuple[str, str] | None:
    for left, right in KIND_OPPOSITION:
        if {a, b} == {left, right}:
            return (left, right)
    return None


def convene(
    question: Question,
    ail: AILEngine,
    *,
    known_assumptions: Sequence[str] = (),
) -> list[ExpertReport]:
    """Run every expert over the axioms, each with its own operator.

    Uses the *gated* inversions from AIL, so an expert never argues from a
    candidate that has no testable consequence.
    """
    accepted = ail.invert()
    known = {canon(a) for a in known_assumptions}
    reports: list[ExpertReport] = []
    for name in OPERATORS:
        mine = [inv for inv in accepted if inv.operator == name]
        assumptions = [a for a in NEW_ASSUMPTIONS.get(name, ()) if canon(a) not in known]
        reports.append(
            ExpertReport(
                operator=name,
                question=question.qid,
                inversions=mine,
                unique_discoveries=[],
                new_assumptions=list(assumptions),
                new_experiments=list(NEW_EXPERIMENTS.get(name, ())),
                blind_spots=[BLIND_SPOTS[name]] if name in BLIND_SPOTS else [],
            )
        )
    return _mark_unique(reports)


def _mark_unique(reports: list[ExpertReport]) -> list[ExpertReport]:
    """An inversion is a unique discovery when no OTHER expert produced its kind."""
    owners: dict[str, set[str]] = {}
    for report in reports:
        for kind in {inv.kind for inv in report.inversions}:
            owners.setdefault(kind, set()).add(report.operator)
    for report in reports:
        report.unique_discoveries = sorted(
            {inv.iid for inv in report.inversions if len(owners.get(inv.kind, set())) == 1}
        )
    return reports


def measure(reports: Iterable[ExpertReport]) -> dict[str, Any]:
    """Report what the experts found. Reports disagreement; never resolves it."""
    rows = list(reports)
    kind_owners: dict[str, list[str]] = {}
    for report in rows:
        for kind in {inv.kind for inv in report.inversions}:
            kind_owners.setdefault(kind, []).append(report.operator)

    agreement = [
        {"kind": kind, "operators": sorted(ops), "n": len(ops)}
        for kind, ops in sorted(kind_owners.items())
        if len(ops) > 1
    ]

    contradictions: list[dict[str, Any]] = []
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            for a in left.inversions:
                for b in right.inversions:
                    by_text = _opposes(a.statement, b.statement)
                    by_kind = _kind_opposes(a.kind, b.kind)
                    if not by_text and not by_kind:
                        continue
                    contradictions.append(
                        {
                            "left": left.operator,
                            "right": right.operator,
                            "left_kind": a.kind,
                            "right_kind": b.kind,
                            "opposition": list(by_text or by_kind or ()),
                            "detected_by": "text" if by_text else "kind",
                            "left_statement": a.statement,
                            "right_statement": b.statement,
                        }
                    )

    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for row in contradictions:
        key = (row["left"], row["right"], row["left_statement"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)

    blind = sorted({spot for report in rows for spot in report.blind_spots})
    return {
        "experts": len(rows),
        "operators": [report.operator for report in rows],
        "agreement": agreement,
        "disagreement": deduped,
        "contradictions": deduped,
        "unique": {report.operator: list(report.unique_discoveries) for report in rows},
        "unique_total": sum(len(report.unique_discoveries) for report in rows),
        "blind_spots": blind,
        "new_assumptions": sorted({a for report in rows for a in report.new_assumptions}),
        "new_experiments": sorted({x for report in rows for x in report.new_experiments}),
        # Stated explicitly so a reader does not have to infer the absence.
        "vote": None,
        "vote_note": "MoIE never tallies; agreement is reported, not counted into a decision",
    }
