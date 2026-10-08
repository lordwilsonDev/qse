"""Build specifications: what is about to be built, and how it will be judged.

A specification is the artifact's contract with its own verification. The
acceptance list is written here, before generation, from the hypothesis's own
structural fields -- so the generated artifact cannot be graded against criteria
chosen after somebody saw how it turned out.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from ..core.evidence import Evidence
from ..core.hypothesis import Hypothesis
from ..ids import new_id

__all__ = ["BuildSpec", "from_hypothesis", "acceptance_for", "measured_columns",
           "outcome_columns"]


@dataclass
class BuildSpec:
    sid: str
    hypothesis: str
    artifact_kind: str
    title: str
    sections: tuple[str, ...] = ()
    acceptance: tuple[str, ...] = ()
    inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("a build specification needs a title")
        if not self.acceptance:
            raise ValueError(
                "a build specification needs acceptance criteria; an artifact with no "
                "criteria can only be declared done, never demonstrated"
            )
        self.sections = tuple(str(s) for s in self.sections)
        self.acceptance = tuple(str(a) for a in self.acceptance)
        self.inputs = tuple(str(i) for i in self.inputs)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        return {k: (list(v) if isinstance(v, tuple) else v) for k, v in out.items()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "BuildSpec":
        return cls(
            sid=str(payload["sid"]),
            hypothesis=str(payload.get("hypothesis", "")),
            artifact_kind=str(payload["artifact_kind"]),
            title=str(payload["title"]),
            sections=tuple(str(s) for s in payload.get("sections", ())),
            acceptance=tuple(str(a) for a in payload.get("acceptance", ())),
            inputs=tuple(str(i) for i in payload.get("inputs", ())),
        )


def acceptance_for(hypothesis: Hypothesis) -> tuple[str, ...]:
    """Criteria fixed before generation, written from the hypothesis itself."""
    return (
        "the module runs under `python3 <file> <rows.json>` with no arguments and exits 0",
        "decide(row) returns flag, reason, action and value for every row, including a row "
        "whose field is absent or non-numeric",
        "the same rows produce byte-identical output on two runs",
        f"the module names the hypothesis it implements ({hypothesis.hid})",
        f"the rule is stated in terms of {hypothesis.locus.lower()} and survives relaxing "
        f"the measurement assumption {hypothesis.measurement_assumption!r}",
    )


def measured_columns(evidence: tuple[Evidence, ...] | list[Evidence] | tuple = ()) -> tuple[str, ...]:
    """The data columns the evidence actually looked at.

    ``inputs`` used to be built from ``Evidence.source``, which is the name of a
    dataset -- so the generated rule compared a *file name* against a threshold and
    flagged nothing. A source is where a number came from; a column is what the
    number is about, and only the runner's own observation knows the difference.
    """
    found: list[str] = []
    for item in evidence:
        observed = getattr(item, "observed", None)
        if not isinstance(observed, dict):
            continue
        # ``favours`` is the column a discrimination scan decided on. It is the
        # column the artifact will actually read, so it belongs in ``inputs`` -- and
        # omitting it here left the artifact declaring every column of the table as
        # its input while reading only one of them.
        for key in ("field", "precursor", "value", "x", "y", "group", "time", "column",
                    "favours"):
            value = observed.get(key)
            if isinstance(value, str) and value and value not in found:
                found.append(value)
    return tuple(found)


def outcome_columns(evidence: tuple[Evidence, ...] | list[Evidence] | tuple = ()) -> tuple[str, ...]:
    """The columns the evidence names as the outcome being explained.

    A rule whose threshold is applied to the outcome it predicts is circular, and
    scoring it would be circular too. The runners already report which column is
    the outcome (``outcome`` on some observations, ``excluded_circular`` on the
    discrimination scan), so it is read back rather than guessed at, and it is
    never treated as an artifact input or as a detector field.
    """
    found: list[str] = []
    for item in evidence:
        observed = getattr(item, "observed", None)
        if not isinstance(observed, dict):
            continue
        outcome = observed.get("outcome")
        if isinstance(outcome, str) and outcome and outcome not in found:
            found.append(outcome)
        for column in observed.get("excluded_circular") or ():
            if isinstance(column, str) and column and column not in found:
                found.append(column)
    return tuple(found)


def from_hypothesis(
    hypothesis: Hypothesis,
    evidence: tuple[Evidence, ...] | list[Evidence] = (),
    *,
    artifact_kind: str = "DECISION_RULE",
    columns: tuple[str, ...] | list[str] = (),
) -> BuildSpec:
    """A specification derived from the hypothesis, not from a template."""
    raw_inputs = measured_columns(evidence) or tuple(str(c) for c in columns)
    # The outcome is what the artifact is judged against, never an input it reads to
    # decide. Dropping it here is what keeps a generated rule from sitting on it.
    outcomes = set(outcome_columns(evidence))
    inputs = tuple(i for i in raw_inputs if i not in outcomes) or raw_inputs
    title = f"{hypothesis.mechanism.title()} rule for {hypothesis.locus.lower()} bottleneck detection"
    sections = (
        f"claim: {hypothesis.text}",
        f"mechanism {hypothesis.mechanism} acting on {hypothesis.locus} at the "
        f"{hypothesis.timescale.lower()} timescale",
        f"measurement assumption: {hypothesis.measurement_assumption}",
        f"authority for being wrong: {hypothesis.authority}",
    )
    sid = new_id("SPEC", hypothesis.hid, artifact_kind, title)
    return BuildSpec(
        sid=sid,
        hypothesis=hypothesis.hid,
        artifact_kind=artifact_kind,
        title=title,
        sections=sections,
        acceptance=acceptance_for(hypothesis),
        inputs=inputs,
    )
