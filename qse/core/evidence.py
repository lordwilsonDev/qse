"""Evidence, and the firewall that decides what may count as evidence.

Two rules, both enforced here rather than in prose:

* evidence needs provenance — a named source and a named method;
* a model proposal, a report about someone else's work, and a contested claim
  are *evidence classes* but never *usable* evidence.

A contradictory observation is usable evidence. The firewall is about how a
thing was obtained, not about which way it points; throwing away evidence
because it disagrees with the leading hypothesis is how a run lies to itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import new_id

CLASSES = ("OBSERVED", "MEASURED", "DERIVED", "REPRODUCED", "REPORTED", "MODEL_PROPOSAL", "CONTESTED")
EVIDENCE_CLASSES = CLASSES

#: Classes that may satisfy a requirement. Everything not listed is recorded and
#: displayed, and never counts.
USABLE_EVIDENCE = ("OBSERVED", "MEASURED", "DERIVED", "REPRODUCED")

STRENGTHS = ("WEAK", "MODERATE", "STRONG")
_STRENGTH_WEIGHT = {"WEAK": 1.0, "MODERATE": 2.0, "STRONG": 3.0}


@dataclass
class Evidence:
    eid: str
    hypothesis: str
    claim: str
    kind: str
    source: str
    method: str
    collected_at: str
    observed: Any = None
    experiment: str | None = None
    supports: bool = True
    strength: str = "MODERATE"
    valid: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in CLASSES:
            raise ValueError(f"unknown evidence class {self.kind!r}; choose from {CLASSES}")
        if self.strength not in STRENGTHS:
            raise ValueError(f"unknown strength {self.strength!r}; choose from {STRENGTHS}")
        if not self.claim.strip():
            raise ValueError("evidence without a claim is a recording, not evidence")

    # -- the firewall ----------------------------------------------------
    def usable(self) -> bool:
        return self.kind in USABLE_EVIDENCE and bool(self.source.strip()) and bool(self.method.strip()) and self.valid

    def why_unusable(self) -> str:
        if not self.valid:
            return "marked invalid"
        if self.kind not in USABLE_EVIDENCE:
            return f"class {self.kind} cannot be consumed as evidence"
        if not self.source.strip():
            return "no source (unprovenanced)"
        if not self.method.strip():
            return "no method (unprovenanced)"
        return "usable"

    def weight(self) -> float:
        return _STRENGTH_WEIGHT[self.strength] if self.usable() else 0.0

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["usable"] = self.usable()
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Evidence":
        return cls(
            eid=str(payload["eid"]),
            hypothesis=str(payload.get("hypothesis", "")),
            claim=str(payload["claim"]),
            kind=str(payload["kind"]),
            source=str(payload.get("source", "")),
            method=str(payload.get("method", "")),
            collected_at=str(payload.get("collected_at", "")),
            observed=payload.get("observed"),
            experiment=payload.get("experiment"),
            supports=bool(payload.get("supports", True)),
            strength=str(payload.get("strength", "MODERATE")),
            valid=bool(payload.get("valid", True)),
            notes=str(payload.get("notes", "")),
        )


def make_evidence(
    claim: str,
    *,
    hypothesis: str,
    kind: str,
    source: str,
    method: str,
    collected_at: str,
    observed: Any = None,
    experiment: str | None = None,
    supports: bool = True,
    strength: str = "MODERATE",
    notes: str = "",
) -> Evidence:
    eid = new_id("EVD", hypothesis, claim, source, method)
    return Evidence(
        eid=eid,
        hypothesis=hypothesis,
        claim=claim,
        kind=kind,
        source=source,
        method=method,
        collected_at=collected_at,
        observed=observed,
        experiment=experiment,
        supports=supports,
        strength=strength,
        notes=notes,
    )
