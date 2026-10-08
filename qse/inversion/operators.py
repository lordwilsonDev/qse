"""The AIL operator set: seven ways of inverting an axiom, none of them the same.

The rule that keeps this from being philosophical brainstorming is
``TestableConsequence``. An inversion is only interesting if it says what would
be *observed* if it were true, what would be observed if it were false, and which
two explanations that observation separates. Operators attach one. When an
operator cannot attach one -- because the idea genuinely has no observable
consequence as stated -- it may still emit the candidate with
``consequence=None``, and then ``qse.inversion.ail`` is required to refuse it and
record the refusal. That is why an unconsequenced candidate exists in this file
at all: a gate with no reachable failure is a decoration.

What is real: the operator functions are deterministic, they read the actual
axiom text, and each one produces statements that name a mechanism rather than a
mood. What is assumed: the opposition each operator looks for is the one a human
analyst would look for first. An analyst would find others.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from ..core.proposition import Proposition
from ..core.question import Question
from ..ids import canon, new_id

OPERATORS = (
    "axiom_inverter",
    "scope_attacker",
    "causal_attacker",
    "temporal_attacker",
    "authority_attacker",
    "measurement_attacker",
    "failure_attacker",
)

#: Inversion kinds, and which operator family produces them.
KINDS = (
    "DATA_INSUFFICIENT",
    "SCOPE_COLLAPSE",
    "REVERSE_CAUSATION",
    "TEMPORAL_DRIFT",
    "AUTHORITY_GAP",
    "MEASUREMENT_ARTIFACT",
    "AGGREGATION",
    "UNOBSERVED_FAILURE",
    "SELECTION_EFFECT",
)


@dataclass(frozen=True)
class TestableConsequence:
    """What you would go and observe, and which two explanations it separates."""

    observation: str
    if_true: str
    if_false: str
    discriminates: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Inversion:
    iid: str
    operator: str
    question: str
    target_axiom: str
    statement: str
    kind: str
    consequence: TestableConsequence | None = None
    target_axiom_id: str = ""

    def __post_init__(self) -> None:
        if self.operator not in OPERATORS:
            raise ValueError(f"unknown operator {self.operator!r}; choose from {OPERATORS}")
        if self.kind not in KINDS:
            raise ValueError(f"unknown inversion kind {self.kind!r}; choose from {KINDS}")
        if not self.statement.strip():
            raise ValueError("an inversion needs a statement")

    def testable(self) -> bool:
        return self.consequence is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "iid": self.iid,
            "operator": self.operator,
            "question": self.question,
            "target_axiom": self.target_axiom,
            "target_axiom_id": self.target_axiom_id,
            "statement": self.statement,
            "kind": self.kind,
            "consequence": self.consequence.to_dict() if self.consequence else None,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Inversion":
        raw = payload.get("consequence")
        consequence = None
        if isinstance(raw, Mapping):
            consequence = TestableConsequence(
                observation=str(raw.get("observation", "")),
                if_true=str(raw.get("if_true", "")),
                if_false=str(raw.get("if_false", "")),
                discriminates=str(raw.get("discriminates", "")),
            )
        return cls(
            iid=str(payload["iid"]),
            operator=str(payload["operator"]),
            question=str(payload.get("question", "")),
            target_axiom=str(payload.get("target_axiom", "")),
            statement=str(payload["statement"]),
            kind=str(payload["kind"]),
            consequence=consequence,
            target_axiom_id=str(payload.get("target_axiom_id", "")),
        )


def candidate(
    statement: str,
    *,
    operator: str,
    question: Question,
    target_axiom: Any,
    kind: str,
    consequence: TestableConsequence | None = None,
) -> Inversion:
    """Build an inversion, permitted to be unconsequenced so the gate can refuse it."""
    axiom_text = getattr(target_axiom, "text", str(target_axiom))
    axiom_id = getattr(target_axiom, "aid", "")
    return Inversion(
        iid=new_id("INV", operator, statement, axiom_id),
        operator=operator,
        question=question.qid,
        target_axiom=axiom_text,
        statement=statement,
        kind=kind,
        consequence=consequence,
        target_axiom_id=axiom_id,
    )


def _consequence(observation: str, if_true: str, if_false: str, discriminates: str) -> TestableConsequence:
    return TestableConsequence(
        observation=observation, if_true=if_true, if_false=if_false, discriminates=discriminates
    )


def _focus(axiom: Any, proposition: Proposition | None) -> str:
    """The short name for what the axiom is about."""
    if proposition is not None and proposition.subject.strip():
        return proposition.subject.strip().rstrip("?").strip()
    text = canon(getattr(axiom, "text", str(axiom)))
    return text or "the claim"


# --------------------------------------------------------------------------- #
# The seven operators
# --------------------------------------------------------------------------- #

def invert_axiom(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """Take the axiom at its word and deny it.

    This is the blunt operator, and it is the one that has to be here: before
    anything clever, ask whether the data can support the claim at all.
    """
    focus = _focus(axiom, proposition)
    text = getattr(axiom, "text", str(axiom))
    return [
        candidate(
            f"the data is insufficient to support '{text}': nothing in the record "
            f"distinguishes a real change in {focus} from normal variation",
            operator="axiom_inverter",
            question=question,
            target_axiom=axiom,
            kind="DATA_INSUFFICIENT",
            consequence=_consequence(
                observation=(
                    f"hold out the most recent third of the history, refit whatever rule "
                    f"was derived from the earlier two thirds, and score it on the held-out part"
                ),
                if_true=(
                    "the rule scores no better than the base rate on held-out history, "
                    "so the data carries no usable signal"
                ),
                if_false=(
                    "the rule scores materially better than the base rate on held-out "
                    "history, so the data does carry signal and this inversion is refuted"
                ),
                discriminates="the data is sufficient vs the data is insufficient",
            ),
        )
    ]


def attack_scope(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """The finding holds inside one workflow and is reported across the whole scope."""
    declared = question.value("scope") or "the declared scope"
    focus = _focus(axiom, proposition)
    return [
        candidate(
            f"'{axiom.text}' holds inside a single workflow but not across {declared}: "
            f"the regularity in {focus} is a property of one process, not of the class",
            operator="scope_attacker",
            question=question,
            target_axiom=axiom,
            kind="SCOPE_COLLAPSE",
            consequence=_consequence(
                observation=(
                    f"estimate the regularity separately in every workflow and compare the "
                    f"within-workflow effect size with the pooled effect size across {declared}"
                ),
                if_true=(
                    "the pooled effect is larger than most within-workflow effects, which is "
                    "what pooling dissimilar processes produces"
                ),
                if_false=(
                    "the within-workflow effects bracket the pooled effect, so the regularity "
                    "does transfer and this inversion is refuted"
                ),
                discriminates="the effect generalises across the scope vs it is one workflow's property",
            ),
        )
    ]


def attack_causality(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """The arrow points the other way, or there is no arrow, only sequence."""
    focus = _focus(axiom, proposition)
    return [
        candidate(
            f"the ordering is reversed: the delay does not follow from {focus}, "
            f"rather the delay causes the state that was read as {focus}",
            operator="causal_attacker",
            question=question,
            target_axiom=axiom,
            kind="REVERSE_CAUSATION",
            consequence=_consequence(
                observation=(
                    "find the earliest recorded timestamp of the supposed cause and the "
                    "supposed effect for every case, and count how often the effect precedes "
                    "the cause"
                ),
                if_true=(
                    "the effect precedes the cause in a substantial share of cases, which no "
                    "forward causal story can produce"
                ),
                if_false=(
                    "the cause precedes the effect in essentially every case, in which case "
                    "this inversion is refuted and the forward story survives"
                ),
                discriminates="the cause precedes the effect vs the order is reversed",
            ),
        )
    ]


def attack_temporal_validity(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """The definition, the process, or the measurement changed inside the window."""
    focus = _focus(axiom, proposition)
    return [
        candidate(
            f"the definition of {focus} changed during the window, so the history is "
            f"not one process and cannot be pooled",
            operator="temporal_attacker",
            question=question,
            target_axiom=axiom,
            kind="TEMPORAL_DRIFT",
            consequence=_consequence(
                observation=(
                    "split the history at every candidate change point and test whether the "
                    "distribution of the outcome, or the throughput of the process, differs "
                    "materially across the split"
                ),
                if_true=(
                    "at least one split separates two populations, so the window contains more "
                    "than one regime and any pooled estimate mixes them"
                ),
                if_false=(
                    "no split separates the populations, so the window is one regime and this "
                    "inversion is refuted"
                ),
                discriminates="the window is one regime vs the window contains a regime change",
            ),
        )
    ]


def attack_authority(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """The party that defines the failure is the party the finding judges."""
    declared = question.value("authority") or "the party named in the question"
    return [
        candidate(
            f"{declared} defines what counts as failure and is also the party whose "
            f"performance that definition measures, so the definition is not independent "
            f"of the result",
            operator="authority_attacker",
            question=question,
            target_axiom=axiom,
            kind="AUTHORITY_GAP",
            consequence=_consequence(
                observation=(
                    "recompute the finding under two independently supplied definitions of "
                    "failure, one from the measured party and one from the customer"
                ),
                if_true=(
                    "the two definitions rank the candidate interventions differently, so the "
                    "conclusion depends on who wrote the definition"
                ),
                if_false=(
                    "both definitions rank the interventions the same way, so the finding is "
                    "robust to the definition and this inversion is refuted"
                ),
                discriminates="the finding is definition-independent vs definition-dependent",
            ),
        )
    ]


def attack_measurement(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """The measurement system produced the pattern it claims to have found."""
    focus = _focus(axiom, proposition)
    return [
        candidate(
            f"the apparent pattern in {focus} is produced by how the lag is measured: "
            f"the clock, the rounding, or the definition of 'complete' creates it",
            operator="measurement_attacker",
            question=question,
            target_axiom=axiom,
            kind="MEASUREMENT_ARTIFACT",
            consequence=_consequence(
                observation=(
                    "recompute the same statistic after replacing each recorded timestamp "
                    "with its value rounded to the coarser granularity the instrument "
                    "actually supports, and compare the two results"
                ),
                if_true=(
                    "the pattern appears, strengthens or vanishes under the coarser clock, "
                    "so the instrument's resolution is doing the work"
                ),
                if_false=(
                    "the pattern is unchanged under the coarser clock, so it is not an "
                    "instrument artifact and this inversion is refuted"
                ),
                discriminates="the pattern is in the process vs the pattern is in the clock",
            ),
        ),
        candidate(
            f"the apparent pattern in {focus} is an artifact of the level of aggregation "
            f"at which the records were reported",
            operator="measurement_attacker",
            question=question,
            target_axiom=axiom,
            kind="AGGREGATION",
            consequence=_consequence(
                observation=(
                    "compute the association at the reported level and again within each "
                    "group, and compare the sign of the association between the two levels"
                ),
                if_true=(
                    "the association has one sign when pooled and the opposite sign inside "
                    "most groups, which is the signature of an aggregation artifact"
                ),
                if_false=(
                    "the association keeps its sign at both levels, so aggregation does not "
                    "explain it and this inversion is refuted"
                ),
                discriminates="a real association vs a pooled-only association",
            ),
        ),
    ]


def attack_failure_mode(axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    """Only the observable failures were observed.

    This operator also emits one candidate with no consequence at all. That is
    deliberate: "the recording system is the problem" is a real intuition and an
    untestable sentence, and the honest thing to do with it is to hand it to the
    gate and let the gate refuse it rather than to dress it up as a hypothesis.
    """
    focus = _focus(axiom, proposition)
    return [
        candidate(
            f"the expensive failure mode in {focus} is unobserved: the events that would "
            f"record it are the events that never get written",
            operator="failure_attacker",
            question=question,
            target_axiom=axiom,
            kind="UNOBSERVED_FAILURE",
            consequence=_consequence(
                observation=(
                    "count records per process step per period and look for steps whose "
                    "record count falls while the downstream outcome worsens"
                ),
                if_true=(
                    "at least one step's record count falls as the outcome worsens, so the "
                    "missing records and the missing successes are the same events"
                ),
                if_false=(
                    "record counts are stable while the outcome worsens, so nothing is being "
                    "lost to non-observation and this inversion is refuted"
                ),
                discriminates="the failures are all observed vs some failures are unrecorded",
            ),
        ),
        candidate(
            f"only the failures that were noticed were recorded, so the observed rate of "
            f"{focus} is a rate of reporting rather than a rate of occurrence",
            operator="failure_attacker",
            question=question,
            target_axiom=axiom,
            kind="SELECTION_EFFECT",
            consequence=_consequence(
                observation=(
                    "compare the recorded failure rate in periods with a high and a low "
                    "reporting load, holding demand roughly constant"
                ),
                if_true=(
                    "the recorded rate tracks the reporting load rather than demand, so the "
                    "record measures attention"
                ),
                if_false=(
                    "the recorded rate tracks demand and not the reporting load, so the "
                    "record measures occurrence and this inversion is refuted"
                ),
                discriminates="the rate of occurrence vs the rate of reporting",
            ),
        ),
        candidate(
            f"the recording system itself is the problem behind {focus}",
            operator="failure_attacker",
            question=question,
            target_axiom=axiom,
            kind="UNOBSERVED_FAILURE",
            consequence=None,
        ),
    ]


OPERATOR_FUNCTIONS: dict[str, Callable[..., list[Inversion]]] = {
    "axiom_inverter": invert_axiom,
    "scope_attacker": attack_scope,
    "causal_attacker": attack_causality,
    "temporal_attacker": attack_temporal_validity,
    "authority_attacker": attack_authority,
    "measurement_attacker": attack_measurement,
    "failure_attacker": attack_failure_mode,
}


def run(operator: str, axiom: Any, question: Question, *, proposition: Proposition | None = None) -> list[Inversion]:
    if operator not in OPERATOR_FUNCTIONS:
        raise ValueError(f"unknown operator {operator!r}; choose from {OPERATORS}")
    return list(OPERATOR_FUNCTIONS[operator](axiom, question, proposition=proposition))
