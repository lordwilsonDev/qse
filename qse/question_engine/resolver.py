"""Resolver: answering a slot produces a new version, never an edit.

An answered question is a *different version of the same question*. Keeping the
earlier version means the record still shows what was asked before the answer
arrived, which is the only way to tell later whether the answer helped.
"""

from __future__ import annotations

from typing import Mapping

from ..core.question import SLOTS, STATED, Question, SlotValue, make_question


def resolve(question: Question, answers: Mapping[str, str], *, reason: str = "") -> Question:
    """Return ``question`` at version+1 with ``answers`` filled as STATED.

    Raises ``ValueError`` for an unknown slot name or a blank answer, because a
    blank answer would silently become an unresolved slot wearing a version bump.
    """
    if not answers:
        raise ValueError("resolve needs at least one answer")
    merged: dict[str, SlotValue] = dict(question.slots)
    for name, value in answers.items():
        if name not in SLOTS:
            raise ValueError(f"unknown slot {name!r}; a question has {', '.join(SLOTS)}")
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"answer for slot {name!r} is empty; omit it instead")
        merged[name] = SlotValue(
            value=value.strip(),
            provenance="operator",
            confidence=STATED,
            note=reason or "supplied by the operator",
        )
    return make_question(
        question.raw,
        merged,
        qid=question.qid,
        version=question.version + 1,
        parent=question.qid,
        revision_of=None,
        revision_reason=reason,
        trigger=reason,
    )


def open_slots(question: Question) -> list[str]:
    return question.unresolved()


def answered_in_version(previous: Question, current: Question) -> list[str]:
    """Slots that went from unanswered to answered between two versions."""
    return [name for name in SLOTS if previous.slots[name].filled is False and current.slots[name].filled]
