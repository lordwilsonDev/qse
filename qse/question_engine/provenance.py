"""Slot provenance: where every filled slot came from, and whether that is known.

A filled slot with no provenance is worse than an empty one, because it looks
answered. ``lossless`` is the check that no such slot exists: every filled slot
names how it got there and which confidence band it sits in.
"""

from __future__ import annotations

from typing import Any

from ..core.question import CONFIDENCES, INFERRED, SLOTS, STATED, UNRESOLVED, Question

#: Provenance strings that mean "nobody established this".
_EMPTY = ("", "unresolved", "unknown", "none")


def slot_provenance(question: Question) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "value": question.slots[name].value,
            "confidence": question.slots[name].confidence,
            "provenance": question.slots[name].provenance,
            "note": question.slots[name].note,
            "filled": question.slots[name].filled,
        }
        for name in SLOTS
    }


def provenance_summary(question: Question) -> dict[str, list[str]]:
    stated, inferred, unresolved = [], [], []
    for name in SLOTS:
        slot = question.slots[name]
        if not slot.filled or slot.confidence == UNRESOLVED:
            unresolved.append(name)
        elif slot.confidence == STATED:
            stated.append(name)
        elif slot.confidence == INFERRED:
            inferred.append(name)
        else:  # pragma: no cover - SlotValue already rejects unknown confidences
            unresolved.append(name)
    return {"stated": stated, "inferred": inferred, "unresolved": unresolved}


def unprovenanced(question: Question, slot: str) -> bool:
    """True when a filled slot does not say where its value came from."""
    if slot not in SLOTS:
        raise KeyError(f"unknown slot {slot!r}")
    value = question.slots[slot]
    if not value.filled:
        return False
    return value.provenance.strip().lower() in _EMPTY or value.confidence not in CONFIDENCES


def lossless(question: Question) -> bool:
    """Every filled slot carries a named provenance and a known confidence."""
    return not any(unprovenanced(question, name) for name in SLOTS)


def audit(questions: list[Question]) -> dict[str, Any]:
    """Which questions in a set carry an unprovenanced slot."""
    bad: dict[str, list[str]] = {}
    for question in questions:
        missing = [name for name in SLOTS if unprovenanced(question, name)]
        if missing:
            bad[question.qid] = missing
    return {"lossless": not bad, "unprovenanced": bad, "checked": len(questions)}
