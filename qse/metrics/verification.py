"""Verification independence and evidence conversion.

``VI = independently_verified_artifacts / total_artifacts``
``EC = verified_claims / generated_claims``

Two traps this module exists to avoid.

**The self-verification trap.** An artifact whose only verification record has
``independent: false`` is not verified, however green it is. Those artifacts are
named in ``self_verified`` so the count of them is visible rather than silently
absorbed.

**The provenance trap.** Evidence is counted usable from its own fields -- class,
source, method, validity -- recomputed here rather than read from a stored
``usable`` flag, so a hand-written ledger cannot claim a MODEL_PROPOSAL was
measured.
"""

from __future__ import annotations

from typing import Any

from ..control.state import State
from ..core.evidence import USABLE_EVIDENCE
from .question_quality import measure, ratio

__all__ = ["is_usable", "verification"]


def is_usable(record: dict[str, Any]) -> bool:
    """Recompute the evidence firewall from first principles, not from a flag."""
    return (
        str(record.get("kind", "")) in USABLE_EVIDENCE
        and bool(str(record.get("source") or "").strip())
        and bool(str(record.get("method") or "").strip())
        and record.get("valid", True) is not False
    )


def verification(state: State) -> dict[str, Any]:
    total = sorted(state.artifacts)
    independently: list[str] = []
    self_verified: list[str] = []
    failed: list[str] = []
    for aid in total:
        records = [v for v in state.verifications.values() if str(v.get("artifact")) == aid]
        if any(v.get("independent") is True and v.get("ok") is True for v in records):
            independently.append(aid)
        # Fail closed: "independent" must be affirmatively True. A record that
        # simply omits the flag counts as a self-verification, not as unknown.
        if records and all(v.get("independent") is not True for v in records):
            self_verified.append(aid)
        if records and not any(v.get("ok") is True for v in records):
            failed.append(aid)
    unverified = [aid for aid in total if aid not in independently and aid not in self_verified and aid not in failed]

    all_evidence = sorted(state.evidence)
    usable = [eid for eid in all_evidence if is_usable(state.evidence[eid])]

    ec = measure(
        ratio(len(usable), len(all_evidence)),
        len(usable),
        len(all_evidence),
        "usable_evidence / generated_evidence",
        unusable=[eid for eid in all_evidence if eid not in usable],
    )

    out = measure(
        ratio(len(independently), len(total)),
        len(independently),
        len(total),
        "independently_verified_artifacts / total_artifacts",
        independently_verified=independently,
        self_verified=self_verified,
        verification_failed=failed,
        unverified=unverified,
        n_verifications=len(state.verifications),
    )
    out["EC"] = ec
    return out
