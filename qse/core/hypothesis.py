"""Hypotheses, and the rule that makes them *structurally* different.

Acceptance demands "multiple structurally different hypotheses". Prose similarity
is not a test, so every hypothesis declares five structural fields and two
hypotheses are the *same explanation* exactly when all five agree. Anything less
is duplicate work wearing a different sentence.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import digest, new_id

#: How the proposed cause could work at all.
MECHANISMS = (
    "CAPACITY", "COORDINATION", "MEASUREMENT", "LATENCY",
    "VARIANCE", "POLICY", "EXTERNAL", "AGGREGATION", "SEQUENCING",
)
#: Where in the system the cause sits.
LOCI = (
    "STAFFING", "SCHEDULING", "SOFTWARE", "SUPPLIER", "COMMUNICATION",
    "TELEMETRY", "PROCESS", "CUSTOMER",
)
#: The timescale on which the cause acts, which decides the experiment design.
TIMESCALES = ("MINUTES", "HOURS", "DAYS", "WEEKS", "MONTHS", "QUARTERS")

STRUCTURE_FIELDS = ("mechanism", "locus", "timescale", "measurement_assumption", "authority")

STATUSES = ("OPEN", "SUPPORTED", "CONTRADICTED", "ELIMINATED")


@dataclass
class Hypothesis:
    hid: str
    text: str
    question: str
    mechanism: str
    locus: str
    timescale: str
    measurement_assumption: str
    authority: str
    from_inversion: str | None = None
    status: str = "OPEN"
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.mechanism not in MECHANISMS:
            raise ValueError(f"unknown mechanism {self.mechanism!r}; choose from {MECHANISMS}")
        if self.locus not in LOCI:
            raise ValueError(f"unknown locus {self.locus!r}; choose from {LOCI}")
        if self.timescale not in TIMESCALES:
            raise ValueError(f"unknown timescale {self.timescale!r}; choose from {TIMESCALES}")
        if self.status not in STATUSES:
            raise ValueError(f"unknown hypothesis status {self.status!r}")
        if not (self.measurement_assumption or "").strip():
            raise ValueError(
                "a hypothesis must state what it assumes about the measurement "
                "(otherwise 'the metric is wrong' is unfalsifiable by construction)"
            )
        if not (self.authority or "").strip():
            raise ValueError("a hypothesis must name who may call it wrong")

    def structure(self) -> tuple[str, ...]:
        return tuple(getattr(self, f) for f in STRUCTURE_FIELDS)

    def signature(self) -> str:
        return digest(*self.structure(), n=12)

    def distance(self, other: "Hypothesis") -> int:
        """How many of the five structural fields differ. 0 means same explanation."""
        return sum(1 for a, b in zip(self.structure(), other.structure()) if a != b)

    def structurally_differs(self, other: "Hypothesis") -> bool:
        return self.distance(other) > 0

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["notes"] = list(self.notes)
        out["signature"] = self.signature()
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Hypothesis":
        return cls(
            hid=str(payload["hid"]),
            text=str(payload["text"]),
            question=str(payload["question"]),
            mechanism=str(payload["mechanism"]),
            locus=str(payload["locus"]),
            timescale=str(payload["timescale"]),
            measurement_assumption=str(payload["measurement_assumption"]),
            authority=str(payload["authority"]),
            from_inversion=payload.get("from_inversion"),
            status=str(payload.get("status", "OPEN")),
            notes=tuple(str(n) for n in payload.get("notes", ())),
        )


def make_hypothesis(
    text: str,
    *,
    question: str,
    mechanism: str,
    locus: str,
    timescale: str,
    measurement_assumption: str,
    authority: str,
    from_inversion: str | None = None,
) -> Hypothesis:
    hid = new_id("HYP", question, mechanism, locus, timescale, measurement_assumption)
    return Hypothesis(
        hid=hid,
        text=text,
        question=question,
        mechanism=mechanism,
        locus=locus,
        timescale=timescale,
        measurement_assumption=measurement_assumption,
        authority=authority,
        from_inversion=from_inversion,
    )
