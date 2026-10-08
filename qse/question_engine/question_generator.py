"""Question generation: the engine's next question, and the reason it is next.

This is the module that turns the moonshot's loop into something a program can
run. Every question QSE asks is emitted here with three things attached: what
produced it (``derived_from``), why that matters (``trigger``), and a first
estimate of how much answering it would be worth (``information_gain``).

``information_gain`` here is a **first estimate from the trigger alone**:
severity for an ambiguity, a constant for a knowledge gap, the count of
explanations an experiment separates for a discrimination question. The control
layer recomputes this against the live state before anything is chosen, because
whether a question is worth asking depends on what has already been answered.
Keeping the two separate means the record shows both the initial estimate and
the final justification.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..core.question import Question
from ..ids import canon, new_id
from .ambiguity import SEVERITY_WEIGHT

KINDS = ("AMBIGUITY", "KNOWLEDGE_GAP", "DISCRIMINATION", "GENERALIZATION", "INTERVENTION")

#: First-estimate weights. Ordinal, not calibrated probabilities -- see the module
#: docstring. Documented here so that any change to them is a visible diff.
GAIN_KNOWLEDGE_GAP = 1.5
GAIN_GENERALIZATION = 2.0
GAIN_INTERVENTION = 2.5
GAIN_WEAK_DISCRIMINATION = 1.0
#: Answering an ambiguity in a BLOCKING slot is worth slightly more than the same
#: severity elsewhere, because consumption is gated on it.
GAIN_BLOCKING_SLOT_BONUS = 0.5
BLOCKING_SLOT_NAMES = ("referential", "proposition", "scope")


@dataclass
class GeneratedQuestion:
    gid: str
    text: str
    kind: str
    parent: str
    trigger: str
    derived_from: str
    rationale: str = ""
    slot_targeted: str | None = None
    information_gain: float = 1.0
    source_kind: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown generated-question kind {self.kind!r}; choose from {KINDS}")
        if not self.text.strip():
            raise ValueError("a generated question needs text")
        if not self.trigger.strip():
            raise ValueError("a generated question must record what triggered it")

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["gain_basis"] = "trigger-only first estimate; the control layer recomputes against state"
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "GeneratedQuestion":
        return cls(
            gid=str(payload["gid"]),
            text=str(payload["text"]),
            kind=str(payload["kind"]),
            parent=str(payload.get("parent", "")),
            trigger=str(payload.get("trigger", "")),
            derived_from=str(payload.get("derived_from", "")),
            rationale=str(payload.get("rationale", "")),
            slot_targeted=payload.get("slot_targeted"),
            information_gain=float(payload.get("information_gain", 1.0)),
            source_kind=str(payload.get("source_kind", "")),
        )


def _make(
    question: Question,
    text: str,
    *,
    kind: str,
    trigger: str,
    derived_from: str,
    rationale: str,
    gain: float,
    slot: str | None = None,
) -> GeneratedQuestion:
    return GeneratedQuestion(
        gid=new_id("G", question.qid, kind, text),
        text=text,
        kind=kind,
        parent=question.qid,
        trigger=trigger,
        derived_from=derived_from,
        rationale=rationale,
        slot_targeted=slot,
        information_gain=gain,
        source_kind=kind,
    )


def from_ambiguities(question: Question, ambiguities: Iterable[Any]) -> list[GeneratedQuestion]:
    """One question per ambiguity: the resolving question it already carries."""
    out: list[GeneratedQuestion] = []
    for item in ambiguities:
        severity = str(getattr(item, "severity", "MATERIAL"))
        slot = str(getattr(item, "slot", "")) or None
        gain = SEVERITY_WEIGHT.get(severity, 1.0)
        if slot in BLOCKING_SLOT_NAMES:
            gain += GAIN_BLOCKING_SLOT_BONUS
        kind = str(getattr(item, "kind", "UNDEFINED_TERM"))
        term = str(getattr(item, "term", ""))
        out.append(
            _make(
                question,
                str(getattr(item, "resolving_question", "")),
                kind="AMBIGUITY",
                trigger=f"{severity} {kind} in slot '{slot}'" + (f" on term '{term}'" if term else ""),
                derived_from=str(getattr(item, "aid", "")),
                rationale=str(getattr(item, "why", "")),
                gain=gain,
                slot=slot,
            )
        )
    return out


def from_gaps(question: Question, gaps: Sequence[str]) -> list[GeneratedQuestion]:
    """One question per named piece of missing evidence."""
    out: list[GeneratedQuestion] = []
    for gap in gaps:
        text = f"What observation would establish '{gap}', and what result would refute it?"
        out.append(
            _make(
                question,
                text,
                kind="KNOWLEDGE_GAP",
                trigger=f"missing evidence: {gap}",
                derived_from=str(gap),
                rationale="the evidence set does not cover this, so no hypothesis can be judged on it",
                gain=GAIN_KNOWLEDGE_GAP,
            )
        )
    return out


def from_discrimination(question: Question, experiments: Iterable[Any]) -> list[GeneratedQuestion]:
    """A question per experiment, asking which explanation its result separates."""
    out: list[GeneratedQuestion] = []
    for item in experiments:
        xid = str(getattr(item, "xid", ""))
        design = str(getattr(item, "design", ""))
        separates = tuple(getattr(item, "discriminates", ()) or ())
        if len(separates) >= 2:
            text = (
                f"Which of the {len(separates)} competing explanations does '{design}' separate, "
                "and what result would eliminate the losers?"
            )
            gain = float(len(separates))
            rationale = "this experiment can tell competing explanations apart rather than confirm one"
        else:
            text = (
                "What experiment would separate at least two of the competing explanations, "
                "rather than measuring only the leading one?"
            )
            gain = GAIN_WEAK_DISCRIMINATION
            rationale = "no experiment so far can distinguish explanations from each other"
        out.append(
            _make(
                question,
                text,
                kind="DISCRIMINATION",
                trigger=f"experiment {xid or '(unnamed)'} separates {len(separates)} explanation(s)",
                derived_from=xid,
                rationale=rationale,
                gain=gain,
            )
        )
    return out


def from_disagreements(question: Question, disagreements: Iterable[Any]) -> list[GeneratedQuestion]:
    """A generalisation question per preserved disagreement."""
    out: list[GeneratedQuestion] = []
    for item in disagreements:
        topic = str(getattr(item, "topic", "") or "the disagreement")
        did = str(getattr(item, "did", ""))
        positions = tuple(getattr(item, "positions", ()) or ())
        holders = sorted(
            {str(p.get("holder", "")) for p in positions if isinstance(p, Mapping) and p.get("holder")}
        )
        text = (
            f"Does the disagreement over '{topic}' generalise beyond the workflow where it was "
            "observed, or is it an artifact of that workflow?"
        )
        out.append(
            _make(
                question,
                text,
                kind="GENERALIZATION",
                trigger=f"unresolved disagreement over '{topic}' between {', '.join(holders) or 'unnamed parties'}",
                derived_from=did,
                rationale="a disagreement that is preserved rather than averaged away has to be located, or it will be rediscovered later",
                gain=GAIN_GENERALIZATION,
            )
        )
    return out


def from_supported(question: Question, hypotheses: Iterable[Any]) -> list[GeneratedQuestion]:
    """The prediction -> intervention step: a supported hypothesis is not an outcome."""
    out: list[GeneratedQuestion] = []
    for item in hypotheses:
        if str(getattr(item, "status", "")) != "SUPPORTED":
            continue
        hid = str(getattr(item, "hid", ""))
        text = (
            f"Does acting on '{getattr(item, 'text', 'the supported explanation')}' reduce the "
            "failure probability, and by how much against which baseline?"
        )
        out.append(
            _make(
                question,
                text,
                kind="INTERVENTION",
                trigger=f"hypothesis {hid} is supported by usable evidence but no intervention was tested",
                derived_from=hid,
                rationale="support for a prediction is not evidence that intervening changes the outcome",
                gain=GAIN_INTERVENTION,
            )
        )
    return out


def next_questions(
    question: Question,
    *,
    ambiguities: Iterable[Any] = (),
    gaps: Sequence[str] = (),
    experiments: Iterable[Any] = (),
    disagreements: Iterable[Any] = (),
    hypotheses: Iterable[Any] = (),
) -> list[GeneratedQuestion]:
    """Every candidate next question, deduped and ranked by first-estimate gain.

    Deduplication is by canonical text, keeping the highest-gain version: two
    triggers that produce the same question are one question, and the record keeps
    the stronger reason rather than both.
    """
    candidates = (
        from_ambiguities(question, ambiguities)
        + from_gaps(question, gaps)
        + from_discrimination(question, experiments)
        + from_disagreements(question, disagreements)
        + from_supported(question, hypotheses)
    )
    best: dict[str, GeneratedQuestion] = {}
    for item in candidates:
        key = canon(item.text)
        if not key:
            continue
        current = best.get(key)
        if current is None or (item.information_gain, item.gid) > (current.information_gain, current.gid):
            best[key] = item
    return sorted(best.values(), key=lambda g: (-g.information_gain, g.gid))
