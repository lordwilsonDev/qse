"""Ambiguity detection: what the question fails to say.

The point of this module is that an underspecified question is *described*, not
rejected. Every ambiguity records the rule that found it, why it matters, and the
question that would resolve it -- so a reader can disagree with a specific rule
instead of arguing about the whole decomposition.

Two kinds of rule:

* **term rules** fire on cue phrases in the raw text ("before" is a relative
  time, "predict" is an undefined capability word);
* **structural rules** (``terms=()``) fire on the *state* of a slot, e.g. an
  authority slot nobody has filled.

Both are suppressed for a slot an operator has already answered (confidence
``STATED``) -- unless the caller passes ``as_asked=True``. Then a stated slot
does not suppress its rules; the record is fired and marked ``closed``. The
difference matters: the ambiguity was real *in the question as it was asked*, and
the operator's answer is what closed it. Suppressing it deletes the defect from
the audit trail and leaves the before/after comparison it feeds with nothing to
compare, so ``as_asked=True`` is what the controller uses. An *inferred* value
never suppresses anything: the engine guessing a slot is exactly what creates
the ambiguity worth reporting.

No model call is involved, so the same question always yields the same
ambiguities in the same order.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from ..core.proposition import MODALITIES, Proposition, parse_proposition
from ..core.question import BLOCKING_SLOTS, STATED, SLOTS, Question
from ..ids import canon, new_id

KINDS = (
    "UNDEFINED_TERM",
    "VAGUE_QUANTIFIER",
    "MISSING_AUTHORITY",
    "RELATIVE_TIME",
    "UNBOUNDED_SCOPE",
    "CONTESTED_DEFINITION",
    "UNMEASURED_OUTCOME",
    "MODALITY_MISMATCH",
)
SEVERITIES = ("BLOCKING", "MATERIAL", "MINOR")

#: BLOCKING stops consumption of the question; MATERIAL changes what counts as an
#: answer; MINOR is worth writing down and not worth blocking on.
SEVERITY_WEIGHT = {"BLOCKING": 3.0, "MATERIAL": 2.0, "MINOR": 1.0}
_SEVERITY_RANK = {name: i for i, name in enumerate(SEVERITIES)}

#: Kind used when a slot is simply unfilled and no term rule covered it.
SLOT_KIND = {
    "referential": "UNDEFINED_TERM",
    "proposition": "UNDEFINED_TERM",
    "scope": "UNBOUNDED_SCOPE",
    "authority": "MISSING_AUTHORITY",
    "obligation": "UNMEASURED_OUTCOME",
    "temporal": "RELATIVE_TIME",
    "consumption": "CONTESTED_DEFINITION",
}


@dataclass(frozen=True)
class AmbiguityRule:
    """One inspectable rule. ``terms=()`` means the rule is structural."""

    id: str
    slot: str
    kind: str
    severity: str
    terms: tuple[str, ...]
    why: str
    resolving_question: str
    #: when non-empty, the rule only fires if the parsed proposition has this modality
    requires_modality: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.slot not in SLOTS:
            raise ValueError(f"rule {self.id}: unknown slot {self.slot!r}")
        if self.kind not in KINDS:
            raise ValueError(f"rule {self.id}: unknown kind {self.kind!r}")
        if self.severity not in SEVERITIES:
            raise ValueError(f"rule {self.id}: unknown severity {self.severity!r}")
        for modality in self.requires_modality:
            if modality not in MODALITIES:
                raise ValueError(f"rule {self.id}: unknown modality {modality!r}")


@dataclass
class Ambiguity:
    aid: str
    qid: str
    slot: str
    term: str
    kind: str
    severity: str
    why: str
    resolving_question: str
    rule: str
    #: True when the operator's answer for this slot already resolves the
    #: ambiguity. Set by ``detect(..., as_asked=True)``; a finding that was real
    #: in the question as asked and has since been answered is still a finding.
    closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Ambiguity":
        return cls(
            aid=str(payload["aid"]),
            qid=str(payload.get("qid", "")),
            slot=str(payload.get("slot", "")),
            term=str(payload.get("term", "")),
            kind=str(payload.get("kind", "")),
            severity=str(payload.get("severity", "MATERIAL")),
            why=str(payload.get("why", "")),
            resolving_question=str(payload.get("resolving_question", "")),
            rule=str(payload.get("rule", "")),
            closed=bool(payload.get("closed", False)),
        )


# --------------------------------------------------------------------------- #
# Cue matching
# --------------------------------------------------------------------------- #

#: Inflection suffixes allowed after a cue, so "bottleneck" finds "bottlenecks"
#: and "predict" finds "prediction" without "predict" matching "predictable"
#: being missed. Ordered so the regex backtracks correctly.
_SUFFIX = r"(?:s|es|ing|ed|ions|ion|ively|ive|ables|able|ably|ities|ity|ors|or|ally|al)?"

_PATTERNS: dict[str, re.Pattern[str]] = {}


def term_pattern(term: str) -> re.Pattern[str]:
    """A word-boundary regex for one cue phrase. Cached; deterministic."""
    key = canon(term)
    hit = _PATTERNS.get(key)
    if hit is None:
        core = r"\s+".join(re.escape(part) for part in key.split())
        hit = re.compile(rf"(?<![a-z0-9]){core}{_SUFFIX}(?![a-z0-9])")
        _PATTERNS[key] = hit
    return hit


def matches(text: str, term: str) -> bool:
    """True when ``term`` appears in ``text`` as a word, allowing inflections."""
    return bool(term_pattern(term).search(canon(text)))


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #

RULES: tuple[AmbiguityRule, ...] = (
    # -- referential: what is being referred to -------------------------- #
    AmbiguityRule(
        id="AMB-REF-001",
        slot="referential",
        kind="UNDEFINED_TERM",
        severity="BLOCKING",
        terms=("bottleneck",),
        why=(
            "'operational bottleneck' is named and never defined; two people can disagree about "
            "what counts as one without either being wrong"
        ),
        resolving_question=(
            "What is the operational definition of '{term}' here -- which measurable quantity, "
            "over what interval, for which process?"
        ),
    ),
    AmbiguityRule(
        id="AMB-REF-002",
        slot="referential",
        kind="UNDEFINED_TERM",
        severity="BLOCKING",
        terms=("system", "workflow", "business process", "platform", "pipeline"),
        why="the system the claim is about is named only generically, so the claim has no referent to be tested against",
        resolving_question="Which specific '{term}' is meant -- name the process, its boundary, and who owns it?",
    ),
    AmbiguityRule(
        id="AMB-REF-003",
        slot="referential",
        kind="UNDEFINED_TERM",
        severity="BLOCKING",
        terms=("failure",),
        why="'failure' is named but no threshold distinguishes a failure from normal variation",
        resolving_question=(
            "What constitutes a '{term}' in measurable terms -- which threshold, over which "
            "interval, and who is authorized to declare it?"
        ),
    ),
    # -- proposition: what is actually claimed --------------------------- #
    AmbiguityRule(
        id="AMB-PROP-001",
        slot="proposition",
        kind="UNDEFINED_TERM",
        severity="BLOCKING",
        terms=("predict",),
        why=(
            "'predict' is undefined: a lead time, an accuracy level and a permitted false-alarm "
            "rate are all implied and none is stated"
        ),
        resolving_question=(
            "Does '{term}' mean a threshold crossed at least N hours before a verified failure, "
            "and what lead time and error rate are acceptable?"
        ),
    ),
    AmbiguityRule(
        id="AMB-PROP-002",
        slot="proposition",
        kind="MODALITY_MISMATCH",
        severity="MATERIAL",
        terms=("reduce", "prevent", "improve", "lower", "increase", "cause", "drive"),
        requires_modality=("PREDICTABLE", "DETECTABLE"),
        why=(
            "the question is phrased as prediction or detection but also claims an effect, which is "
            "a causal proposition wearing a predictive sentence"
        ),
        resolving_question=(
            "Is the claim that a precursor can be '{term}d' in advance, or that acting on it changes "
            "the outcome -- and which of the two is the thing that must be proven?"
        ),
    ),
    # -- temporal -------------------------------------------------------- #
    AmbiguityRule(
        id="AMB-TMP-001",
        slot="temporal",
        kind="RELATIVE_TIME",
        severity="BLOCKING",
        terms=("before", "ahead of", "in advance", "prior to", "early enough", "lead time"),
        why=(
            "'{term}' is a relative time with no anchor: without an N and a definition of the "
            "event being led, no observation can confirm or refute the claim"
        ),
        resolving_question="At least how many hours or days '{term}' which verified event, measured on which clock?",
    ),
    AmbiguityRule(
        id="AMB-TMP-002",
        slot="temporal",
        kind="RELATIVE_TIME",
        severity="MATERIAL",
        terms=("current", "as of", "real-time", "today", "right now"),
        why="'{term}' has no timestamp, so evidence from any period could be claimed to satisfy it",
        resolving_question="As of which date is '{term}' to be evaluated, and what is the evidence-validity window?",
    ),
    # -- scope ----------------------------------------------------------- #
    AmbiguityRule(
        id="AMB-SCP-001",
        slot="scope",
        kind="UNBOUNDED_SCOPE",
        severity="BLOCKING",
        terms=("fortune 500", "enterprise", "company", "companies", "organization", "organisation", "firm"),
        why=(
            "'{term}' names a class of organization rather than bounding the claim; a result inside one "
            "workflow would be reported as though it held across all of them"
        ),
        resolving_question="Which specific '{term}', which business process, and which sites or regions does the claim range over?",
    ),
    AmbiguityRule(
        id="AMB-SCP-002",
        slot="scope",
        kind="UNBOUNDED_SCOPE",
        severity="MATERIAL",
        terms=("historical", "history", "cross-company", "all departments", "every department"),
        why="'{term}' does not say which window or which units are inside the scope and which are excluded",
        resolving_question="Which period and which units do you mean by '{term}', and what is explicitly out of scope?",
    ),
    # -- authority ------------------------------------------------------- #
    AmbiguityRule(
        id="AMB-AUT-001",
        slot="authority",
        kind="MISSING_AUTHORITY",
        severity="BLOCKING",
        terms=(),
        why=(
            "nobody is named who may define failure or validate the result, so a finding could be "
            "true and still not acceptable to the people who own the decision"
        ),
        resolving_question="Who is authorized to define failure here, who owns the data, and who may validate a result?",
    ),
    # -- obligation ------------------------------------------------------ #
    AmbiguityRule(
        id="AMB-OBL-001",
        slot="obligation",
        kind="UNMEASURED_OUTCOME",
        severity="BLOCKING",
        terms=("expensive", "costly", "losing", "losses", "millions", "billions"),
        why="'{term}' names harm without a unit, so no result can be shown to have reduced it",
        resolving_question="In which unit is '{term}' to be measured, against which baseline, over which period?",
    ),
    AmbiguityRule(
        id="AMB-OBL-002",
        slot="obligation",
        kind="UNMEASURED_OUTCOME",
        severity="MATERIAL",
        terms=("delay", "late", "backlog", "outage", "downtime", "rework", "defect", "churn"),
        why="'{term}' is the thing to be reduced but the quantity that would show a reduction is not stated",
        resolving_question="Which measurable quantity represents '{term}' -- orders late, hours late, or dollars lost?",
    ),
    # -- consumption ----------------------------------------------------- #
    AmbiguityRule(
        id="AMB-CON-001",
        slot="consumption",
        kind="CONTESTED_DEFINITION",
        severity="MATERIAL",
        terms=("management", "leadership", "executives", "board", "stakeholders", "we"),
        why=(
            "the consumer is named as a group, and the question itself says the group disagrees; "
            "which member's definition the result must satisfy is unstated"
        ),
        resolving_question="Which named consumer will act on '{term}', what decision will they make, and what happens if the result is wrong?",
    ),
    # -- quantifiers ----------------------------------------------------- #
    AmbiguityRule(
        id="AMB-QTY-001",
        slot="referential",
        kind="VAGUE_QUANTIFIER",
        severity="MATERIAL",
        terms=("millions", "many", "most", "significant", "often", "several", "a lot", "substantial", "major"),
        why="'{term}' is a quantity with no number attached, so any result could be called consistent with it",
        resolving_question="How many, how often, or how much does '{term}' mean as a number?",
    ),
    AmbiguityRule(
        id="AMB-QTY-002",
        slot="obligation",
        kind="VAGUE_QUANTIFIER",
        severity="MINOR",
        terms=("better", "faster", "improve", "reduced", "increased", "more efficient"),
        why="'{term}' states a direction without a magnitude, so a result of any size would satisfy it",
        resolving_question="By how much must something '{term}' for the result to count as success?",
    ),
)


def rule(id_: str) -> AmbiguityRule:
    for candidate in RULES:
        if candidate.id == id_:
            return candidate
    raise KeyError(f"no ambiguity rule {id_!r}")


def _emit(rule_: AmbiguityRule, question: Question, term: str, *, closed: bool = False) -> Ambiguity:
    resolving = rule_.resolving_question
    if "{term}" in resolving:
        resolving = resolving.replace("{term}", term)
    return Ambiguity(
        aid=new_id("AMB", question.qid, rule_.id, rule_.slot, term),
        qid=question.qid,
        slot=rule_.slot,
        term=term,
        kind=rule_.kind,
        severity=rule_.severity,
        why=rule_.why,
        resolving_question=resolving,
        rule=rule_.id,
        closed=closed,
    )


def detect(
    question: Question,
    *,
    proposition: Proposition | None = None,
    as_asked: bool = False,
) -> list[Ambiguity]:
    """Every ambiguity the rules find, ordered BLOCKING -> MATERIAL -> MINOR.

    A slot an operator answered with ``answers=`` (confidence ``STATED``) does not
    produce ambiguities: the point of asking is that the answer removes them.

    ``as_asked=True`` changes that back: the rules fire, and each finding carries
    ``closed=True`` when a stated slot already answers it. Use it to report the
    question as it was put, alongside which of its defects the brief settled --
    which is the only way the before/after blindspot count can see a repair.
    """
    if proposition is None:
        try:
            proposition = parse_proposition(question.raw)
        except ValueError:
            proposition = None

    found: list[Ambiguity] = []
    for rule_ in RULES:
        slot = question.slots[rule_.slot]
        stated = slot.confidence == STATED
        if stated and not as_asked:
            continue
        if rule_.terms:
            if rule_.requires_modality and (
                proposition is None or proposition.modality not in rule_.requires_modality
            ):
                continue
            for term in rule_.terms:
                if matches(question.raw, term):
                    found.append(_emit(rule_, question, term, closed=stated))
        else:
            # Structural rule: the slot has no value at all.
            if not slot.filled:
                found.append(_emit(rule_, question, rule_.slot, closed=stated))

    found.sort(key=lambda a: (_SEVERITY_RANK[a.severity], a.aid))
    unique: list[Ambiguity] = []
    seen: set[str] = set()
    for item in found:
        if item.aid in seen:
            continue
        seen.add(item.aid)
        unique.append(item)
    return unique


def blocking(ambiguities: Sequence[Ambiguity]) -> list[Ambiguity]:
    return [a for a in ambiguities if a.severity == "BLOCKING"]


def by_slot(ambiguities: Sequence[Ambiguity]) -> dict[str, list[Ambiguity]]:
    out: dict[str, list[Ambiguity]] = {name: [] for name in SLOTS}
    for item in ambiguities:
        out[item.slot].append(item)
    return out


def kinds(ambiguities: Sequence[Ambiguity]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in ambiguities:
        out[item.kind] = out.get(item.kind, 0) + 1
    return out


def unresolved_slots(question: Question, ambiguities: Sequence[Ambiguity]) -> list[str]:
    """Slots still open after detection, blocking ones first."""
    open_slots = {a.slot for a in ambiguities}
    ranked = [name for name in BLOCKING_SLOTS if name in open_slots]
    ranked += sorted(name for name in open_slots if name not in ranked)
    return ranked
