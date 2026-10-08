"""Assumptions: what has to be true for the question to be answerable at all.

The load-bearing flag matters. An assumption the question survives without is a
note; an assumption the question collapses without is a target. Only the second
kind generates experiments on its own.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ..ids import new_id

STATUSES = ("UNTESTED", "SUPPORTED", "CONTRADICTED")
ASSUMPTION_STATUSES = STATUSES


@dataclass
class Assumption:
    aid: str
    text: str
    source: str
    slot: str | None = None
    status: str = "UNTESTED"
    load_bearing: bool = False
    testable_consequence: str | None = None

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown assumption status {self.status!r}")
        if not self.text.strip():
            raise ValueError("an assumption needs text")
        if self.load_bearing and not (self.testable_consequence or "").strip():
            raise ValueError(
                f"load-bearing assumption {self.aid!r} needs a testable consequence "
                "(otherwise it is an opinion, not an assumption)"
            )

    def testable(self) -> bool:
        return bool((self.testable_consequence or "").strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Assumption":
        return cls(
            aid=str(payload["aid"]),
            text=str(payload["text"]),
            source=str(payload.get("source", "unknown")),
            slot=payload.get("slot"),
            status=str(payload.get("status", "UNTESTED")),
            load_bearing=bool(payload.get("load_bearing", False)),
            testable_consequence=payload.get("testable_consequence"),
        )


def make_assumption(
    text: str,
    *,
    source: str,
    slot: str | None = None,
    load_bearing: bool = False,
    testable_consequence: str | None = None,
) -> Assumption:
    aid = new_id("ASM", source, slot or "", text)
    return Assumption(
        aid=aid,
        text=text,
        source=source,
        slot=slot,
        load_bearing=load_bearing,
        testable_consequence=testable_consequence,
    )
