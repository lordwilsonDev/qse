"""The gate. The one place where an artifact may become VERIFIED.

Three refusals stand between a constructed artifact and the word "verified",
and they are checked in a fixed order so the report always names the earliest
thing that was wrong:

  R-VER-1  the verifier is not the builder
  R-VER-2  the artifact has been constructed and attacked
  R-VER-3  a reproduction ran and matched

Then two conditions that are findings rather than rule violations: no decisive
attack may have landed, and the artifact's hypothesis must carry usable evidence
after the firewall.

The gate **does not raise**. It catches each ``Refusal``, records the rule id and
returns ``ok: False`` with the reason. A gate that raised would be caught by
whatever called it, and the difference between "refused" and "crashed" would be
erased at exactly the moment it matters most.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from ..core.artifact import Artifact
from ..core.evidence import Evidence
from ..control.policy import (
    RULES,
    Refusal,
    require_attacked,
    require_independent,
    require_reproduced,
)
from ..ids import canon, new_id
from . import adversary


@dataclass
class Verification:
    vid: str
    artifact: str
    builder: str
    verifier: str
    independent: bool
    ok: bool
    method: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    builder_identity: str = ""
    verifier_identity: str = ""
    independence_basis: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["evidence"] = list(self.evidence)
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Verification":
        return cls(
            vid=str(payload["vid"]),
            artifact=str(payload.get("artifact", "")),
            builder=str(payload.get("builder", "")),
            verifier=str(payload.get("verifier", "")),
            independent=bool(payload.get("independent", False)),
            ok=bool(payload.get("ok", False)),
            method=str(payload.get("method", "")),
            evidence=tuple(str(e) for e in payload.get("evidence", ())),
            notes=str(payload.get("notes", "")),
            # Older records predate identity; absent means "not attested", not "equal".
            builder_identity=str(payload.get("builder_identity", "")),
            verifier_identity=str(payload.get("verifier_identity", "")),
            independence_basis=str(payload.get("independence_basis", "")),
        )


def is_independent(builder: str, verifier: str) -> bool:
    """Whether the verifier is somebody other than the builder, by name.

    Compared by folded name, which is exactly as strong as the names are. Two
    strings that differ can still be one person, and two spellings that agree
    after folding are treated as one. ``independence`` is the stronger check when
    identities are attested; this keeps the name-only rule for callers that have
    nothing more.
    """
    if not str(verifier or "").strip():
        return False
    return canon(verifier) != canon(builder)


def independence(
    builder: str,
    verifier: str,
    *,
    builder_identity: str = "",
    verifier_identity: str = "",
) -> tuple[bool, str]:
    """Whether the verifier is an independent path, and the basis for saying so.

    Names alone are weak: two names can be one person, one model in two sessions,
    or a client and its alias. When both sides *attest* an identity -- a session
    id, a runner identity, a signed attestation -- independence is established only
    if those identities differ, and a shared identity is refused even when the
    names differ. When no identity is attested, the verdict says so rather than
    implying the name is a path.
    """
    if not str(verifier or "").strip():
        return False, "no verifier named"
    if canon(verifier) == canon(builder):
        return False, "names are equal"
    bi, vi = str(builder_identity or "").strip(), str(verifier_identity or "").strip()
    if bi and vi:
        if bi == vi:
            return False, "names differ but identities are equal"
        return True, "names and identities differ"
    return True, "names differ; identities not attested"


def _evidence(raw: Iterable[Any]) -> list[Evidence]:
    out: list[Evidence] = []
    for item in raw or ():
        if isinstance(item, Evidence):
            out.append(item)
        elif isinstance(item, Mapping) and "eid" in item:
            try:
                out.append(Evidence.from_dict(item))
            except (ValueError, KeyError, TypeError):
                continue
    return out


def verify(
    artifact: Artifact,
    *,
    verifier: str,
    attacks: Iterable[Any] = (),
    reproductions: Iterable[Any] = (),
    evidence_for: Iterable[Any] = (),
    evidence_against: Iterable[Any] = (),
    method: str = "independent replay",
    notes: str = "",
    builder_identity: str = "",
    verifier_identity: str = "",
) -> Verification:
    """Build the Verification record.

    Whether it *should* exist is the gate's decision; this is the constructor the
    gate calls once that decision is yes. ``ok`` requires independence and a
    surviving artifact, so a record built by hand still cannot claim a pass for
    a non-independent verifier.
    """
    independent, basis = independence(
        artifact.builder, verifier,
        builder_identity=builder_identity, verifier_identity=verifier_identity,
    )
    rows = list(attacks or ())
    return Verification(
        vid=new_id("VER", artifact.aid, verifier, method),
        artifact=artifact.aid,
        builder=artifact.builder,
        verifier=str(verifier),
        independent=independent,
        ok=independent and adversary.survived(rows),
        method=method,
        evidence=tuple(e.eid for e in _evidence(evidence_for)),
        notes=notes,
        builder_identity=str(builder_identity or ""),
        verifier_identity=str(verifier_identity or ""),
        independence_basis=basis,
    )


def gate(
    artifact: Artifact,
    *,
    verifier: str,
    attacks: Iterable[Any] = (),
    reproductions: Iterable[Any] = (),
    evidence_for: Iterable[Any] = (),
    evidence_against: Iterable[Any] = (),
    method: str = "independent replay",
    builder_identity: str = "",
    verifier_identity: str = "",
) -> dict[str, Any]:
    """Decide whether the artifact may be marked VERIFIED. Never raises a Refusal.

    Returns the decision, the rule ids that were refused, the reasons in plain
    language, the Verification record when one was issued, and the state the
    artifact should be moved to.
    """
    rows = list(attacks or ())
    repros = [r for r in (reproductions or ()) if r is not None]
    for_ev = _evidence(evidence_for)
    against_ev = _evidence(evidence_against)

    refusals: list[str] = []
    reasons: list[str] = []
    passed = True

    def guard(check: Any, *args: Any) -> bool:
        """Run one policy check, recording a refusal instead of propagating it."""
        try:
            check(*args)
            return True
        except Refusal as refusal:
            refusals.append(refusal.rule)
            reasons.append(f"{refusal.rule} ({RULES[refusal.rule]}): {refusal.message}")
            return False

    # `&` rather than `and`: every rule is evaluated and every reason recorded, so
    # a report names all the problems at once instead of only the first.
    passed &= guard(require_independent, artifact.builder, verifier,
                    builder_identity, verifier_identity)
    passed &= guard(require_attacked, artifact)
    passed &= guard(require_reproduced, repros)

    landed_rows = adversary.landed(rows)
    heavy = adversary.decisive(rows)
    if heavy:
        passed = False
        reasons.append(
            f"{len(heavy)} attack(s) landed and were "
            f"{[adversary.severity_of(a) for a in heavy]}: "
            + ", ".join(
                f"{adversary.kind_of(a)} -- {a.get('claim') if isinstance(a, Mapping) else getattr(a, 'claim', '')}"
                for a in heavy
            )
        )
    elif landed_rows:
        reasons.append(
            f"{len(landed_rows)} minor attack(s) landed and were recorded without rejecting: "
            + ", ".join(adversary.kind_of(a) for a in landed_rows)
        )

    usable_for = [e for e in for_ev if e.usable()]
    if not usable_for:
        passed = False
        unusable = sorted({e.why_unusable() for e in for_ev}) or ["no evidence was offered"]
        reasons.append(
            "R-EVD-2 (a model proposal, report or contested claim never counts as usable "
            "evidence): the artifact's hypothesis has no usable supporting evidence -- "
            + "; ".join(unusable)
        )

    independent, basis = independence(
        artifact.builder, verifier,
        builder_identity=builder_identity, verifier_identity=verifier_identity,
    )
    verification = None
    if passed:
        verification = verify(
            artifact,
            verifier=verifier,
            attacks=rows,
            reproductions=repros,
            evidence_for=usable_for,
            evidence_against=against_ev,
            method=method,
            builder_identity=builder_identity,
            verifier_identity=verifier_identity,
        )

    return {
        "ok": passed,
        "artifact": artifact.aid,
        "verifier": str(verifier),
        "builder": artifact.builder,
        "independent": independent,
        "independence_basis": basis,
        "refusals": refusals,
        "reasons": reasons,
        "verification": verification,
        "state_after": "VERIFIED" if passed else "REJECTED",
        "attacks": len(rows),
        "survived_attacks": len(rows) - len(landed_rows),
        "landed": [adversary.kind_of(a) for a in landed_rows],
        "usable_evidence": [e.eid for e in usable_for],
        "method": method,
    }


def explain(outcome: Mapping[str, Any]) -> str:
    """One sentence a person can read, built only from the gate's own result."""
    if outcome.get("ok"):
        return (
            f"VERIFIED: {outcome.get('artifact')} was verified by {outcome.get('verifier')} "
            f"(independent of builder {outcome.get('builder')}) after surviving "
            f"{outcome.get('survived_attacks')} of {outcome.get('attacks')} attacks, "
            f"with {len(outcome.get('usable_evidence') or [])} usable evidence item(s)."
        )
    refusals = outcome.get("refusals") or []
    reasons = outcome.get("reasons") or []
    head = f"REJECTED: {outcome.get('artifact')} is not verified"
    if refusals:
        head += f" (refused on {', '.join(refusals)})"
    tail = "; ".join(str(r) for r in reasons) or "no reason was recorded, which is itself a defect"
    return f"{head}. {tail}"


def as_rows(verification: Verification) -> str:
    """A compact receipt line for a verification record."""
    mark = "independent" if verification.independent else "SELF-VERIFIED"
    return f"{verification.vid}  {verification.artifact}  {mark}  by {verification.verifier}"
