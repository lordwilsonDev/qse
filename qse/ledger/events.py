"""Event schemas: one function, one shape per event type.

An event is a small JSON object. Every type declares the fields it must carry,
and ``build`` refuses to produce a record without them, so a malformed event
cannot reach the ledger in the first place. This matters because the ledger is
the only thing replay reads: a field that was never written is a fact that
cannot be recovered afterwards.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..ids import iso, utcnow

EVENT_TYPES = (
    "question",      # a question object exists (root or revised)
    "ambiguity",     # the decomposition found something undefined
    "assumption",    # something had to be true
    "inversion",     # AIL produced an inversion
    "expert",        # one MoIE operator's report
    "hypothesis",    # a competing explanation
    "experiment",    # a falsifiable test
    "evidence",      # a usable or unusable observation
    "artifact",      # something was constructed
    "attack",        # the artifact was attacked
    "verification",  # somebody other than the builder checked
    "mutation",      # the question was rewritten, and why
    "outcome",       # what actually happened
    "decision",      # the controller chose one thing over another
)

#: The fields each event type cannot be replayed without.
REQUIRED: dict[str, tuple[str, ...]] = {
    "question": ("qid", "version", "raw", "slots"),
    "ambiguity": ("aid", "qid", "slot", "term", "kind", "severity", "resolving_question"),
    "assumption": ("aid", "text", "source", "load_bearing"),
    "inversion": ("iid", "operator", "target_axiom", "statement", "consequence"),
    "expert": ("operator", "question", "unique_discoveries", "contradictions", "blind_spots"),
    "hypothesis": ("hid", "text", "question", "mechanism", "locus", "timescale",
                   "measurement_assumption", "authority"),
    "experiment": ("xid", "hypothesis", "question", "design", "refuted_by"),
    "evidence": ("eid", "hypothesis", "claim", "kind", "source", "method"),
    "artifact": ("aid", "hypothesis", "kind", "title", "builder"),
    "attack": ("atid", "artifact", "kind", "severity", "survives"),
    "verification": ("vid", "artifact", "builder", "verifier", "independent", "ok"),
    "mutation": ("gid", "parent", "text", "kind", "trigger"),
    "outcome": ("oid", "artifact", "kind", "real_world"),
    "decision": ("did", "kind", "subject", "chosen", "why"),
}


class EventError(ValueError):
    """An event cannot be formed, so it will not be written."""


def build(event_type: str, **fields: Any) -> dict[str, Any]:
    """Validate and stamp one event. Raises rather than writing a partial record."""
    if event_type not in EVENT_TYPES:
        raise EventError(f"unknown event type {event_type!r}; choose from {EVENT_TYPES}")
    missing = [name for name in REQUIRED[event_type] if name not in fields]
    if missing:
        raise EventError(f"{event_type} event is missing required field(s): {', '.join(missing)}")
    record: dict[str, Any] = {"ev": event_type}
    record.update(fields)
    record.setdefault("ts", iso(utcnow()))
    return check(record)


def check(record: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an already-formed record. Returns it as a plain dict."""
    if not isinstance(record, Mapping):
        raise EventError("an event must be an object")
    event_type = record.get("ev")
    if event_type not in EVENT_TYPES:
        raise EventError(f"unknown event type {event_type!r}")
    missing = [name for name in REQUIRED[event_type] if record.get(name) is None]
    if missing:
        raise EventError(f"{event_type} event is missing required field(s): {', '.join(missing)}")
    out = dict(record)
    out["ev"] = event_type
    return out
