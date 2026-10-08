"""Decomposition: raw sentence in, seven slots out.

The rule this module is built around: **inference never invents a value.** A slot
is filled only when a named cue actually fired, the cue is recorded as the slot's
provenance, and every slot the cues do not reach stays ``UNRESOLVED``. An
engine that guesses the scope of a question has quietly decided what the answer
is allowed to be, and that decision would then be invisible.

The reframing this enables, from the moonshot spec:

    "Can we predict operational bottlenecks?"
        -> referential: an operational bottleneck  (inferred, cue: problem noun)
        -> proposition: "We can predict operational bottlenecks"  (inferred, declarative rendering)
        -> scope: UNRESOLVED   -> blocking
        -> authority: UNRESOLVED -> blocking, and nobody has been asked

The decomposition is a cue table, not a parser. It is deliberately inspectable:
when it is wrong, the wrong answer sits next to the cue that produced it.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from ..core.question import (
    INFERRED,
    STATED,
    UNRESOLVED,
    SLOTS,
    SLOT_QUESTIONS,
    Question,
    SlotValue,
    make_question,
)
from ..ids import canon

# --------------------------------------------------------------------------- #
# Referential -- the problem noun the question is about
# --------------------------------------------------------------------------- #

_QUALIFIERS = (
    "operational", "critical", "major", "systemic", "hidden", "recurring", "chronic",
    "customer-facing", "customer facing", "high-impact", "high impact", "seasonal",
    "structural", "intermittent",
)

_PROBLEM_NOUNS = (
    "bottleneck", "delay", "failure", "outage", "defect", "latency", "backlog", "error",
    "churn", "downtime", "stockout", "rework", "escalation", "shortage", "discrepancy",
)

_REFERENT_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:(?:"
    + "|".join(re.escape(q) for q in sorted(_QUALIFIERS, key=len, reverse=True))
    + r")\s+)?(?:"
    + "|".join(_PROBLEM_NOUNS)
    + r")(?:s|es)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)

# --------------------------------------------------------------------------- #
# Proposition -- the declarative the question is really asserting
# --------------------------------------------------------------------------- #

_MODAL_FRONT = re.compile(r"^\s*(can|could|will|would|should|may|might)\s+(we|you|they|it|i)\s+", re.IGNORECASE)
_BE_FRONT = re.compile(r"^\s*(is|are|was|were|does|do|did)\s+", re.IGNORECASE)
_IT_IS_FRONT = re.compile(r"^\s*(is|was)\s+it\s+(possible|feasible|likely|true)\s+to\s+", re.IGNORECASE)
_HOW_FRONT = re.compile(r"^\s*how\s+(can|could|do)\s+we\s+", re.IGNORECASE)

# --------------------------------------------------------------------------- #
# Scope -- only an explicit bound counts. Illustrations of scale do not.
# --------------------------------------------------------------------------- #

_SCOPE_BOUNDS = (
    "one department", "a single department", "one workflow", "a single workflow",
    "one plant", "one site", "one team", "one product line", "one region",
    "one company", "a single company", "one customer", "one process",
    "one order type", "this quarter", "the last 12 months", "the last 90 days",
    "the last 6 months", "the last year", "one business unit", "one distribution centre",
    "one distribution center",
)

_AUTHORITY_CUES = (
    "authorized", "authorised", "approved by", "the owner is", "we own the data",
    "data owner", "signed off by", "validated by",
)

_OBLIGATION_CUES = (
    "must prove", "must show", "must demonstrate", "prove that", "demonstrate that",
    "evidence that", "we require that", "has to show",
)

_TEMPORAL_CUES = (
    "as of", "current", "real-time", "realtime", "today", "right now",
    "at the time of the event", "in production",
)

_CONSUMPTION_CUES = (
    "so that we can decide", "to decide", "management will", "the board will",
    "for the board", "for leadership", "for the coo", "for the cio",
    "so the team can", "to act on",
)


def _contains(text: str, phrase: str) -> bool:
    return canon(phrase) in canon(text)


def _first_contained(text: str, phrases: tuple[str, ...]) -> str | None:
    for phrase in phrases:
        if _contains(text, phrase):
            return phrase
    return None


def _declarative(raw: str) -> str:
    """Render an interrogative as the assertion it would be if it were a claim.

    A rendering heuristic, not a parser: the three prefix shapes below cover the
    interrogatives QSE is given in practice, and anything else is left as written
    with the question mark removed rather than mangled.
    """
    text = raw.strip().rstrip("?").strip()
    hit = _IT_IS_FRONT.match(text)
    if hit:
        return f"It {hit.group(1).lower()} {hit.group(2).lower()} to " + text[hit.end():]
    hit = _HOW_FRONT.match(text)
    if hit:
        return "We can " + text[hit.end():]
    hit = _MODAL_FRONT.match(text)
    if hit:
        return f"{hit.group(2).capitalize()} {hit.group(1).lower()} " + text[hit.end():]
    hit = _BE_FRONT.match(text)
    if hit:
        return text[hit.end():].strip()
    return text


# --------------------------------------------------------------------------- #
# Inference
# --------------------------------------------------------------------------- #

def infer_slots(raw: str) -> dict[str, SlotValue]:
    """Cue-driven inference. Anything not genuinely inferable stays UNRESOLVED."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("inference needs non-empty raw text")

    inferred: dict[str, SlotValue] = {
        name: SlotValue(None, provenance="unresolved", confidence=UNRESOLVED) for name in SLOTS
    }

    noun = _REFERENT_RE.search(raw)
    if noun:
        inferred["referential"] = SlotValue(
            value=noun.group(0),
            provenance="infer:problem-noun",
            confidence=INFERRED,
            note="the first problem noun in the sentence is taken as the referent",
        )

    declarative = _declarative(raw)
    if declarative.strip():
        inferred["proposition"] = SlotValue(
            value=declarative,
            provenance="infer:declarative",
            confidence=INFERRED,
            note="the interrogative rendered as the assertion it would make",
        )

    bound = _first_contained(raw, _SCOPE_BOUNDS)
    if bound:
        inferred["scope"] = SlotValue(
            value=bound,
            provenance="infer:scope-bound",
            confidence=INFERRED,
            note="an explicit bound was named; scale illustrations such as an industry name are not bounds",
        )

    cue = _first_contained(raw, _AUTHORITY_CUES)
    if cue:
        inferred["authority"] = SlotValue(value=cue, provenance="infer:authority-cue", confidence=INFERRED)

    cue = _first_contained(raw, _OBLIGATION_CUES)
    if cue:
        inferred["obligation"] = SlotValue(value=cue, provenance="infer:obligation-cue", confidence=INFERRED)

    cue = _first_contained(raw, _TEMPORAL_CUES)
    if cue:
        inferred["temporal"] = SlotValue(
            value=cue,
            provenance="infer:time-cue",
            confidence=INFERRED,
            note="names a currency, not a validity window; the window is still a question",
        )

    cue = _first_contained(raw, _CONSUMPTION_CUES)
    if cue:
        inferred["consumption"] = SlotValue(value=cue, provenance="infer:consumer-cue", confidence=INFERRED)

    return inferred


