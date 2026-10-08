"""Blindspot reduction: what the engine did not know, before and after.

``BSR = blindspots_before - blindspots_after``.

* before = every ambiguity the seven-slot decomposition exposed
* after  = every slot still unfilled across every question in state

BSR can be **negative**, and that is worth keeping rather than clamping. A
revision that opens more slots than it closes has made the question worse, and a
metric that cannot say so is not measuring anything.
"""

from __future__ import annotations

from typing import Any

from ..control.state import State
from .question_quality import measure

__all__ = ["blindspots"]


def blindspots(state: State) -> dict[str, Any]:
    records = [rec for bucket in state.ambiguities.values() for rec in bucket]
    before = len(records)

    after = sum(len(q.unresolved()) for q in state.questions.values())

    closed: list[dict[str, Any]] = []
    for qid, bucket in state.ambiguities.items():
        question = state.questions.get(qid)
        if question is None:
            continue
        still_open = set(question.unresolved())
        for rec in bucket:
            if str(rec.get("slot", "")) not in still_open:
                closed.append(rec)

    exposed: list[str] = []
    for rec in sorted(closed, key=lambda r: (str(r.get("term", "")), str(r.get("kind", "")))):
        label = str(rec.get("term") or rec.get("kind") or "")
        if label and label not in exposed:
            exposed.append(label)

    value = before - after
    return measure(
        value,
        value,
        before,
        "blindspots_before - blindspots_after",
        before=before,
        after=after,
        exposed=exposed,
        still_open=sorted(
            {f"{qid}:{slot}" for qid, slots in state.unresolved_slots().items() for slot in slots}
        ),
    )
