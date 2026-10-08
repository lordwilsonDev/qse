"""The seven types that must never be confused with each other.

``Answer`` is deliberately absent: an answer is not a QSE object, because QSE
does not optimise for answers. Everything it stores is one of these.
"""

from .artifact import ARTIFACT_KINDS, ARTIFACT_STATES, Artifact, make_artifact
from .assumption import ASSUMPTION_STATUSES, Assumption, make_assumption
from .evidence import EVIDENCE_CLASSES, USABLE_EVIDENCE, Evidence, make_evidence
from .experiment import EXPERIMENT_STATUSES, Experiment, make_experiment
from .hypothesis import (
    LOCI,
    MECHANISMS,
    STRUCTURE_FIELDS,
    TIMESCALES,
    Hypothesis,
    make_hypothesis,
)
from .outcome import OUTCOME_KINDS, Outcome, make_outcome
from .proposition import MODALITIES, Proposition, parse_proposition
from .question import SLOTS, SLOT_QUESTIONS, Question, SlotValue, make_question

__all__ = [
    "ARTIFACT_KINDS", "ARTIFACT_STATES", "Artifact", "make_artifact",
    "ASSUMPTION_STATUSES", "Assumption", "make_assumption",
    "EVIDENCE_CLASSES", "USABLE_EVIDENCE", "Evidence", "make_evidence",
    "EXPERIMENT_STATUSES", "Experiment", "make_experiment",
    "LOCI", "MECHANISMS", "STRUCTURE_FIELDS", "TIMESCALES", "Hypothesis", "make_hypothesis",
    "OUTCOME_KINDS", "Outcome", "make_outcome",
    "MODALITIES", "Proposition", "parse_proposition",
    "SLOTS", "SLOT_QUESTIONS", "Question", "SlotValue", "make_question",
]
