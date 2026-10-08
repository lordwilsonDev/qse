"""The Question Object: one raw sentence, seven slots, and the record of how
each slot came to hold what it holds.

The point of the slots is that an underspecified question is not rejected, it is
*described*. "Can we predict operational bottlenecks?" is a legal QSE input; it
arrives with five of seven slots unresolved, an ambiguity per unresolved slot,
and a `blocking()` list that tells the controller the investigation may not
consume it yet.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import iso, new_id, utcnow

SLOTS = (
    "referential",   # 1. what exactly is referred to
    "proposition",   # 2. what is actually being claimed
    "scope",         # 3. over what the claim ranges
    "authority",     # 4. who may define and validate it
    "obligation",    # 5. what must be proven, what must never be claimed
    "temporal",      # 6. was the definition valid when the event occurred
    "consumption",   # 7. who consumes it, and what happens if it is wrong
)

SLOT_QUESTIONS = {
    "referential": "What exactly is being referred to?",
    "proposition": "What is actually being claimed, and in what modality?",
    "scope": "Over what does the claim range?",
    "authority": "Who is authorized to define failure and validate the result?",
    "obligation": "What must be proven, and what must never be claimed?",
    "temporal": "Is the evidence current, and was the definition valid when the event occurred?",
    "consumption": "Who consumes the result, what decision will they make, and what happens if it is wrong?",
}

#: Slots without which a defensible investigation cannot start.
BLOCKING_SLOTS = ("referential", "proposition", "scope")

STATED = "STATED"
INFERRED = "INFERRED"
UNRESOLVED = "UNRESOLVED"
CONFIDENCES = (STATED, INFERRED, UNRESOLVED)


@dataclass(frozen=True)
class SlotValue:
    """A slot's content plus how it got there. Provenance is not optional."""

    value: str | None
    provenance: str = "unresolved"
    confidence: str = UNRESOLVED
    note: str = ""

    @property
    def filled(self) -> bool:
        return bool(self.value and self.value.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Any) -> "SlotValue":
        if isinstance(payload, SlotValue):
            return payload
        if payload is None or isinstance(payload, str):
            return cls(payload)
        if not isinstance(payload, Mapping):
            raise ValueError("a slot value must be a string, null, or an object")
        if str(payload.get("confidence", UNRESOLVED)) not in CONFIDENCES:
            raise ValueError(f"unknown confidence {payload.get('confidence')!r}")
        return cls(
            value=None if payload.get("value") is None else str(payload["value"]),
            provenance=str(payload.get("provenance", "unresolved")),
            confidence=str(payload.get("confidence", UNRESOLVED)),
            note=str(payload.get("note", "")),
        )


@dataclass
class Question:
    qid: str
    version: int
    raw: str
    slots: dict[str, SlotValue]
    parent: str | None = None
    revision_of: str | None = None
    revision_reason: str = ""
    created: str = ""
    #: questions this one was generated to answer, and the trigger that generated it
    trigger: str = ""

    def __post_init__(self) -> None:
        if set(self.slots) != set(SLOTS):
            raise ValueError(f"a question needs exactly the seven slots; got {sorted(self.slots)}")
        self.slots = {k: SlotValue.from_dict(v) for k, v in self.slots.items()}
        if self.version < 1:
            raise ValueError("version must be >= 1")
        if not self.created:
            self.created = iso(utcnow())

    # -- reading ---------------------------------------------------------
    def value(self, slot: str) -> str | None:
        return self.slots[slot].value

    def filled(self) -> dict[str, str]:
        return {k: v.value for k, v in self.slots.items() if v.filled}

    def unresolved(self) -> list[str]:
        return [k for k in SLOTS if not self.slots[k].filled]

    def blocking(self) -> list[str]:
        return [k for k in BLOCKING_SLOTS if not self.slots[k].filled]

    def derived(self) -> list[str]:
        """Slots no human stated, which the decomposition inferred."""
        return [k for k in SLOTS if self.slots[k].filled and self.slots[k].confidence == INFERRED]

    def fingerprint(self) -> str:
        """Identity of the question's *content*, ignoring bookkeeping."""
        return new_id("QF", self.raw, *(self.slots[k].value or "" for k in SLOTS))

    # -- serialisation ---------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "version": self.version,
            "raw": self.raw,
            "slots": {k: v.to_dict() for k, v in self.slots.items()},
            "parent": self.parent,
            "revision_of": self.revision_of,
            "revision_reason": self.revision_reason,
            "created": self.created,
            "trigger": self.trigger,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Question":
        raw_slots = payload.get("slots") or {}
        if not isinstance(raw_slots, Mapping):
            raise ValueError("slots must be an object")
        return cls(
            qid=str(payload["qid"]),
            version=int(payload.get("version", 1)),
            raw=str(payload["raw"]),
            slots={k: SlotValue.from_dict(raw_slots.get(k)) for k in SLOTS},
            parent=payload.get("parent"),
            revision_of=payload.get("revision_of"),
            revision_reason=str(payload.get("revision_reason", "")),
            created=str(payload.get("created", "")),
            trigger=str(payload.get("trigger", "")),
        )

    def summary(self) -> str:
        kept = ", ".join(self.filled()) or "none"
        return f"{self.qid} v{self.version}: filled [{kept}]; unresolved [{', '.join(self.unresolved()) or 'none'}]"


def make_question(
    raw: str,
    slots: Mapping[str, Any],
    *,
    qid: str | None = None,
    version: int = 1,
    parent: str | None = None,
    revision_of: str | None = None,
    revision_reason: str = "",
    trigger: str = "",
) -> Question:
    """Build a Question from raw text plus a partial slot mapping.

    Missing slots become ``UNRESOLVED`` rather than raising: an underspecified
    question is the input QSE exists to work on, not an error.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("a question needs non-empty raw text")
    seeded = {name: SlotValue.from_dict(slots.get(name)) for name in SLOTS}
    return Question(
        qid=qid or new_id("Q", raw, version),
        version=version,
        raw=raw,
        slots=seeded,
        parent=parent,
        revision_of=revision_of,
        revision_reason=revision_reason,
        trigger=trigger,
    )
