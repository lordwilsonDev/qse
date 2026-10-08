"""Falsification: is this a test, or a demonstration dressed as one?

``Experiment`` already refuses to exist without a ``refuted_by`` condition, so
"unfalsifiable" should be empty for objects built in this process. It is not
empty for records read back from JSON, and that asymmetry is the point of
``audit``: the constructor protects the way in, and the audit protects the way
back in.

The more common real defect is not a missing refutation condition but a
*decorative* one -- a test whose two predictions are the same sentence, or whose
refutation condition is a restatement of what the author hopes to see. Those
pass construction and are caught here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import replace

from ..core.experiment import Experiment
from ..ids import canon

__all__ = ["falsifiable", "reasons", "audit", "strengthen", "WEAKNESSES"]

#: Weakness codes, so a report can be read by a machine as well as a person.
WEAKNESSES = (
    "NO_REFUTATION",
    "IDENTICAL_PREDICTIONS",
    "REFUTATION_RESTATES_PREDICTION",
    "NO_RUNNER",
    "NO_DISCRIMINATION",
)


def falsifiable(experiment: Experiment) -> bool:
    """True when a result could change the hypothesis. Requires a refutation
    condition *and* two predictions that are not the same sentence."""
    return not set(reasons(experiment)) & {
        "NO_REFUTATION",
        "IDENTICAL_PREDICTIONS",
        "REFUTATION_RESTATES_PREDICTION",
    }


def reasons(experiment: Experiment) -> list[str]:
    """Every weakness found, in a fixed order so the output is deterministic."""
    found: list[str] = []
    if not (experiment.refuted_by or "").strip():
        found.append("NO_REFUTATION")
    if canon(experiment.prediction_if_true) == canon(experiment.prediction_if_false):
        found.append("IDENTICAL_PREDICTIONS")
    elif (experiment.prediction_if_true or "").strip() and (
        canon(experiment.prediction_if_true) in canon(experiment.refuted_by)
    ):
        # "refuted if we observe X" when X is already predicted: the condition
        # can never fire, so the test cannot lose.
        found.append("REFUTATION_RESTATES_PREDICTION")
    if experiment.runner is None:
        found.append("NO_RUNNER")
    if len(experiment.discriminates) < 2:
        found.append("NO_DISCRIMINATION")
    return found


def audit(experiments: Iterable[Experiment | Mapping[str, object]]) -> dict:
    """Audit a set of experiments, including records reconstructed from JSON.

    ``unfalsifiable`` lists the ones that could not even be constructed; that is
    normally empty and is not a bug in this function.
    """
    falsifiable_ids: list[str] = []
    unfalsifiable: list[str] = []
    weak: dict[str, list[str]] = {}
    malformed: dict[str, str] = {}

    for item in experiments:
        try:
            experiment = (
                item if isinstance(item, Experiment) else Experiment.from_dict(dict(item))  # type: ignore[arg-type]
            )
        except (ValueError, KeyError, TypeError) as exc:
            raw = item if isinstance(item, Mapping) else getattr(item, "xid", "?")
            xid = str(raw.get("xid", "?") if isinstance(raw, Mapping) else raw)
            malformed[xid] = str(exc)
            unfalsifiable.append(xid)
            continue

        if falsifiable(experiment):
            falsifiable_ids.append(experiment.xid)
        else:
            unfalsifiable.append(experiment.xid)
        issues = reasons(experiment)
        if issues:
            weak[experiment.xid] = issues

    return {
        "falsifiable": sorted(falsifiable_ids),
        "unfalsifiable": sorted(unfalsifiable),
        "weak": weak,
        "malformed": malformed,
        "n": len(falsifiable_ids) + len(unfalsifiable),
    }


def strengthen(experiment: Experiment, refuted_by: str) -> Experiment:
    """Return a copy with a usable refutation condition.

    The ``xid`` is deliberately preserved: strengthening a test must not create a
    new experiment that no evidence, hypothesis or ledger entry points at.
    """
    if not (refuted_by or "").strip():
        raise ValueError("strengthening requires a non-empty refutation condition")
    return replace(experiment, refuted_by=refuted_by)