def decompose(
    raw: str,
    *,
    qid: str | None = None,
    version: int = 1,
    answers: Mapping[str, str] | None = None,
    trigger: str = "",
    parent: str | None = None,
    revision_of: str | None = None,
    revision_reason: str = "",
) -> Question:
    """Turn raw text plus any operator answers into a Question.

    ``answers`` wins over inference and is recorded as ``STATED`` with provenance
    ``operator``: a human said it. Inference is recorded as ``INFERRED`` with the
    rule that fired. Everything else is ``UNRESOLVED``.

    ``revision_of`` links a question to the question it replaced, which is what
    ``qse.ledger.receipts.why`` walks to reconstruct a question sequence.
    """
    slots = infer_slots(raw)
    if answers:
        for name, value in answers.items():
            if name not in SLOTS:
                raise ValueError(f"unknown slot {name!r}; a question has {', '.join(SLOTS)}")
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"answer for slot {name!r} is empty; omit it instead")
            slots[name] = SlotValue(
                value=value.strip(),
                provenance="operator",
                confidence=STATED,
                note="supplied by the operator",
            )
    return make_question(
        raw, slots, qid=qid, version=version, trigger=trigger,
        parent=parent, revision_of=revision_of, revision_reason=revision_reason,
    )


def seven_slot_report(question: Question) -> dict[str, dict[str, Any]]:
    """The seven slots in order, with what each holds and why.

    This is the artifact the acceptance test reads: it shows which slots are
    answered, which the engine inferred, and which nobody has answered yet.
    """
    report: dict[str, dict[str, Any]] = {}
    for name in SLOTS:
        slot = question.slots[name]
        report[name] = {
            "slot_question": SLOT_QUESTIONS[name],
            "value": slot.value,
            "confidence": slot.confidence,
            "provenance": slot.provenance,
            "note": slot.note,
            "filled": slot.filled,
        }
    return report


def render_report(question: Question) -> str:
    """The seven-slot report as plain text, for the CLI."""
    lines = [question.summary(), ""]
    for name, row in seven_slot_report(question).items():
        mark = "*" if row["filled"] else " "
        lines.append(f"{mark} {name:<12} {row['confidence']:<10} {row['value'] or '-- unanswered --'}")
        if row["filled"] and row["provenance"]:
            lines.append(f"  {'':<12} via {row['provenance']}")
    return "\n".join(lines)
