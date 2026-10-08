"""Outcomes: the last rung, and the one most easily faked.

``VI`` counts independently verified *artifacts*. ``OC`` counts *real-world
outcomes* per verified artifact. The ``real_world`` flag is the whole
distinction: "the verifier re-ran the test" is an outcome, but it is not the
company's orders shipping on time, and the scorecard must not pretend otherwise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ..ids import new_id

KINDS = (
    "MEASURED_CHANGE",
    "PREDICTION_CONFIRMED",
    "DECISION_TAKEN",
    "ARTIFACT_DEPLOYED",
    "NO_OUTCOME",
)
OUTCOME_KINDS = KINDS


@dataclass
class Outcome:
    oid: str
    artifact: str
    kind: str
    observed: Any = None
    baseline: Any = None
    before: Any = None
    after: Any = None
    evidence: tuple[str, ...] = ()
    real_world: bool = False
    notes: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown outcome kind {self.kind!r}; choose from {KINDS}")
        if self.kind != "NO_OUTCOME" and not self.evidence:
            raise ValueError("an outcome other than NO_OUTCOME needs at least one evidence id")
        if self.real_world and self.kind == "NO_OUTCOME":
            raise ValueError("NO_OUTCOME cannot be a real-world outcome")

    def delta(self) -> float | None:
        """before -> after, when both are numbers. Otherwise None, never a guess."""
        if isinstance(self.before, (int, float)) and isinstance(self.after, (int, float)):
            return float(self.after) - float(self.before)
        return None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["evidence"] = list(self.evidence)
        out["delta"] = self.delta()
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Outcome":
        return cls(
            oid=str(payload["oid"]),
            artifact=str(payload.get("artifact", "")),
            kind=str(payload["kind"]),
            observed=payload.get("observed"),
            baseline=payload.get("baseline"),
            before=payload.get("before"),
            after=payload.get("after"),
            evidence=tuple(str(e) for e in payload.get("evidence", ())),
            real_world=bool(payload.get("real_world", False)),
            notes=str(payload.get("notes", "")),
        )


def make_outcome(
    *,
    artifact: str,
    kind: str,
    evidence: tuple[str, ...] = (),
    observed: Any = None,
    baseline: Any = None,
    before: Any = None,
    after: Any = None,
    real_world: bool = False,
    notes: str = "",
) -> Outcome:
    oid = new_id("OUT", artifact, kind, str(before), str(after))
    return Outcome(
        oid=oid,
        artifact=artifact,
        kind=kind,
        observed=observed,
        baseline=baseline,
        before=before,
        after=after,
        evidence=evidence,
        real_world=real_world,
        notes=notes,
    )
