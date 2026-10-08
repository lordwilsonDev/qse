"""What the question actually claims, separated from how it is phrased.

The defect this exists to catch: *"Can we predict operational bottlenecks?"* and
*"Does acting on a precursor reduce failure probability?"* are different
propositions wearing the same sentence. QSE records a proposition as
(subject, predicate, modality, quantifier, absence) so a revision can show that
**the modality changed** rather than argue about the wording.

The classifier is deliberately a cue-word table, not a model call: it is
deterministic, it is testable, and when it is wrong the wrong answer is written
down next to the cue that produced it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import canon

MODALITIES = ("FEASIBLE", "PREDICTABLE", "DETECTABLE", "CAUSAL", "COMPARATIVE", "DESCRIPTIVE")
QUANTIFIERS = ("ALL", "NONE", "SOME", "UNSPECIFIED")

#: Cue table, longest cue first so "lead to" beats "lead".
_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("PREDICTABLE", ("predict", "forecast", "anticipate", "ahead of", "precursor")),
    ("DETECTABLE", ("detect", "identify", "find", "flag", "surface", "determine")),
    ("CAUSAL", ("cause", "reduce", "improve", "increase", "lower", "prevent", "drive", "impact of")),
    ("COMPARATIVE", ("better than", "more than", "less than", "faster", "outperform", "highest-leverage", "highest leverage")),
    ("FEASIBLE", ("build", "design", "engineer", "is it possible", "can we", "feasible")),
)

_ABSENCE = ("no ", "none", "never", "absent", "without", "does not exist", "do not exist", "missing")

_QUANT: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ALL", ("all ", "every", "each ", "any ")),
    ("NONE", ("no ", "none", "never")),
    ("SOME", ("some ", "certain", "a few", "many", "several")),
)

_WH = re.compile(r"^\s*(can|could|does|do|is|are|will|would|should|how|what|why|when|who)\b", re.I)

# ``Can we predict X?`` is not a claim whose subject is "we". Leaving the pronoun in
# made every generated statement read as first-person narration -- "the data is
# insufficient to support 'we predict bottlenecks'" -- so the asker is stripped.
_LEAD_PRONOUN = re.compile(r"^\s*(we|i|you|they|one|it|the company|management|the team)\b\s*", re.I)


@dataclass(frozen=True)
class Proposition:
    text: str
    subject: str
    predicate: str
    modality: str = "DESCRIPTIVE"
    quantifier: str = "UNSPECIFIED"
    absence: bool = False
    cues: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.modality not in MODALITIES:
            raise ValueError(f"unknown modality {self.modality!r}")
        if self.quantifier not in QUANTIFIERS:
            raise ValueError(f"unknown quantifier {self.quantifier!r}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Proposition":
        return cls(
            text=str(payload["text"]),
            subject=str(payload.get("subject", "")),
            predicate=str(payload.get("predicate", "")),
            modality=str(payload.get("modality", "DESCRIPTIVE")),
            quantifier=str(payload.get("quantifier", "UNSPECIFIED")),
            absence=bool(payload.get("absence", False)),
            cues=tuple(str(c) for c in payload.get("cues", ())),
        )

    def modality_changed(self, other: "Proposition") -> bool:
        """True when two phrasings claim different *kinds* of thing."""
        return self.modality != other.modality and (self.predicate != other.predicate)


def _subject_and_predicate(text: str) -> tuple[str, str]:
    stripped = _WH.sub("", text.strip()).strip()
    stripped = _LEAD_PRONOUN.sub("", stripped).strip().rstrip("?").strip()
    for splitter in (" that ", " whether ", " if ", " to "):
        head, sep, tail = stripped.partition(splitter)
        if sep and head.strip() and tail.strip():
            return head.strip(), tail.strip()
    return stripped, stripped


def parse_proposition(text: str) -> Proposition:
    """Classify a sentence. Deterministic; the cues that fired are recorded."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("a proposition needs non-empty text")
    low = canon(text)
    hits: list[str] = []
    modality = "DESCRIPTIVE"
    for name, cues in _CUES:
        found = [c for c in cues if c in low]
        if found:
            modality = name
            hits.extend(found)
            break
    quantifier = "UNSPECIFIED"
    for name, cues in _QUANT:
        found = [c for c in cues if c in low]
        if found:
            quantifier = name
            hits.extend(found)
            break
    absence = any(cue in low for cue in _ABSENCE)
    subject, predicate = _subject_and_predicate(text)
    return Proposition(
        text=text.strip(),
        subject=subject,
        predicate=predicate,
        modality=modality,
        quantifier=quantifier,
        absence=absence,
        cues=tuple(sorted(set(hits))),
    )
