"""The adversary: seven attacks, each one a way for the artifact to be wrong.

Every attack runs on every artifact. None of them is optional, and none of them
reads a verdict off a constant -- each decides from the real context (the
hypothesis, the evidence, the experiment results, the reproductions) and
records the observation it decided from in ``evidence_ref``.

``survives`` means **the artifact survived the attack**. So ``survives=False``
is the attack landing, which is the opposite of how the word reads at a glance;
the field is named from the artifact's point of view throughout, and
``landed()`` is the accessor to use when you want the failures.

A landed MINOR attack does not by itself reject an artifact. A landed FATAL or
SERIOUS one does. The threshold is the point: a system that rejects on any
criticism cannot finish, and one that rejects on nothing is not adversarial.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

from ..core.artifact import Artifact
from ..core.evidence import Evidence
from ..core.hypothesis import Hypothesis
from ..ids import canon, new_id

KINDS = (
    "attack_measurement",
    "attack_causality",
    "attack_scope",
    "attack_assumption",
    "attack_reproduction",
    "attack_authority",
    "attack_direction",
)

SEVERITIES = ("FATAL", "SERIOUS", "MINOR")

#: Attacks that reject an artifact outright when they land.
DECISIVE = ("FATAL", "SERIOUS")

#: Artifact kinds that claim to apply more than once, so a single source is not enough.
_GENERALIZING = ("DECISION_RULE", "PROCESS")


@dataclass
class Attack:
    atid: str
    artifact: str
    kind: str
    claim: str
    severity: str
    survives: bool
    response: str
    evidence_ref: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown attack kind {self.kind!r}; choose from {KINDS}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}; choose from {SEVERITIES}")

    @property
    def landed(self) -> bool:
        return not self.survives

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["landed"] = self.landed
        # `claim` is the ACCUSATION, written in the accusing tense, and it is
        # rendered whether or not the accusation succeeded. Read alone it can
        # therefore read backwards -- "the artifact does not reproduce" sits next
        # to survives=True. `finding` is the verdict in words, so a reader of the
        # ledger never has to infer the outcome from the tense of a sentence.
        out["finding"] = (
            f"{'LANDED' if self.landed else 'CLEARED'} ({self.severity}): {self.claim}"
        )
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Attack":
        return cls(
            atid=str(payload["atid"]),
            artifact=str(payload.get("artifact", "")),
            kind=str(payload["kind"]),
            claim=str(payload.get("claim", "")),
            severity=str(payload.get("severity", "MINOR")),
            survives=bool(payload.get("survives", True)),
            response=str(payload.get("response", "")),
            evidence_ref=str(payload.get("evidence_ref", "")),
        )


# --------------------------------------------------------------------------- #
# Input normalisation
# --------------------------------------------------------------------------- #

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


def _hypothesis(raw: Any) -> Hypothesis | None:
    if isinstance(raw, Hypothesis):
        return raw
    if isinstance(raw, Mapping) and "hid" in raw:
        try:
            return Hypothesis.from_dict(raw)
        except (ValueError, KeyError, TypeError):
            return None
    return None


def _ran(result: Mapping[str, Any]) -> bool:
    return bool(result.get("ran", True))


def _supported(result: Mapping[str, Any]) -> bool:
    return result.get("supported") is True


def _separating(results: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Results that separated competing explanations rather than confirming one.

    A correlational confirmation is not a causal test. The two marks of a
    separating run are a counterfactual design and a claim to distinguish more
    than one explanation; either is enough.
    """
    out = []
    for result in results or ():
        if not isinstance(result, Mapping) or not _ran(result):
            continue
        discriminates = result.get("discriminates") or ()
        if result.get("runner") == "counterfactual_replay" or len(list(discriminates)) > 1:
            out.append(result)
    return out


# --------------------------------------------------------------------------- #
# The seven attacks
# --------------------------------------------------------------------------- #

def _attack_measurement(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    classes = sorted({e.kind for e in for_ev if e.usable()})
    reproduced = [r for r in reproductions if getattr(r, "ran", False) and getattr(r, "ok", False)]
    only_measured = bool(classes) and set(classes) <= {"MEASURED"}
    landed = only_measured and not reproduced
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[0]),
        artifact=artifact.aid,
        kind=KINDS[0],
        claim=(
            "the result is an artifact of how it was measured: every supporting "
            "observation is a MEASURED aggregate and nothing was re-measured"
        ),
        severity="FATAL" if landed and not reproduced else ("SERIOUS" if landed else "MINOR"),
        survives=not landed,
        response=(
            "re-derive the finding from an independent measurement path "
            "(an OBSERVED or REPRODUCED class), or show the same number via a second instrument"
        ),
        evidence_ref=f"usable classes={classes or ['none']}; reproductions={len(reproduced)} ran clean",
    )


