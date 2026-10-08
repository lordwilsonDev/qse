"""The question engine: decomposition, ambiguity detection, revision.

What is real here: the cue tables and the structural rules are deterministic
tables, the slot inference only fills a slot when a named cue fired, and every
ambiguity carries the rule that produced it. What is *not* claimed: the cue
tables are not a linguistics engine. They are a small, inspectable, testable
approximation whose failures are visible in the record rather than hidden in a
model's weights.
"""

from .ambiguity import (
    KINDS as AMBIGUITY_KINDS,
    RULES,
    SEVERITIES,
    SEVERITY_WEIGHT,
    SLOT_KIND,
    Ambiguity,
    AmbiguityRule,
    blocking,
    by_slot,
    detect,
    kinds,
    matches,
    rule,
    term_pattern,
    unresolved_slots,
)
from .decomposer import decompose, infer_slots, render_report, seven_slot_report
from .dependency import (
    SLOT_DEPENDENCIES,
    blocked_by,
    circular,
    cycles,
    dependencies,
    find_cycles,
    roots,
)
from .provenance import audit, lossless, provenance_summary, slot_provenance, unprovenanced
from .question_generator import (
    BLOCKING_SLOT_NAMES,
    GAIN_GENERALIZATION,
    GAIN_INTERVENTION,
    GAIN_KNOWLEDGE_GAP,
    KINDS as GENERATED_KINDS,
    GeneratedQuestion,
    from_ambiguities,
    from_disagreements,
    from_discrimination,
    from_gaps,
    from_supported,
    next_questions,
)
from .resolver import answered_in_version, open_slots, resolve

__all__ = [
    "AMBIGUITY_KINDS", "RULES", "SEVERITIES", "SEVERITY_WEIGHT", "SLOT_KIND",
    "Ambiguity", "AmbiguityRule", "blocking", "by_slot", "detect", "kinds",
    "matches", "rule", "term_pattern", "unresolved_slots",
    "decompose", "infer_slots", "render_report", "seven_slot_report",
    "SLOT_DEPENDENCIES", "blocked_by", "circular", "cycles", "dependencies",
    "find_cycles", "roots",
    "audit", "lossless", "provenance_summary", "slot_provenance", "unprovenanced",
    "BLOCKING_SLOT_NAMES", "GAIN_GENERALIZATION", "GAIN_INTERVENTION", "GAIN_KNOWLEDGE_GAP",
    "GENERATED_KINDS", "GeneratedQuestion", "from_ambiguities", "from_disagreements",
    "from_discrimination", "from_gaps", "from_supported", "next_questions",
    "answered_in_version", "open_slots", "resolve",
]
