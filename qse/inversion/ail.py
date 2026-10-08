"""AIL — the Axiomatic Inversion Logic engine.

The engine has exactly three jobs, and the third is the one that makes it
trustworthy:

1. extract the axioms a question rests on;
2. run all seven operators over all of them;
3. push every candidate through ``policy.require_testable_consequence`` and
   **report what it refused**.

Job three is why ``rejected()`` exists as a public method. An engine that drops
an unconsequenced inversion silently is indistinguishable from an engine that
never produced one, and the second is a claim nobody can check.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..control.policy import Refusal, require_testable_consequence
from ..core.proposition import Proposition, parse_proposition
from ..core.question import Question
from .axiom import Axiom, extract
from .operators import OPERATORS, OPERATOR_FUNCTIONS, Inversion


@dataclass
class AILReport:
    question: str
    proposition: str
    axioms: list[Axiom]
    inversions: list[Inversion]
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "proposition": self.proposition,
            "axioms": [a.to_dict() for a in self.axioms],
            "inversions": [i.to_dict() for i in self.inversions],
            "rejected": list(self.rejected),
            "counts": {
                "axioms": len(self.axioms),
                "accepted": len(self.inversions),
                "rejected": len(self.rejected),
                "operators": len({i.operator for i in self.inversions}),
                "kinds": len({i.kind for i in self.inversions}),
            },
        }


class AILEngine:
    """Invert one question's axioms.

    Deterministic: the run order is ``OPERATORS`` x axioms, so the same question
    produces the same inversions with the same ids on every run.
    """

    def __init__(self, question: Question, *, proposition: Proposition | None = None) -> None:
        self.question = question
        if proposition is not None:
            self.proposition = proposition
            self.proposition_source = "supplied"
        else:
            slot = question.value("proposition")
            if slot and slot.strip():
                self.proposition = parse_proposition(slot)
                self.proposition_source = "proposition slot"
            else:
                self.proposition = parse_proposition(question.raw)
                self.proposition_source = "raw text (the proposition slot is unresolved)"
        self._axioms: list[Axiom] | None = None
        self._candidates: list[Inversion] | None = None
        self._accepted: list[Inversion] | None = None
        self._rejected: list[dict[str, Any]] | None = None

    # -- stages ----------------------------------------------------------
    def axioms(self) -> list[Axiom]:
        if self._axioms is None:
            self._axioms = extract(self.question, proposition=self.proposition)
        return list(self._axioms)

    def candidates(self) -> list[Inversion]:
        """Every inversion the operators produce, before the gate."""
        if self._candidates is None:
            found: list[Inversion] = []
            for name in OPERATORS:
                for axiom in self.axioms():
                    found.extend(
                        OPERATOR_FUNCTIONS[name](axiom, self.question, proposition=self.proposition)
                    )
            self._candidates = found
        return list(self._candidates)

    def _gate(self) -> tuple[list[Inversion], list[dict[str, Any]]]:
        if self._accepted is None or self._rejected is None:
            accepted: list[Inversion] = []
            refused: list[dict[str, Any]] = []
            for inversion in self.candidates():
                try:
                    require_testable_consequence(inversion)
                except Refusal as exc:
                    refused.append(
                        {
                            "statement": inversion.statement,
                            "operator": inversion.operator,
                            "kind": inversion.kind,
                            "rule": exc.rule,
                            "reason": exc.message,
                        }
                    )
                    continue
                accepted.append(inversion)
            self._accepted, self._rejected = accepted, refused
        return list(self._accepted), list(self._rejected)

    def invert(self) -> list[Inversion]:
        """The gate-passing inversions, in production order."""
        return self._gate()[0]

    def rejected(self) -> list[dict[str, Any]]:
        """Candidates refused by the gate, with the rule that refused them."""
        return self._gate()[1]

    def report(self) -> AILReport:
        return AILReport(
            question=self.question.qid,
            proposition=f"{self.proposition.text} [{self.proposition.modality}; from {self.proposition_source}]",
            axioms=self.axioms(),
            inversions=self.invert(),
            rejected=self.rejected(),
        )
