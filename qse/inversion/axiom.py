"""Axioms: what a question would have to believe before it could be true.

AIL does not invert *the question*. It inverts the axioms the question rests on.
"What if the opposite were true?" aimed at a sentence produces wordplay; aimed
at an axiom it produces a claim you can go and test.

What is real here: the extraction is a deterministic table over the seven slots
plus the parsed proposition, and every axiom records *why* it was extracted, so
a reader can disagree with the rule rather than with the conclusion.

What is assumed: that a question's written form exposes its axioms. A question
whose real axiom was never written down will produce axioms about the words
instead, and QSE will invert those. That is a limit of the method, not a bug.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..core.proposition import Proposition
from ..core.question import Question
from ..ids import new_id

#: What kind of belief an axiom is.
KINDS = (
    "CAUSAL", "MEASUREMENT", "SCOPE", "CAPACITY",
    "COORDINATION", "TEMPORAL", "AUTHORITY", "FAILURE",
)

#: slot -> (kind, template). ``{subject}`` and ``{value}`` are substituted.
_SLOT_AXIOMS: dict[str, tuple[str, str]] = {
    "referential": ("SCOPE", "the phrase '{value}' names one thing with one shared definition"),
    "proposition": ("CAUSAL", "the claim '{value}' is the claim that actually matters"),
    "scope": ("SCOPE", "what is observed inside '{value}' generalises to the whole declared scope"),
    "authority": ("AUTHORITY", "the named authority can decide what counts as failure"),
    "obligation": ("CAPACITY", "the required proof is obtainable from evidence that exists"),
    "temporal": ("TEMPORAL", "the definition of failure was the same at the time the events occurred"),
    "consumption": ("COORDINATION", "the consumer of this result will act on it rather than file it"),
}

#: modality -> the verb phrase the headline axiom is written with.
_MODALITY_VERB = {
    "PREDICTABLE": "predicted",
    "DETECTABLE": "detected",
    "FEASIBLE": "built",
    "CAUSAL": "explained",
    "COMPARATIVE": "ranked",
    "DESCRIPTIVE": "described",
}


@dataclass(frozen=True)
class Axiom:
    aid: str
    text: str
    kind: str
    source_question: str
    because: str

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown axiom kind {self.kind!r}; choose from {KINDS}")
        if not self.text.strip():
            raise ValueError("an axiom needs text")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _make(text: str, kind: str, question: Question, because: str) -> Axiom:
    return Axiom(
        aid=new_id("AXI", question.qid, kind, text),
        text=text,
        kind=kind,
        source_question=question.qid,
        because=because,
    )


def _subject(question: Question, proposition: Proposition | None) -> str:
    """The shortest honest name for what the question is about."""
    if proposition is not None and proposition.subject.strip():
        return proposition.subject.strip().rstrip("?").strip()
    if question.value("referential"):
        return str(question.value("referential")).strip()
    return question.raw.strip().rstrip("?").strip()


def extract(question: Question, *, proposition: Proposition | None = None) -> list[Axiom]:
    """Mine the axioms a question rests on. Deterministic, deduped by ``aid``.

    The headline axiom is always present: it is the belief that the subject can
    be *done to* using historical data, which is exactly the belief every
    "can we predict / detect / explain X" question smuggles in. Everything after
    it comes from a slot the question has actually filled.
    """
    subject = _subject(question, proposition)
    modality = proposition.modality if proposition is not None else "DESCRIPTIVE"
    verb = _MODALITY_VERB.get(modality, "described")

    axioms: list[Axiom] = [
        _make(
            f"{subject} can be {verb} from historical data",
            "MEASUREMENT" if modality in ("PREDICTABLE", "DETECTABLE") else "CAUSAL",
            question,
            f"the question is phrased in the {modality} modality",
        ),
        _make(
            f"{subject} fails in the ways the recorded events already show",
            "FAILURE",
            question,
            "every investigation of a failure assumes the observed failures are the failures",
        ),
    ]

    for slot, (kind, template) in _SLOT_AXIOMS.items():
        value = question.value(slot)
        if not value or not str(value).strip():
            continue
        axioms.append(
            _make(
                template.format(subject=subject, value=str(value).strip()),
                kind,
                question,
                f"slot '{slot}' was filled with the decomposition's value",
            )
        )

    seen: set[str] = set()
    out: list[Axiom] = []
    for axiom in axioms:
        if axiom.aid in seen:
            continue
        seen.add(axiom.aid)
        out.append(axiom)
    return out
