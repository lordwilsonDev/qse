"""Experiments, and the requirement that each one can lose.

An experiment that cannot be refuted is a demonstration, not a test. The
constructor refuses one, so `refuted_by` is not a field somebody may forget:
it is the price of constructing the object at all.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import new_id

STATUSES = ("PROPOSED", "RUN", "REFUTED", "SURVIVED", "INCONCLUSIVE")
EXPERIMENT_STATUSES = STATUSES

#: Runners that exist. Naming one is how a proposed experiment becomes executable.
RUNNERS = (
    "precursor_detection",
    "discrimination_scan",
    "aggregation_check",
    "correlation_split",
    "variance_compare",
    "coverage_scan",
    "counterfactual_replay",
)


@dataclass
class Experiment:
    xid: str
    hypothesis: str
    question: str
    design: str
    prediction_if_true: str
    prediction_if_false: str
    refuted_by: str
    runner: str | None = None
    discriminates: tuple[str, ...] = field(default_factory=tuple)
    required_data: tuple[str, ...] = field(default_factory=tuple)
    cost: float = 1.0
    duration_h: float = 1.0
    status: str = "PROPOSED"

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown experiment status {self.status!r}")
        if not (self.design or "").strip():
            raise ValueError("an experiment needs a design")
        if not (self.refuted_by or "").strip():
            raise ValueError(
                "an experiment must state what would refute it; a test that cannot "
                "lose is a demonstration, not an experiment (R-EXP-1)"
            )
        if self.runner is not None and self.runner not in RUNNERS:
            raise ValueError(f"unknown runner {self.runner!r}; choose from {RUNNERS}")
        if self.cost < 0 or self.duration_h < 0:
            raise ValueError("cost and duration_h cannot be negative")

    def falsifiable(self) -> bool:
        """Always True for a constructed Experiment; kept so a caller need not know
        that the constructor is where the rule is enforced, and so a record read
        back from JSON is checked the same way it was on the way in."""
        return bool((self.refuted_by or "").strip())

    def executable(self) -> bool:
        return self.runner is not None and self.falsifiable()

    def separates(self) -> int:
        """How many hypotheses this experiment can tell apart."""
        return len(self.discriminates) if self.discriminates else 1

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["discriminates"] = list(self.discriminates)
        out["required_data"] = list(self.required_data)
        out["falsifiable"] = self.falsifiable()
        out["executable"] = self.executable()
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Experiment":
        return cls(
            xid=str(payload["xid"]),
            hypothesis=str(payload.get("hypothesis", "")),
            question=str(payload.get("question", "")),
            design=str(payload.get("design", "")),
            prediction_if_true=str(payload.get("prediction_if_true", "")),
            prediction_if_false=str(payload.get("prediction_if_false", "")),
            refuted_by=str(payload.get("refuted_by", "")),
            runner=payload.get("runner"),
            discriminates=tuple(str(h) for h in payload.get("discriminates", ())),
            required_data=tuple(str(d) for d in payload.get("required_data", ())),
            cost=float(payload.get("cost", 1.0)),
            duration_h=float(payload.get("duration_h", 1.0)),
            status=str(payload.get("status", "PROPOSED")),
        )


def make_experiment(
    *,
    hypothesis: str,
    question: str,
    design: str,
    prediction_if_true: str,
    prediction_if_false: str,
    refuted_by: str,
    runner: str | None = None,
    discriminates: tuple[str, ...] = (),
    required_data: tuple[str, ...] = (),
    cost: float = 1.0,
    duration_h: float = 1.0,
) -> Experiment:
    xid = new_id("EXP", hypothesis, design, refuted_by, runner or "")
    return Experiment(
        xid=xid,
        hypothesis=hypothesis,
        question=question,
        design=design,
        prediction_if_true=prediction_if_true,
        prediction_if_false=prediction_if_false,
        refuted_by=refuted_by,
        runner=runner,
        discriminates=discriminates,
        required_data=required_data,
        cost=cost,
        duration_h=duration_h,
    )
