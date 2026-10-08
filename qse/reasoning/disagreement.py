"""Disagreement, preserved on purpose.

Acceptance requires "disagreement preserved". The cheap way to satisfy that is to
print the experts' answers next to each other. The real requirement is that a
disagreement survives into the record as an object with a topic, positions, and
the evidence each position rests on — and that nothing downstream is allowed to
delete it because a majority formed.

So: ``find`` constructs disagreements, ``preserve`` returns them with the
preserved flag set, and ``unresolved`` is what a caller reads to learn what the
investigation has *not* settled. Nothing here collapses positions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Sequence

from ..core.evidence import Evidence
from ..core.hypothesis import STRUCTURE_FIELDS, Hypothesis
from ..ids import new_id


@dataclass
class Disagreement:
    did: str
    topic: str
    positions: list[dict[str, Any]] = field(default_factory=list)
    preserved: bool = True
    resolved_by: str | None = None

    def holders(self) -> list[str]:
        return [str(p.get("holder", "")) for p in self.positions]

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["holders"] = self.holders()
        return out


def _usable_for(evidence: Iterable[Evidence], hid: str) -> tuple[list[Evidence], list[Evidence]]:
    mine = [e for e in evidence if e.hypothesis == hid and e.usable()]
    return [e for e in mine if e.supports], [e for e in mine if not e.supports]


def _topic(left: Hypothesis, right: Hypothesis) -> str:
    differing = [f for f in STRUCTURE_FIELDS if getattr(left, f) != getattr(right, f)]
    return (
        f"does the cause lie in {left.locus} via {left.mechanism}, "
        f"or in {right.locus} via {right.mechanism} "
        f"(differing on {', '.join(differing)})"
    )


def find(
    hypotheses: Sequence[Hypothesis],
    evidence: Iterable[Evidence],
) -> list[Disagreement]:
    """A disagreement per pair of open hypotheses that the evidence supports both ways.

    The rule, stated plainly: both hypotheses must have at least one usable
    observation *for* them, and at least one usable observation *against* one of
    them. Two hypotheses with no evidence at all are not disagreeing; they are
    both untested, which is a different thing and is reported as such elsewhere.
    """
    evidence = list(evidence)
    rows = [h for h in hypotheses if h.status == "OPEN"]
    out: list[Disagreement] = []
    for i, left in enumerate(rows):
        for right in rows[i + 1 :]:
            left_for, left_against = _usable_for(evidence, left.hid)
            right_for, right_against = _usable_for(evidence, right.hid)
            if not left_for or not right_for:
                continue
            if not (left_against or right_against):
                continue
            positions = [
                {
                    "holder": left.hid,
                    "position": left.text,
                    "basis": [e.eid for e in left_for],
                    "against": [e.eid for e in left_against],
                    "weight": sum(e.weight() for e in left_for),
                },
                {
                    "holder": right.hid,
                    "position": right.text,
                    "basis": [e.eid for e in right_for],
                    "against": [e.eid for e in right_against],
                    "weight": sum(e.weight() for e in right_for),
                },
            ]
            topic = _topic(left, right)
            out.append(
                Disagreement(
                    did=new_id("DIS", left.hid, right.hid, topic),
                    topic=topic,
                    positions=positions,
                    preserved=True,
                )
            )
    return out


def preserve(disagreements: Iterable[Disagreement]) -> list[Disagreement]:
    """Return disagreements with the preserved flag held at True.

    It exists so a caller has an explicit place to record that preservation was
    applied, and so a future edit that wanted to drop a disagreement would have
    to change this function rather than change nothing.
    """
    out: list[Disagreement] = []
    for disagreement in disagreements:
        disagreement.preserved = True
        out.append(disagreement)
    return out


def unresolved(disagreements: Iterable[Disagreement]) -> list[Disagreement]:
    return [d for d in disagreements if d.resolved_by is None]


def summary(disagreements: Iterable[Disagreement]) -> dict[str, Any]:
    rows = list(disagreements)
    return {
        "n": len(rows),
        "preserved": sum(1 for d in rows if d.preserved),
        "resolved": sum(1 for d in rows if d.resolved_by is not None),
        "topics": [d.topic for d in rows],
    }
