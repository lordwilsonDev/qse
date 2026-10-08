"""Replayable state: the whole run, rebuilt from the ledger alone.

This is the auditability core. Every other module may hold live objects while it
works, but ``State.replay(records)`` must produce the same picture from nothing
but the stored events. That is the difference between an engine with intelligence
and an engine with intelligence *and* auditability.

Three deliberate choices:

* An unknown event type is recorded and counted, never raised on. A reader that
  crashes on a future event type cannot read its own past.
* A record that cannot be rebuilt is kept in ``errors`` with the reason, rather
  than being dropped. A record silently skipped is a fact lost.
* Nothing here mutates the records it is given.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from ..core.question import Question

__all__ = ["State"]


@dataclass
class State:
    """Everything the ledger knows, keyed by id."""

    questions: dict[str, Question] = field(default_factory=dict)
    ambiguities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    assumptions: dict[str, dict[str, Any]] = field(default_factory=dict)
    inversions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    experts: dict[str, dict[str, Any]] = field(default_factory=dict)
    hypotheses: dict[str, dict[str, Any]] = field(default_factory=dict)
    experiments: dict[str, dict[str, Any]] = field(default_factory=dict)
    evidence: dict[str, dict[str, Any]] = field(default_factory=dict)
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    attacks: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    verifications: dict[str, dict[str, Any]] = field(default_factory=dict)
    outcomes: dict[str, dict[str, Any]] = field(default_factory=dict)
    mutations: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)
    #: qid -> the ledger sequence number of its most recent version
    seen: dict[str, int] = field(default_factory=dict)
    unknown: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    # -- construction ----------------------------------------------------
    @classmethod
    def empty(cls) -> "State":
        return cls()

    @classmethod
    def replay(cls, records: Iterable[Mapping[str, Any]]) -> "State":
        """Fold a ledger into state. The ledger is the only input."""
        state = cls.empty()
        for index, raw in enumerate(records, 1):
            if not isinstance(raw, Mapping):
                state.unknown += 1
                continue
            rec = dict(raw)  # never touch the caller's record
            state.records.append(rec)
            kind = rec.get("ev")
            seq = rec.get("seq", index)
            try:
                state._fold(kind, rec, seq)
            except (ValueError, KeyError, TypeError) as exc:
                state.errors.append({"seq": seq, "ev": kind, "error": f"{type(exc).__name__}: {exc}"})
        return state

    def _fold(self, kind: Any, rec: dict[str, Any], seq: Any) -> None:
        if kind == "question":
            qid = str(rec["qid"])
            self.questions[qid] = Question.from_dict(rec)
            self.seen[qid] = seq if isinstance(seq, int) else len(self.records)
        elif kind == "ambiguity":
            self.ambiguities.setdefault(str(rec["qid"]), []).append(rec)
        elif kind == "assumption":
            self.assumptions[str(rec["aid"])] = rec
        elif kind == "inversion":
            key = str(rec.get("question") or rec.get("qid") or "unattached")
            self.inversions.setdefault(key, []).append(rec)
        elif kind == "expert":
            self.experts[str(rec["operator"])] = rec
        elif kind == "hypothesis":
            self.hypotheses[str(rec["hid"])] = rec
        elif kind == "experiment":
            self.experiments[str(rec["xid"])] = rec
        elif kind == "evidence":
            self.evidence[str(rec["eid"])] = rec
        elif kind == "artifact":
            self.artifacts[str(rec["aid"])] = rec
        elif kind == "attack":
            self.attacks.setdefault(str(rec["artifact"]), []).append(rec)
        elif kind == "verification":
            self.verifications[str(rec["vid"])] = rec
        elif kind == "outcome":
            self.outcomes[str(rec["oid"])] = rec
        elif kind == "mutation":
            self.mutations.append(rec)
        elif kind == "decision":
            self.decisions.append(rec)
        else:
            # A future event type, or a record with no `ev`. Counted, never fatal.
            self.unknown += 1

    # -- reading ---------------------------------------------------------
    def latest_question(self) -> Question | None:
        """The question whose most recent version appears last in the ledger."""
        if not self.seen:
            return None
        qid = max(self.seen, key=lambda k: self.seen[k])
        return self.questions.get(qid)

    def question_chain(self, qid: str) -> list[str]:
        """qids from the root question down to ``qid``, following ``revision_of``.

        Cycle-safe: a ledger that claims a question descends from itself stops
        rather than looping. A missing parent ends the walk too, and the partial
        chain is returned rather than raising -- the caller can see how far the
        ledger actually reaches.
        """
        chain: list[str] = []
        seen: set[str] = set()
        cursor: str | None = qid
        while cursor and cursor not in seen:
            seen.add(cursor)
            question = self.questions.get(cursor)
            chain.append(cursor)
            cursor = question.revision_of if question is not None else None
        chain.reverse()
        return chain

    def root_questions(self) -> list[dict[str, Any]]:
        """Questions with no ``revision_of``: the ones the engine was actually asked."""
        return [q.to_dict() for q in self.questions.values() if not q.revision_of]

    def open_hypotheses(self) -> list[dict[str, Any]]:
        return [h for h in self.hypotheses.values() if str(h.get("status", "OPEN")) == "OPEN"]

    def verified_artifacts(self) -> list[dict[str, Any]]:
        return [a for a in self.artifacts.values() if str(a.get("state")) == "VERIFIED"]

    def unresolved_slots(self) -> dict[str, list[str]]:
        """qid -> the slots still unfilled in that question's latest version."""
        return {qid: q.unresolved() for qid, q in self.questions.items() if q.unresolved()}

    # The dict buckets are indexes, not the record of truth: every event is also
    # in ``records``. These flatteners are how a caller reads a whole category
    # without caring how it was bucketed.
    def all_inversions(self) -> list[dict[str, Any]]:
        return [rec for bucket in self.inversions.values() for rec in bucket]

    def all_ambiguities(self) -> list[dict[str, Any]]:
        return [rec for bucket in self.ambiguities.values() for rec in bucket]

    def all_attacks(self) -> list[dict[str, Any]]:
        return [rec for bucket in self.attacks.values() for rec in bucket]

    def summary(self) -> dict[str, Any]:
        return {
            "questions": len(self.questions),
            "ambiguities": sum(len(v) for v in self.ambiguities.values()),
            "assumptions": len(self.assumptions),
            "inversions": sum(len(v) for v in self.inversions.values()),
            "experts": len(self.experts),
            "hypotheses": len(self.hypotheses),
            "experiments": len(self.experiments),
            "evidence": len(self.evidence),
            "artifacts": len(self.artifacts),
            "attacks": sum(len(v) for v in self.attacks.values()),
            "verifications": len(self.verifications),
            "outcomes": len(self.outcomes),
            "mutations": len(self.mutations),
            "decisions": len(self.decisions),
            "events": len(self.records),
            "unknown_events": self.unknown,
            "errors": len(self.errors),
        }
