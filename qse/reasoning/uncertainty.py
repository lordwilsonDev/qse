"""Uncertainty: naming what is not known, and what would reduce it.

An uncertainty is only useful if it comes with the observation that would shrink
it. Every entry here carries ``reduces_with`` for that reason; an uncertainty
with no route to reduction is a worry, not a work item.

``entropy_level`` is explicitly ordinal. It counts and weights uncertainty
magnitudes and divides by the number of uncertainties, so it answers "is this
getting better or worse" and does not pretend to answer "how probable is this".
Calling it entropy is a two-hundred-year-old habit; the docstring is where the
habit is paid for.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from ..core.evidence import Evidence
from ..core.hypothesis import Hypothesis
from ..core.question import SLOT_QUESTIONS, Question
from ..ids import new_id

KINDS = ("EPISTEMIC", "MODEL", "MEASUREMENT", "SCOPE", "AUTHORITY", "DESIGN")
MAGNITUDES = ("HIGH", "MEDIUM", "LOW")

#: ambiguity kind -> the uncertainty kind it produces. Anything unmapped lands on
#: EPISTEMIC, which is the honest default: the engine does not know.
_AMBIGUITY_TO_UNCERTAINTY = {
    "UNDEFINED_TERM": "EPISTEMIC",
    "CONTESTED_DEFINITION": "AUTHORITY",
    "MISSING_AUTHORITY": "AUTHORITY",
    "UNBOUNDED_SCOPE": "SCOPE",
    "RELATIVE_TIME": "MEASUREMENT",
    "VAGUE_QUANTIFIER": "MEASUREMENT",
    "UNMEASURED_OUTCOME": "MEASUREMENT",
    "MODALITY_MISMATCH": "MODEL",
}

#: ambiguity severity -> uncertainty magnitude.
_SEVERITY_TO_MAGNITUDE = {"BLOCKING": "HIGH", "MATERIAL": "MEDIUM", "MINOR": "LOW"}

#: slot -> the kind of uncertainty an unresolved slot represents.
_SLOT_KIND = {
    "referential": "EPISTEMIC",
    "proposition": "MODEL",
    "scope": "SCOPE",
    "authority": "AUTHORITY",
    "obligation": "EPISTEMIC",
    "temporal": "MEASUREMENT",
    "consumption": "DESIGN",
}

#: magnitude -> the ordinal weight used by entropy_level.
_ORDINAL = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}


@dataclass(frozen=True)
class Uncertainty:
    uid: str
    about: str
    kind: str
    reduces_with: str
    magnitude: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown uncertainty kind {self.kind!r}; choose from {KINDS}")
        if self.magnitude not in MAGNITUDES:
            raise ValueError(f"unknown magnitude {self.magnitude!r}; choose from {MAGNITUDES}")
        if not self.about.strip():
            raise ValueError("an uncertainty needs something to be about")
        if not self.reduces_with.strip():
            raise ValueError(
                "an uncertainty with no route to reduction is a worry, not a work item; "
                "say what observation would shrink it"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _make(about: str, kind: str, magnitude: str, reduces_with: str, source: str) -> Uncertainty:
    return Uncertainty(
        uid=new_id("UNC", source, kind, about),
        about=about,
        kind=kind,
        reduces_with=reduces_with,
        magnitude=magnitude,
    )


def survey(
    question: Question,
    *,
    ambiguities: Sequence[Any] = (),
    hypotheses: Sequence[Hypothesis] = (),
    evidence: Iterable[Evidence] = (),
    gaps: Sequence[str] = (),
) -> list[Uncertainty]:
    """Every uncertainty the run can currently name, deduped by id."""
    evidence = list(evidence)
    out: list[Uncertainty] = []

    for slot in question.unresolved():
        out.append(
            _make(
                about=f"slot '{slot}' has not been filled",
                kind=_SLOT_KIND.get(slot, "EPISTEMIC"),
                magnitude="HIGH" if slot in question.blocking() else "MEDIUM",
                reduces_with=SLOT_QUESTIONS[slot],
                source=f"{question.qid}:{slot}",
            )
        )

    for ambiguity in ambiguities:
        kind = _AMBIGUITY_TO_UNCERTAINTY.get(str(getattr(ambiguity, "kind", "")), "EPISTEMIC")
        severity = str(getattr(ambiguity, "severity", "MINOR"))
        out.append(
            _make(
                about=str(getattr(ambiguity, "why", "")) or str(getattr(ambiguity, "term", "ambiguity")),
                kind=kind,
                magnitude=_SEVERITY_TO_MAGNITUDE.get(severity, "LOW"),
                reduces_with=str(getattr(ambiguity, "resolving_question", "")) or "resolve the ambiguity",
                source=str(getattr(ambiguity, "aid", "ambiguity")),
            )
        )

    for hypothesis in hypotheses:
        mine = [e for e in evidence if e.hypothesis == hypothesis.hid and e.usable()]
        if not mine:
            out.append(
                _make(
                    about=f"{hypothesis.hid} has no usable observation for or against it",
                    kind="EPISTEMIC",
                    magnitude="HIGH",
                    reduces_with=f"run an experiment that can refute {hypothesis.hid}",
                    source=hypothesis.hid,
                )
            )

    for item in evidence:
        if item.kind == "CONTESTED":
            out.append(
                _make(
                    about=f"{item.eid} is contested: {item.claim}",
                    kind="MEASUREMENT",
                    magnitude="MEDIUM",
                    reduces_with="re-measure independently and compare with the original record",
                    source=item.eid,
                )
            )

    for gap in gaps:
        out.append(
            _make(
                about=str(gap),
                kind="EPISTEMIC",
                magnitude="MEDIUM",
                reduces_with="obtain the missing series or declare the scope in which it is not needed",
                source=f"gap:{gap}",
            )
        )

    seen: set[str] = set()
    deduped: list[Uncertainty] = []
    for item in out:
        if item.uid in seen:
            continue
        seen.add(item.uid)
        deduped.append(item)
    return deduped


def load(uncertainties: Iterable[Uncertainty]) -> dict[str, Any]:
    rows = list(uncertainties)
    return {
        "n": len(rows),
        "by_kind": dict(Counter(u.kind for u in rows)),
        "by_magnitude": dict(Counter(u.magnitude for u in rows)),
        "ordinal": entropy_level(rows),
        "high": [u.uid for u in rows if u.magnitude == "HIGH"],
    }


def entropy_level(uncertainties: Iterable[Uncertainty]) -> float:
    """An ORDINAL measure in [0, 3]: mean magnitude weight, not a probability."""
    rows = list(uncertainties)
    if not rows:
        return 0.0
    return round(sum(_ORDINAL[u.magnitude] for u in rows) / len(rows), 6)
