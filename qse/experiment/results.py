"""Turning a run into a verdict, and a verdict into evidence.

The direction of the evidence is taken from the *runner's* answer, not from the
hypothesis's author: ``supported`` False becomes ``supports=False`` evidence.
That is the whole reason a run can refute something.

A run that did not happen produces no evidence at all. "The experiment could not
run" is not weak evidence against a hypothesis and is never recorded as any.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace

from ..core.evidence import Evidence, make_evidence
from ..core.experiment import Experiment

__all__ = ["verdict", "update", "to_evidence", "effect_size", "strength_for"]

VERDICTS = ("SURVIVED", "REFUTED", "INCONCLUSIVE")

#: Effect-size floors for the recorded strength of the resulting evidence.
STRONG_EFFECT = 0.50
MODERATE_EFFECT = 0.20


def effect_size(result: Mapping) -> float | None:
    """A single magnitude for the observed effect, when the runner reports one.

    Different runners name their magnitude differently, so the largest absolute
    value among the recognised keys is used. None means the runner did not report
    one, which is a real answer: an effect size is not invented to fill a gap.
    """
    observed = result.get("observed")
    if not isinstance(observed, Mapping):
        return None
    keys = ("separation", "best_separation", "margin", "delta", "pooled_correlation")
    values = [abs(float(observed[k])) for k in keys if isinstance(observed.get(k), (int, float))]
    return max(values) if values else None


def strength_for(value: float | None) -> str:
    if value is None:
        return "WEAK"
    if value >= STRONG_EFFECT:
        return "STRONG"
    if value >= MODERATE_EFFECT:
        return "MODERATE"
    return "WEAK"


def verdict(experiment: Experiment, result: Mapping) -> str:
    """SURVIVED, REFUTED or INCONCLUSIVE for one run."""
    if not result.get("ran"):
        return "INCONCLUSIVE"
    if bool(result.get("refuted")):
        return "REFUTED"
    if result.get("supported") is True:
        return "SURVIVED"
    return "INCONCLUSIVE"


def update(experiment: Experiment, result: Mapping) -> Experiment:
    """The same experiment with its status set from the verdict.

    ``cost`` and ``duration_h`` are preserved from the plan, so a re-run does not
    quietly rewrite what it was expected to cost.
    """
    return replace(experiment, status=verdict(experiment, result))


def to_evidence(
    experiment: Experiment,
    result: Mapping,
    *,
    collected_at: str,
    source: str,
) -> Evidence:
    """The evidence a run produced, or a refusal to pretend it produced any.

    Raises ``ValueError`` when the run did not happen. Callers that want to record
    a non-run must record it as a decision, not as evidence.
    """
    if not result.get("ran"):
        raise ValueError(
            f"experiment {experiment.xid} did not run ({result.get('reason', 'no reason given')}), "
            "so it produced no evidence"
        )
    outcome = verdict(experiment, result)
    magnitude = effect_size(result)
    claim = (
        f"{experiment.runner} over dataset {source!r}: {outcome} "
        f"(supported={result.get('supported')}, refuted={bool(result.get('refuted'))})"
    )
    return make_evidence(
        claim,
        hypothesis=experiment.hypothesis,
        kind="MEASURED",
        source=source,
        method=f"{experiment.runner}: {experiment.design}",
        collected_at=collected_at,
        observed=result.get("observed"),
        experiment=experiment.xid,
        supports=(outcome != "REFUTED"),
        strength=strength_for(magnitude),
        notes="" if outcome != "INCONCLUSIVE" else "inconclusive: the data did not decide",
    )
