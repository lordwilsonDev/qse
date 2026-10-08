"""Provenance: where each piece of evidence came from, and whether that is enough.

Two questions, kept deliberately separate:

* is the record **complete** -- does it name a source, a method and a time?
* is the class **usable** -- may anything be consumed from it at all?

The second is ``Evidence.usable()``, the type's own firewall. This module must
never form a second opinion about it. If the two could disagree, one of them
would be wrong, and the one that decides the run is whichever got called last.
So ``usable`` here is read off the object, never recomputed.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from ..core.evidence import Evidence
from ..ids import canon

#: A record without these three cannot be traced back to what produced it.
REQUIRED_FIELDS = ("source", "method", "collected_at")


def _items(raw: Iterable[Any]) -> list[Evidence]:
    """Accept Evidence objects or their dict form; skip what cannot be read.

    A replay hands back dicts and the live engine hands back objects. Both are
    legitimate, and a single unreadable row must not take the audit down with it.
    """
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


def missing(evidence: Evidence) -> list[str]:
    """Which required provenance fields this record does not carry."""
    return [name for name in REQUIRED_FIELDS if not str(getattr(evidence, name, "") or "").strip()]


def complete(evidence: Evidence) -> bool:
    return not missing(evidence)


def trace(evidence: Evidence) -> dict[str, Any]:
    """Everything needed to walk back from a claim to the thing that produced it."""
    return {
        "eid": evidence.eid,
        "claim": evidence.claim,
        "source": evidence.source,
        "method": evidence.method,
        "collected_at": evidence.collected_at,
        "hypothesis": evidence.hypothesis,
        "experiment": evidence.experiment,
        "kind": evidence.kind,
        "supports": evidence.supports,
        "strength": evidence.strength,
        "usable": evidence.usable(),
    }


def audit(items: Iterable[Any]) -> dict[str, Any]:
    """Every record, split by completeness and by whether it may be consumed.

    The counts are meant to be read together. A run whose evidence is complete
    but entirely unusable has provable paperwork and no findings.
    """
    records = _items(items)
    incomplete: dict[str, list[str]] = {}
    unusable: dict[str, str] = {}
    ok: list[str] = []
    consumable: list[str] = []
    for record in records:
        gaps = missing(record)
        if gaps:
            incomplete[record.eid] = gaps
        else:
            ok.append(record.eid)
        if record.usable():
            consumable.append(record.eid)
        else:
            unusable[record.eid] = record.why_unusable()
    return {
        "n": len(records),
        "complete": ok,
        "incomplete": incomplete,
        "usable": consumable,
        "unusable": unusable,
        "complete_rate": (len(ok) / len(records)) if records else None,
    }


def sources(items: Iterable[Any]) -> dict[str, int]:
    """How many distinct sources the usable evidence actually rests on.

    One source reported five times is one source. This count is what the scope
    attack leans on, so it is computed here once rather than twice.
    """
    tally: dict[str, int] = {}
    for record in _items(items):
        if record.usable():
            tally[canon(record.source)] = tally.get(canon(record.source), 0) + 1
    return tally
