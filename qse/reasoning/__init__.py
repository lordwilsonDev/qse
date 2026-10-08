"""Reasoning: hypotheses, preserved disagreement, evidence-weighted synthesis."""

from .disagreement import Disagreement, find, preserve, summary, unresolved
from .hypothesis import (
    DEFAULT_STRUCTURE,
    KIND_TO_STRUCTURE,
    coverage,
    distinct_pairs,
    from_inversions,
    groups,
    register,
    structure_for,
)
from .synthesis import SCALE_NOTE, select, weigh
from .uncertainty import (
    KINDS as UNCERTAINTY_KINDS,
    MAGNITUDES,
    Uncertainty,
    entropy_level,
    load,
    survey,
)

__all__ = [
    "Disagreement", "find", "preserve", "summary", "unresolved",
    "DEFAULT_STRUCTURE", "KIND_TO_STRUCTURE", "coverage", "distinct_pairs",
    "from_inversions", "groups", "register", "structure_for",
    "SCALE_NOTE", "select", "weigh",
    "UNCERTAINTY_KINDS", "MAGNITUDES", "Uncertainty", "entropy_level", "load", "survey",
]