def _attack_causality(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    separating = _separating(results)
    landed = not separating
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[1]),
        artifact=artifact.aid,
        kind=KINDS[1],
        claim=(
            "the artifact's rule is asserted as a mechanism while every observation "
            "behind it is associational; no run separates this explanation from its competitors"
        ),
        severity="FATAL" if landed else "MINOR",
        survives=not landed,
        response=(
            "run a counterfactual replay or an experiment that discriminates between at "
            "least two hypotheses, and record the separating result"
        ),
        evidence_ref=(
            f"hypothesis={'present' if hypothesis is not None else 'absent'}; "
            f"separating results={len(separating)} of {len(list(results or ()))}"
        ),
    )


def _attack_scope(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    usable = [e for e in for_ev if e.usable()]
    distinct = sorted({canon(e.source) for e in usable})
    generalizing = artifact.kind in _GENERALIZING
    landed = generalizing and len(distinct) < 2
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[2]),
        artifact=artifact.aid,
        kind=KINDS[2],
        claim=(
            f"the artifact is a {artifact.kind} and therefore claims to apply more than "
            f"once, but its support rests on {len(distinct)} distinct source(s)"
        ),
        severity="SERIOUS" if landed else "MINOR",
        survives=not landed,
        response=(
            "show the rule holds on a second, independent data source, or narrow the "
            "artifact's stated scope to the single source it was derived from"
        ),
        evidence_ref=f"sources={distinct or ['none']}; kind={artifact.kind}",
    )


def _attack_assumption(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    ran = [r for r in (results or ()) if isinstance(r, Mapping) and _ran(r)]
    supported = [r for r in ran if _supported(r)]
    landed = not supported
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[3]),
        artifact=artifact.aid,
        kind=KINDS[3],
        claim=(
            "the mechanism the artifact assumes was never demonstrated: "
            f"{len(ran)} test(s) ran and {len(supported)} came back supporting it"
        ),
        severity="SERIOUS" if landed else "MINOR",
        survives=not landed,
        response=(
            "run the experiment the hypothesis was built from and record a result that "
            "supports it, or mark the hypothesis CONTRADICTED and rebuild from that"
        ),
        evidence_ref=f"results={[str(r.get('runner', '?')) for r in ran]}; supported={len(supported)}",
    )


def _attack_reproduction(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    items = list(reproductions or ())
    ran = [r for r in items if getattr(r, "ran", False)]
    clean = [r for r in ran if getattr(r, "ok", False)]
    landed = (not ran) or (not clean)
    if not ran:
        reason = "nothing was ever re-run; a single execution is not reproducibility"
    else:
        reason = f"{len(ran) - len(clean)} of {len(ran)} rerun(s) disagreed with the first run"
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[4]),
        artifact=artifact.aid,
        kind=KINDS[4],
        claim=f"the artifact does not reproduce: {reason}",
        severity="FATAL" if landed else "MINOR",
        survives=not landed,
        response=(
            "re-execute the artifact from its recorded source and confirm identical output; "
            "if the output varies, the artifact is not deterministic and that is the defect"
        ),
        evidence_ref=f"reproductions ran={len(ran)} clean={len(clean)}",
    )


def _attack_authority(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    """Is there a named party with the standing to call this wrong?

    This used to require the authority's name to appear inside an *evidence source*
    -- that is, inside a dataset's filename. A person is not a file, so the check
    could never be satisfied and every artifact was permanently rejected. An attack
    that cannot be cleared is not an attack; it is a veto.

    What is checked now is the question that can actually be answered: is an
    authority named at all, and is it a real one rather than a placeholder? Whether
    that authority has *weighed in* is still reported, but as a MINOR observation,
    because "nobody has signed off yet" is a caveat on the claim, not a refutation
    of the artifact.
    """
    placeholders = {"unnamed", "unknown", "none", "n/a", "na", "tbd", "todo", "-"}
    named = (hypothesis.authority if hypothesis is not None else "") or ""
    usable = [e for e in for_ev if e.usable()]
    folded = canon(named)
    if not named.strip():
        landed, severity, ref = True, "SERIOUS", "the hypothesis names no authority at all"
    elif folded in {canon(p) for p in placeholders}:
        landed, severity, ref = True, "SERIOUS", f"the authority is a placeholder ({named!r})"
    else:
        landed, severity = False, "MINOR"
        attributable = [e.source for e in usable if folded and folded in canon(e.source)]
        ref = (
            f"authority={named!r} is named and stands behind the claim; "
            f"evidence directly attributable to them={attributable or 'none yet'}"
        )
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[5]),
        artifact=artifact.aid,
        kind=KINDS[5],
        claim=(
            f"nobody with the standing to call this wrong has weighed in: {ref}"
        ),
        severity=severity,
        survives=not landed,
        response=(
            "have the named authority attest to the artifact, or record who does hold that "
            "standing and why their evidence is admissible"
        ),
        evidence_ref=ref,
    )


