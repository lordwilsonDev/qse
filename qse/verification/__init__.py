"""Verification: provenance, sufficiency, reproducibility, adversarial attack, the gate.

The package answers five different questions and refuses to let any of them
stand in for another:

* provenance  -- can this be traced back to the thing that produced it?
* sufficiency -- is there enough usable evidence to believe anything?
* reproducibility -- does it do the same thing when run again?
* adversary   -- in what ways is it wrong, and did it survive being told?
* gate        -- may the word "verified" be applied at all?

Only the last one may move an artifact to VERIFIED, and it may only do so when
the first four agree. See ``verifier.gate``.
"""

from .adversary import (
    DECISIVE,
    KINDS as ATTACK_KINDS,
    SEVERITIES as ATTACK_SEVERITIES,
    Attack,
    attack,
    catalogue,
    decisive,
    kind_of,
    landed,
    report as attack_report,
    severity_of,
    survived,
    survives_of,
    verdict,
)
from .evidence import contested, meets_bar, sufficiency, unsupported
from .provenance import REQUIRED_FIELDS, audit as provenance_audit, complete, missing, sources, trace
from .reproducibility import Reproduction, check, content_hash, output_hash, record
from .verifier import Verification, as_rows, explain, gate, is_independent, verify

__all__ = [
    "ATTACK_KINDS", "ATTACK_SEVERITIES", "Attack", "DECISIVE", "attack", "attack_report",
    "catalogue", "decisive", "kind_of", "landed", "severity_of", "survived", "survives_of",
    "verdict",
    "contested", "meets_bar", "sufficiency", "unsupported",
    "REQUIRED_FIELDS", "complete", "missing", "provenance_audit", "sources", "trace",
    "Reproduction", "check", "content_hash", "output_hash", "record",
    "Verification", "as_rows", "explain", "gate", "is_independent", "verify",
]
