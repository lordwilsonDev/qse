"""Evidence sufficiency: is there actually enough here to believe anything?

This is the arithmetic the gate refuses on. Unusable evidence is counted and
displayed -- deleting a model proposal raises the apparent support of whatever
survived it, which is the same defect as dropping a failed test -- but it
contributes zero weight and can never make a hypothesis sufficient.

Direction is tracked separately from class. Usable evidence *against* a
hypothesis is evidence, and a hypothesis carrying both is `contested`, which is
a finding rather than a problem to be averaged away.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..core.evidence import Evidence
from ..core.hypothesis import Hypothesis


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


def _hids(raw: Iterable[Any]) -> list[str]:
    out: list[str] = []
    for item in raw or ():
        if isinstance(item, Hypothesis):
            out.append(item.hid)
        elif isinstance(item, Mapping) and "hid" in item:
            out.append(str(item["hid"]))
        elif isinstance(item, str):
            out.append(item)
    return out


def sufficiency(
    hypotheses: Iterable[Any],
    evidence: Iterable[Any],
    *,
    minimum: int = 1,
) -> dict[str, dict[str, Any]]:
    """One row per hypothesis: what is usable, what is not, and which way it points.

    `sufficient` means *minimum usable items after the firewall*, not "we feel
    good about it". An empty evidence list is a row of zeros with
    ``sufficient: False``, never a missing key -- a hypothesis nobody tested and
    a hypothesis that was tested and came back empty are different situations,
    and both are the opposite of sufficient.
    """
    if minimum < 1:
        raise ValueError("minimum must be at least 1; otherwise nothing is ever required")
    rows: dict[str, dict[str, Any]] = {}
    for hid in _hids(hypotheses):
        rows[hid] = {
            "usable": 0, "unusable": 0, "for": 0, "against": 0,
            "weight": 0.0, "classes": {}, "sufficient": False,
        }
    for record in _evidence(evidence):
        row = rows.get(record.hypothesis)
        if row is None:
            # Evidence for a hypothesis that is not in this question's set. It is
            # still real, so it gets its own row rather than being discarded.
            row = rows.setdefault(record.hypothesis, {
                "usable": 0, "unusable": 0, "for": 0, "against": 0,
                "weight": 0.0, "classes": {}, "sufficient": False,
            })
        if not record.usable():
            row["unusable"] += 1
            continue
        row["usable"] += 1
        row["classes"][record.kind] = row["classes"].get(record.kind, 0) + 1
        if record.supports:
            row["for"] += 1
            row["weight"] += record.weight()
        else:
            row["against"] += 1
            row["weight"] -= record.weight()
    for row in rows.values():
        row["sufficient"] = row["usable"] >= minimum
    return rows


def meets_bar(hypotheses: Iterable[Any], evidence: Iterable[Any], *, minimum: int = 1) -> bool:
    """True only when EVERY hypothesis in the set carries enough usable evidence."""
    rows = sufficiency(hypotheses, evidence, minimum=minimum)
    return bool(rows) and all(row["sufficient"] for row in rows.values())


def unsupported(hypotheses: Iterable[Any], evidence: Iterable[Any], *, minimum: int = 1) -> list[str]:
    """Hypotheses with too little usable evidence, in input order."""
    rows = sufficiency(hypotheses, evidence, minimum=minimum)
    return [hid for hid in _hids(hypotheses) if not rows.get(hid, {}).get("sufficient", False)]


def contested(evidence: Iterable[Any]) -> list[dict[str, Any]]:
    """Hypotheses carrying usable evidence both for and against.

    Reported, not resolved. A run that quietly picks the larger number here has
    thrown away the disagreement it was built to preserve.
    """
    seen: dict[str, dict[str, Any]] = {}
    for record in _evidence(evidence):
        if not record.usable():
            continue
        row = seen.setdefault(record.hypothesis, {"for": [], "against": []})
        row["for" if record.supports else "against"].append(record.eid)
    out: list[dict[str, Any]] = []
    for hid, row in seen.items():
        if row["for"] and row["against"]:
            out.append({"hid": hid, "for": sorted(row["for"]), "against": sorted(row["against"])})
    return sorted(out, key=lambda r: r["hid"])