def _attack_direction(artifact, hypothesis, for_ev, against_ev, results, reproductions):
    usable_for = [e for e in for_ev if e.usable()]
    usable_against = [e for e in against_ev if e.usable()]
    weight_for = sum(e.weight() for e in usable_for)
    weight_against = sum(e.weight() for e in usable_against)
    landed = weight_against > weight_for
    return Attack(
        atid=new_id("ATK", artifact.aid, KINDS[6]),
        artifact=artifact.aid,
        kind=KINDS[6],
        claim=(
            "the usable evidence points the other way: weight against "
            f"{weight_against:g} exceeds weight for {weight_for:g}"
        ),
        severity="FATAL" if landed else "MINOR",
        survives=not landed,
        response=(
            "invert the artifact's rule, or explain the counter-evidence and record what "
            "would have to be observed for it to be wrong"
        ),
        evidence_ref=(
            f"for={[e.eid for e in usable_for]} (w={weight_for:g}); "
            f"against={[e.eid for e in usable_against]} (w={weight_against:g})"
        ),
    )


_ATTACKS = (
    _attack_measurement,
    _attack_causality,
    _attack_scope,
    _attack_assumption,
    _attack_reproduction,
    _attack_authority,
    _attack_direction,
)


def catalogue() -> tuple[str, ...]:
    return KINDS


# --------------------------------------------------------------------------- #
# Running them
# --------------------------------------------------------------------------- #

def attack(
    artifact: Artifact,
    *,
    hypothesis: Any = None,
    evidence_for: Iterable[Any] = (),
    evidence_against: Iterable[Any] = (),
    results: Iterable[Mapping[str, Any]] = (),
    reproductions: Iterable[Any] = (),
) -> list[Attack]:
    """Run all seven attacks and return one verdict per attack, in catalogue order.

    Every attack runs every time. Short-circuiting after the first landing would
    make the report's shape depend on which attack fired first, and the point of
    a fixed catalogue is that two runs of the same artifact produce the same
    seven rows.
    """
    hyp = _hypothesis(hypothesis)
    for_ev = _evidence(evidence_for)
    against_ev = _evidence(evidence_against)
    result_list = [r for r in (results or ()) if isinstance(r, Mapping)]
    repro_list = list(reproductions or ())
    return [
        fn(artifact, hyp, for_ev, against_ev, result_list, repro_list)
        for fn in _ATTACKS
    ]


# A rejected artifact is read back out of the ledger as a dict, while a live run
# holds Attack objects. Every accessor below therefore reads both, because the
# alternative -- getattr defaulting on a dict -- silently reports a landed attack
# as survived, which turns a rejection into an approval.

def survives_of(item: Any) -> bool:
    if isinstance(item, Mapping):
        return bool(item.get("survives", True))
    return bool(getattr(item, "survives", True))


def severity_of(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("severity", "MINOR"))
    return str(getattr(item, "severity", "MINOR"))


def kind_of(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("kind", "?"))
    return str(getattr(item, "kind", "?"))


def landed(attacks: Iterable[Any]) -> list[Any]:
    """The attacks that landed, i.e. that the artifact did NOT survive."""
    return [a for a in (attacks or ()) if not survives_of(a)]


def decisive(attacks: Iterable[Any]) -> list[Any]:
    """The landed attacks heavy enough to reject the artifact."""
    return [a for a in landed(attacks) if severity_of(a) in DECISIVE]


def survived(attacks: Iterable[Any]) -> bool:
    """True only when no FATAL or SERIOUS attack landed.

    A landed MINOR attack is recorded and shown and does not reject. Returning
    False here means the artifact is not fit to verify, not that it is worthless.
    """
    return not decisive(attacks)


def verdict(attacks: Iterable[Any]) -> str:
    return "SURVIVED" if survived(attacks) else "REJECTED"


def report(attacks: Iterable[Any]) -> dict[str, Any]:
    rows = list(attacks or ())
    landed_rows = landed(rows)
    return {
        "n": len(rows),
        "verdict": verdict(rows),
        "landed": [kind_of(a) for a in landed_rows],
        "decisive": [kind_of(a) for a in decisive(rows)],
        "survived": [kind_of(a) for a in rows if survives_of(a)],
        "attacks": [a.to_dict() if hasattr(a, "to_dict") else dict(a) for a in rows],
    }
