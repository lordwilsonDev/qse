"""Experiments: falsification audit, planning, deterministic runners, results."""

from .falsification import WEAKNESSES, audit, falsifiable, reasons, strengthen
from .planner import RUNNER_FOR, best_to_run, coverage, discriminating, propose
from .results import VERDICTS, effect_size, strength_for, to_evidence, update, verdict
from .runner import (
    COVERAGE_GAP_SUPPORT,
    CORRELATION_FLOOR,
    DISCRIMINATION_MARGIN_FLOOR,
    MIN_GROUPS,
    RUNNERS,
    VARIANCE_RATIO_REFUTE,
    VARIANCE_RATIO_SUPPORT,
    Dataset,
    NeedsColumns,
    available,
    bindings,
    run,
)

__all__ = [
    "WEAKNESSES", "audit", "falsifiable", "reasons", "strengthen",
    "RUNNER_FOR", "best_to_run", "coverage", "discriminating", "propose",
    "VERDICTS", "effect_size", "strength_for", "to_evidence", "update", "verdict",
    "COVERAGE_GAP_SUPPORT", "CORRELATION_FLOOR", "DISCRIMINATION_MARGIN_FLOOR",
    "MIN_GROUPS", "RUNNERS", "VARIANCE_RATIO_REFUTE", "VARIANCE_RATIO_SUPPORT",
    "Dataset", "NeedsColumns", "available", "bindings", "run",
]
