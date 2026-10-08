"""Which question to ask next, and why that one.

The controller's real question is *"what is the next question whose answer would
most reduce uncertainty or produce the most valuable discriminating experiment?"*
This module is the arithmetic behind that sentence.

It is an ORDINAL measure. It says question A outranks question B; it does not say
by how much in any calibrated unit, and nothing here calls a model.

The gain is computed **from state**, not from the candidate alone. That matters:
the same ambiguity is worth more in a run where twenty open hypotheses depend on
that slot than in a run where none do, and a candidate that carries its own
estimate does not get to set its own price.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .state import State

__all__ = ["SEVERITY_WEIGHT", "KIND_BASE", "information_gain", "rank", "gain_report"]

SEVERITY_WEIGHT = {"BLOCKING": 3.0, "MATERIAL": 2.0, "MINOR": 1.0}

#: Base weight per candidate kind. ``None`` means "derived", not "defaulted":
#: AMBIGUITY reads its severity, DISCRIMINATION counts what it separates.
KIND_BASE: dict[str, float | None] = {
    "AMBIGUITY": None,
    "KNOWLEDGE_GAP": 1.5,
    "DISCRIMINATION": None,
    "GENERALIZATION": 2.0,
    "INTERVENTION": 2.5,
}
DEFAULT_BASE = 1.0


def _field(candidate: Any, name: str, default: Any = None) -> Any:
    """Read one field from a GeneratedQuestion-like object or a plain mapping."""
    if isinstance(candidate, Mapping):
        return candidate.get(name, default)
    return getattr(candidate, name, default)


def _as_list(value: Any) -> list[Any]:
    if value is None or isinstance(value, str):
        return [] if value is None else [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _base(candidate: Any, state: State) -> tuple[float, str]:
    kind = str(_field(candidate, "kind", "") or "").upper()
    if kind == "AMBIGUITY":
        severity = str(_field(candidate, "severity", "") or "").upper()
        weight = SEVERITY_WEIGHT.get(severity, DEFAULT_BASE)
        return weight, f"severity {severity or 'unspecified'} weighs {weight:g}"
    if kind == "DISCRIMINATION":
        separates = _as_list(_field(candidate, "discriminates"))
        count = len(separates) if separates else len(state.open_hypotheses())
        return 1.0 + count, f"separates {count} hypothesis(es)"
    if kind in KIND_BASE and KIND_BASE[kind] is not None:
        base = float(KIND_BASE[kind])  # type: ignore[arg-type]
        return base, f"kind {kind} weighs {base:g}"
    return DEFAULT_BASE, f"unrecognised kind {kind or 'none'} falls back to {DEFAULT_BASE:g}"


def information_gain(candidate: Any, state: State) -> float:
    """Expected uncertainty reduction, ordinal.

    ``base(kind)`` x ``(1 + open hypotheses that stand or fall with this question)``
    x a factor of 1.0 when the targeted slot is still unresolved in state and 0.5
    when it is not. A candidate aimed at a slot somebody already filled is worth
    half as much; it is not worth nothing, because a filled slot can still be
    filled wrongly.

    The dependency count is what makes this a *state* measurement rather than a
    property of the sentence: resolving a slot of question Q lowers uncertainty
    for every still-open hypothesis answering Q, so the same ambiguity is worth
    more in a run with five live explanations than in a run with none.
    """
    base, _ = _base(candidate, state)
    dependencies = _dependents(candidate, state)
    still_open = _slot_is_open(state, _field(candidate, "slot_targeted"))
    return round(base * (1 + dependencies) * (1.0 if still_open else 0.5), 6)


def _dependents(candidate: Any, state: State) -> int:
    """Open hypotheses that would be affected by this question being answered."""
    open_hypotheses = state.open_hypotheses()
    parent = _field(candidate, "parent") or _field(candidate, "question")
    if not parent:
        return len(open_hypotheses)
    return sum(1 for h in open_hypotheses if str(h.get("question")) == str(parent))


def _slot_is_open(state: State, slot: Any) -> bool:
    if not slot or not state.questions:
        return True
    return any(str(slot) in q.unresolved() for q in state.questions.values())


def _because(candidate: Any, state: State) -> str:
    base, why_base = _base(candidate, state)
    slot = _field(candidate, "slot_targeted")
    parts = [why_base]
    if slot:
        parts.append(
            f"targets slot '{slot}', which is "
            f"{'still open' if _slot_is_open(state, slot) else 'already answered (halved)'}"
        )
    else:
        parts.append("targets no particular slot")
    parts.append(f"{_dependents(candidate, state)} open hypothesis(es) stand on this question")
    estimate = _field(candidate, "information_gain")
    if isinstance(estimate, (int, float)):
        parts.append(f"the candidate offered its own estimate {estimate:g}, which is not what set this number")
    parts.append(f"base {base:g}")
    return "; ".join(parts)


def rank(candidates: Iterable[Any], state: State) -> list[dict[str, Any]]:
    """Every candidate scored, highest gain first, ties broken on gid so a run is
    reproducible rather than order-dependent."""
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        gid = str(_field(candidate, "gid", "") or "")
        rows.append(
            {
                "gid": gid,
                "text": str(_field(candidate, "text", "") or ""),
                "kind": str(_field(candidate, "kind", "") or ""),
                "slot": _field(candidate, "slot_targeted"),
                "gain": information_gain(candidate, state),
                "because": _because(candidate, state),
            }
        )
    rows.sort(key=lambda r: (-r["gain"], r["gid"]))
    return rows


def gain_report(candidates: Sequence[Any], state: State) -> dict[str, Any]:
    """The ranking plus the one line the controller needs: what to ask next."""
    ranked = rank(candidates, state)
    nxt = ranked[0]["gid"] if ranked else None
    if not ranked:
        why = "no candidate questions were offered"
    else:
        top = ranked[0]
        runner = ranked[1] if len(ranked) > 1 else None
        head = f"{top['gid']} has the highest information gain ({top['gain']:g}): {top['because']}"
        why = head + (
            f"; next best is {runner['gid']} at {runner['gain']:g}"
            if runner is not None
            else "; it is the only candidate"
        )
    return {"ranked": ranked, "next": nxt, "why": why}
