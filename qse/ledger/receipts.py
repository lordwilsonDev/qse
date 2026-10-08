"""Receipts and the reconstruction of *why* a question was asked.

The final acceptance test is not "does it work" but "can another process
reconstruct why the engine asked the questions it asked". That answer has to
come out of the ledger alone -- not from a docstring, not from the engine's
own memory of what it did -- so everything here reads records and nothing else.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping


def receipt(records: Iterable[Mapping[str, Any]]) -> str:
    """One line per event: sequence, type, subject, and the first useful detail."""
    out: list[str] = []
    for rec in records:
        subject = (
            rec.get("qid") or rec.get("hid") or rec.get("xid") or rec.get("eid")
            or rec.get("aid") or rec.get("atid") or rec.get("vid") or rec.get("oid")
            or rec.get("gid") or rec.get("did") or rec.get("operator") or "-"
        )
        detail = str(
            rec.get("statement") or rec.get("text") or rec.get("claim")
            or rec.get("title") or rec.get("trigger") or rec.get("why") or ""
        )
        out.append(f"{rec.get('seq', '?'):>4}  {rec.get('ev', '?'):<13} {subject:<28} {detail[:88]}")
    return "\n".join(out)


def _questions_by_id(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.get("ev") == "question":
            found[str(rec["qid"])] = rec
    return found


def _mutations_by_child(records: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for rec in records:
        if rec.get("ev") == "mutation":
            # a mutation event describes the question it produced
            found[str(rec.get("produced") or rec.get("gid"))] = rec
    return found


def why(records: Iterable[Mapping[str, Any]], qid: str) -> dict[str, Any]:
    """Reconstruct the causal chain that produced ``qid``.

    Walks ``revision_of`` links backwards from the question to its root, and for
    each link reports the trigger recorded on the mutation event -- which is the
    ambiguity, knowledge gap, contradiction or disagreement that caused it.
    ``complete`` is False when a link is missing from the ledger, which is worth
    saying out loud rather than papering over.
    """
    rows = [dict(r) for r in records]
    questions = _questions_by_id(rows)
    if qid not in questions:
        return {"qid": qid, "found": False, "chain": [], "complete": False,
                "reason": f"no question event for {qid!r} in this ledger"}

    mutations = _mutations_by_child(rows)
    steps: list[dict[str, Any]] = []
    seen: set[str] = set()
    cursor: str | None = qid
    complete = True
    while cursor is not None:
        if cursor in seen:
            complete = False
            steps.append({"qid": cursor, "note": "cycle detected while walking revision_of"})
            break
        seen.add(cursor)
        record = questions.get(cursor)
        if record is None:
            complete = False
            steps.append({"qid": cursor, "note": "referenced parent question is absent from the ledger"})
            break
        step: dict[str, Any] = {
            "qid": cursor,
            "version": record.get("version"),
            "raw": record.get("raw"),
            "trigger": record.get("trigger") or "",
        }
        mutation = mutations.get(cursor)
        if mutation is not None:
            step["mutation"] = {
                "kind": mutation.get("kind"),
                "trigger": mutation.get("trigger"),
                "derived_from": mutation.get("derived_from"),
                "rationale": mutation.get("rationale"),
            }
        steps.append(step)
        cursor = record.get("revision_of")

    steps.reverse()
    return {
        "qid": qid,
        "found": True,
        "root": steps[0]["qid"] if steps else qid,
        "chain": steps,
        "complete": complete,
    }


def referenced_by(records: Iterable[Mapping[str, Any]], subject: str) -> list[dict[str, Any]]:
    """Every event naming ``subject`` in any of its identity fields."""
    keys = ("qid", "parent", "revision_of", "question", "hid", "xid", "eid", "aid",
            "atid", "vid", "oid", "produced", "derived_from")
    hits: list[dict[str, Any]] = []
    for rec in records:
        if any(str(rec.get(k)) == subject for k in keys):
            hits.append(dict(rec))
    return hits
