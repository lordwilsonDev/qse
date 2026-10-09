"""The Witness: continuity a machine can attest about itself because it refuses to.

MOONSHOT-M. See ``docs/moonshot-m.md`` for the inversions this was built from, and
``moonshot_machine.py`` for the one-command run.
"""

from . import continuity, power
from .continuity import (BEAT, BEYOND_REACH, CORROBORATION_KINDS, DEFAULT_INTERVAL,
                        DEFAULT_STALL_AFTER, EFFECT_KINDS, INDEPENDENCE_KINDS, POLICIES,
                        PROGRESS_KINDS, PROVENANCE_KINDS, REACH_KINDS, SLACK, SUBJECT_FIELDS,
                        SUBJECT_KINDS, SUBJECT_TOKEN_DRIFT, SUBJECT_VOUCH_CONFLICT,
                        absences, beat, boot_time, classify, classify_effect,
                        classify_progress, classify_subject, corroborate, effect_of,
                        effects_of, file_effect, independence, observe_reach, progress_of,
                        provenance_of, reach_of, resolve_subject, subject_identity,
                        subject_token, verify)
from .power import Sleep, covering, load as load_power_log, parse as parse_power_log, read as read_power_log

__all__ = [
    "continuity", "power",
    "BEAT", "BEYOND_REACH", "CORROBORATION_KINDS", "DEFAULT_INTERVAL",
    "DEFAULT_STALL_AFTER", "EFFECT_KINDS", "INDEPENDENCE_KINDS", "POLICIES",
    "PROGRESS_KINDS", "PROVENANCE_KINDS", "REACH_KINDS", "SLACK", "SUBJECT_FIELDS",
    "SUBJECT_KINDS",
    "SUBJECT_TOKEN_DRIFT", "SUBJECT_VOUCH_CONFLICT",
    "absences", "beat", "boot_time", "classify", "classify_effect",
    "classify_progress", "classify_subject", "corroborate", "effect_of",
    "effects_of", "file_effect", "independence", "observe_reach",
    "progress_of", "provenance_of", "reach_of", "resolve_subject",
    "subject_identity", "subject_token", "verify",
    "Sleep", "covering", "load_power_log", "parse_power_log", "read_power_log",
]
