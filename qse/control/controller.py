"""The controller: the loop, and the only place the ledger is written.

Every other module returns objects. This one logs them. That is deliberate --
one writer means one place where the event schema can be got wrong, and replay
has exactly one shape to be right about.

The loop is a feedback controller, not a pipeline:

    ask -> analyze -> revise while blocked -> invert -> convene -> hypothesize
        -> plan -> run -> disagree -> synthesize -> build -> execute -> attack
        -> verify -> outcome -> ask the next question

At every step that could go more than one way the controller logs a ``decision``
event naming what it chose, the alternatives it rejected, and why. That is what
makes the last acceptance test answerable: another process can reconstruct why
the engine asked the questions it asked, because the alternatives it did *not*
ask are in the ledger next to the reason each one lost.

If a blocking slot cannot be answered, the loop does not guess. It stops,
records ``R-QUE-1``, and reports the question it would have asked next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .. import metrics as metrics_mod
from ..build import artifact_graph, generator, specification
from ..build.executor import execute
from ..core.artifact import Artifact
from ..core.assumption import make_assumption
from ..core.evidence import Evidence
from ..core.experiment import Experiment
from ..core.hypothesis import Hypothesis
from ..core.outcome import make_outcome
from ..core.proposition import parse_proposition
from ..core.question import Question, SLOTS
from ..experiment import planner, runner
from ..experiment import results as result_mod
from ..experiment.falsification import audit as falsification_audit
from ..ids import iso, new_id, utcnow
from ..inversion import moie
from ..inversion.ail import AILEngine
from ..ledger import chain, receipts
from ..ledger.events import EventError, build
from ..question_engine import ambiguity as ambiguity_mod
from ..question_engine import decomposer, dependency, question_generator
from ..question_engine.provenance import provenance_summary
from ..reasoning import disagreement as disagreement_mod
from ..reasoning import synthesis
from ..reasoning.hypothesis import from_inversions, register
from ..reasoning.uncertainty import load as uncertainty_load
from ..reasoning.uncertainty import survey as uncertainty_survey
from ..verification import adversary
from ..verification import evidence as verification_evidence
from ..verification import reproducibility
from ..verification.verifier import gate as verification_gate
from .policy import Refusal

DEFAULT_BUILDER = "qse-builder"
DEFAULT_VERIFIER = "qse-verifier"
MAX_REVISIONS = 4


class ContractError(RuntimeError):
    """A slice returned something the controller cannot log. Fail loud, not quietly."""


def columns_of(dataset: Any) -> list[str]:
    """The declared column names of a Dataset, in a stable order."""
    rows = getattr(dataset, "rows", None) or []
    seen: set[str] = set()
    for row in rows:
        if isinstance(row, Mapping):
            seen.update(str(k) for k in row)
    return sorted(seen)


@dataclass
class RunReport:
    """What one pass of the loop produced. Everything here is also in the ledger."""

    question: str
    stages: list[dict[str, Any]] = field(default_factory=list)
    blocked: bool = False
    metrics: dict[str, Any] = field(default_factory=dict)
    next_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "blocked": self.blocked,
            "stages": self.stages,
            "metrics": self.metrics,
            "next_question": self.next_question,
        }


class Engine:
    """One run, one ledger, one writer."""

    def __init__(
        self,
        ledger: str | Path,
        *,
        builder: str = DEFAULT_BUILDER,
        verifier: str = DEFAULT_VERIFIER,
        max_revisions: int = MAX_REVISIONS,
    ) -> None:
        self.ledger = Path(ledger)
        self.builder = builder
        self.verifier = verifier
        self.max_revisions = max_revisions

    # ------------------------------------------------------------------ #
    # Ledger
    # ------------------------------------------------------------------ #

    def log(self, event_type: str, **fields: Any) -> dict[str, Any]:
        return chain.append(self.ledger, build(event_type, **fields))

    def decide(self, kind: str, *, subject: str, chosen: str, why: str, **extra: Any) -> dict[str, Any]:
        return self.log(
            "decision",
            did=new_id("DEC", kind, subject, chosen),
            kind=kind,
            subject=subject,
            chosen=chosen,
            why=why,
            **extra,
        )

    def records(self) -> list[dict[str, Any]]:
        return chain.load(self.ledger)

    def state(self) -> Any:
        from .state import State

        return State.replay(self.records())

    def why(self, qid: str) -> dict[str, Any]:
        rows = self.records()
        out = receipts.why(rows, qid)
        out["decisions"] = [d for d in receipts.referenced_by(rows, qid) if d.get("ev") == "decision"]
        return out

    def metrics(self) -> dict[str, Any]:
        return metrics_mod.scorecard(self.state())

    # ------------------------------------------------------------------ #
    # 1-2. The question and its model
    # ------------------------------------------------------------------ #

    def ask(
        self,
        raw: str,
        *,
        qid: str | None = None,
        answers: Mapping[str, str] | None = None,
        trigger: str = "",
        parent: str | None = None,
        revision_of: str | None = None,
        revision_reason: str = "",
    ) -> Question:
        question = decomposer.decompose(
            raw, qid=qid, answers=answers, trigger=trigger,
            parent=parent, revision_of=revision_of, revision_reason=revision_reason,
        )
        self.log("question", **question.to_dict())
        return question

    def analyze(self, question: Question) -> dict[str, Any]:
        proposition = parse_proposition(question.value("proposition") or question.raw)
        # as_asked=True: report the question as it was put. An operator answer
        # marks a finding `closed` rather than deleting it, so the ledger keeps the
        # defect and the repair side by side and BSR has a `before` to subtract from.
        found = ambiguity_mod.detect(question, proposition=proposition, as_asked=True)
        for item in found:
            self.log("ambiguity", **item.to_dict())
        return {
            "qid": question.qid,
            "seven_slots": decomposer.seven_slot_report(question),
            "proposition": proposition.to_dict(),
            "ambiguities": found,
            "open_ambiguities": [a for a in found if not a.closed],
            "closed_ambiguities": [a for a in found if a.closed],
            "blocking": question.blocking(),
            "blocked_by": dependency.blocked_by(question),
            "provenance": provenance_summary(question),
        }

    # ------------------------------------------------------------------ #
    # 10. Recursive question mutation
    # ------------------------------------------------------------------ #

    def revise(
        self,
        question: Question,
        *,
        ambiguities: Sequence[Any] = (),
        hypotheses: Sequence[Hypothesis] = (),
        experiments: Sequence[Experiment] = (),
        disagreements: Sequence[Any] = (),
    ) -> dict[str, Any]:
        """Ask what the next question should be, log the choice *and the losers*.

        Returns ``{"chosen", "ranked", "mutation", "child"}``. The child question
        is written to the ledger but not answered here -- answering it is the
        operator's or the scenario's job, and pretending otherwise is how a
        system starts inventing its own evidence.
        """
        candidates = question_generator.next_questions(
            question,
            ambiguities=ambiguities,
            experiments=experiments,
            disagreements=disagreements,
            hypotheses=hypotheses,
        )
        if not candidates:
            return {"chosen": None, "ranked": [], "mutation": None, "child": None}
        ranked = feedback_rank(candidates, self.state())
        chosen_gid = ranked["next"]
        chosen = next((c for c in candidates if c.gid == chosen_gid), None)
        if chosen is None:
            return {"chosen": None, "ranked": ranked["ranked"], "mutation": None, "child": None}

        losers = ", ".join(
            f"{row['text'][:48]} ({row['gain']:.2f})" for row in ranked["ranked"][1:4]
        ) or "no other candidate"
        mutation = self.log(
            "mutation",
            gid=chosen.gid,
            parent=question.qid,
            text=chosen.text,
            kind=chosen.kind,
            trigger=chosen.trigger,
            derived_from=chosen.derived_from,
            produced=None,
            rationale=chosen.rationale,
        )
        self.decide(
            "QUESTION_MUTATION",
            subject=question.qid,
            chosen=chosen.text,
            why=(
                f"highest information gain {ranked['ranked'][0]['gain']:.2f} of "
                f"{len(candidates)} candidate question(s); rejected: {losers}"
            ),
            alternatives=[row["text"] for row in ranked["ranked"][1:]],
            gain_basis="ordinal estimate, not a calibrated probability",
        )
        return {"chosen": chosen, "ranked": ranked["ranked"], "mutation": mutation, "child": None}

    # ------------------------------------------------------------------ #
    # 3-4. AIL and MoIE
    # ------------------------------------------------------------------ #

    def invert(self, question: Question) -> dict[str, Any]:
        proposition = parse_proposition(question.value("proposition") or question.raw)
        engine = AILEngine(question, proposition=proposition)
        axioms = engine.axioms()
        accepted = engine.invert()
        rejected = engine.rejected()
        # An axiom is exactly the thing the question has to believe for its own
        # answer to be possible, so it is recorded as an assumption -- load-bearing
        # when the axiom is one the whole investigation rests on.
        load_bearing_kinds = {"MEASUREMENT", "CAUSAL", "FAILURE"}
        for axiom in axioms:
            reason = str(axiom.because or "").strip()
            # Routed through the type rather than logged as a loose dict, so the
            # rule that a load-bearing assumption needs a testable consequence is
            # actually applied. An axiom with no reason recorded is a note, not a
            # load-bearing assumption.
            item = make_assumption(
                axiom.text,
                source=f"inversion.axiom.extract [{axiom.kind}] {reason or 'no reason recorded'}",
                load_bearing=axiom.kind in load_bearing_kinds and bool(reason),
                testable_consequence=reason or None,
            )
            self.log("assumption", **item.to_dict())
        for inversion in accepted:
            self.log("inversion", **inversion.to_dict())
        for row in rejected:
            self.decide(
                "REFUSED_INVERSION",
                subject=str(row.get("statement", ""))[:120],
                chosen="reject",
                why=f"{row.get('rule', 'R-INV-1')}: {row.get('reason', '')}",
            )
        reports = moie.convene(question, engine)
        for report in reports:
            self.log("expert", **report.to_dict())
        measured = moie.measure(reports)
        # Preserving the disagreement is a decision, so it is recorded as one. The
        # alternative -- letting the experts' positions quietly average out -- is
        # exactly what R-SYN-1 forbids, and a ledger that never says disagreement
        # was found cannot show that it was kept.
        contested = list(measured.get("disagreement") or [])
        contradicted = list(measured.get("contradictions") or [])
        if contested or contradicted:
            self.decide(
                "EXPERT_DISAGREEMENT",
                subject=question.qid,
                chosen="preserve",
                why=(
                    f"{len(contested)} pairwise expert disagreement(s) and {len(contradicted)} "
                    "contradiction(s) kept open; nothing is averaged or outvoted"
                ),
                disagreements=contested[:8],
                contradictions=contradicted[:8],
            )
        return {"ail": engine, "axioms": axioms, "accepted": accepted, "rejected": rejected,
                "experts": reports, "measured": measured}

    # ------------------------------------------------------------------ #
    # 5. Competing hypotheses
    # ------------------------------------------------------------------ #

    def hypothesize(
        self,
        question: Question,
        inversions: Sequence[Any],
        *,
        authority: str | None = None,
        measurement_assumption: str | None = None,
    ) -> list[Hypothesis]:
        kwargs: dict[str, Any] = {"authority": authority or question.value("authority") or "unnamed"}
        if measurement_assumption:
            kwargs["measurement_assumption"] = measurement_assumption
        candidates = from_inversions(inversions, question, **kwargs)
        kept: list[Hypothesis] = []
        for candidate in candidates:
            try:
                kept = register(kept, candidate)
            except Refusal as refusal:
                self.decide(
                    "REFUSED_HYPOTHESIS",
                    subject=candidate.hid,
                    chosen="reject",
                    why=f"{refusal.rule}: {refusal.message}",
                )
                continue
        for hypothesis in kept:
            self.log("hypothesis", **hypothesis.to_dict())
        return kept

    # ------------------------------------------------------------------ #
    # 6-7. Experiments and evidence
    # ------------------------------------------------------------------ #

    def plan(
        self,
        question: Question,
        hypotheses: Sequence[Hypothesis],
        *,
        columns: Sequence[str] = (),
    ) -> dict[str, Any]:
        if not hypotheses:
            return {"experiments": [], "audit": {"n": 0}, "coverage": {}, "best": None}
        per_hypothesis = planner.propose(hypotheses, question=question.qid, columns=columns)
        wide = planner.discriminating(hypotheses, question=question.qid, columns=columns)
        everything = list(per_hypothesis) + list(wide)
        for experiment in everything:
            self.log("experiment", **experiment.to_dict())
        return {
            "experiments": everything,
            "audit": falsification_audit(everything),
            "coverage": planner.coverage(everything, hypotheses=hypotheses),
            "best": planner.best_to_run(everything),
        }

    def run_experiments(self, experiments: Iterable[Experiment], datasets: Any) -> dict[str, Any]:
        """Run the experiments against every source supplied.

        More than one source is the point. A rule that claims to apply more than
        once has to show it holds somewhere other than where it was found, and the
        adversary's scope attack says so -- so a single dataset can never clear it.
        One Evidence record is produced per (experiment, source) pair, each with its
        own provenance.
        """
        if isinstance(datasets, (list, tuple)):
            frames = list(datasets)
        else:
            frames = [datasets]
        results: list[dict[str, Any]] = []
        produced: list[Evidence] = []
        for experiment in experiments:
            for frame in frames:
                outcome = runner.run(experiment, frame)
                verdict = result_mod.verdict(experiment, outcome)
                source = getattr(frame, "name", "dataset")
                results.append({
                    "xid": experiment.xid,
                    "runner": outcome.get("runner"),
                    "verdict": verdict,
                    "ran": outcome.get("ran"),
                    "reason": outcome.get("reason", ""),
                    "observed": outcome.get("observed"),
                    # the adversary reads these two at the top level, so a result
                    # that only carried them inside `observed` looked like a run
                    # that supported nothing
                    "supported": outcome.get("supported"),
                    "refuted": outcome.get("refuted"),
                    "source": source,
                    # the adversary needs these to judge whether any run separates
                    # this explanation from its competitors
                    "hypothesis": experiment.hypothesis,
                    "discriminates": list(experiment.discriminates),
                })
                if not outcome.get("ran"):
                    self.decide(
                        "EXPERIMENT_NOT_RUN",
                        subject=f"{experiment.xid}@{source}",
                        chosen="record-not-run",
                        why=str(outcome.get("reason", "runner did not run")),
                    )
                    continue
                updated = result_mod.update(experiment, outcome)
                self.log("experiment", **updated.to_dict())
                try:
                    evidence = result_mod.to_evidence(
                        experiment, outcome,
                        collected_at=iso(utcnow()),
                        source=source,
                    )
                except ValueError as exc:
                    self.decide("EVIDENCE_REFUSED", subject=experiment.xid,
                                chosen="record-nothing", why=str(exc))
                    continue
                self.log("evidence", **evidence.to_dict())
                produced.append(evidence)
        return {"results": results, "evidence": produced}

    # ------------------------------------------------------------------ #
    # 8-10. Build, attack, verify
    # ------------------------------------------------------------------ #

    def build(
        self,
        hypothesis: Hypothesis,
        evidence: Sequence[Evidence],
        *,
        artifact_kind: str = "DECISION_RULE",
        builder: str | None = None,
        columns: Sequence[str] = (),
    ) -> dict[str, Any]:
        spec = specification.from_hypothesis(
            hypothesis, list(evidence), artifact_kind=artifact_kind, columns=columns,
        )
        rule = generator.default_rule(spec, list(evidence))
        artifact = generator.generate(spec, builder=builder or self.builder, rule=rule)
        self.log("artifact", **artifact.to_dict())
        return {"spec": spec, "rule": rule, "artifact": artifact}

    def attack(
        self,
        artifact: Artifact,
        *,
        hypothesis: Hypothesis,
        evidence_for: Sequence[Evidence] = (),
        evidence_against: Sequence[Evidence] = (),
        results: Sequence[Mapping[str, Any]] = (),
        reproductions: Sequence[Any] = (),
    ) -> list[Any]:
        attacks = adversary.attack(
            artifact,
            hypothesis=hypothesis,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
            results=results,
            reproductions=reproductions,
        )
        for item in attacks:
            self.log("attack", **item.to_dict())
        return attacks

    def reproduce(self, artifact: Artifact, *, rows: Sequence[Mapping[str, Any]] | None = None) -> Any:
        """Run the artifact twice and require identical output from identical source.

        The first run establishes both hashes; the second has to match on *both*.
        Matching only the source would prove the bytes did not change, which is a
        much weaker claim than "it reproduces".
        """

        def run(target: Artifact) -> dict[str, Any]:
            return execute(target, rows=list(rows or []))

        first = reproducibility.check(artifact, execute=run)
        if not first.ran:
            self.decide("REPRODUCTION_FAILED", subject=artifact.aid, chosen="did-not-run",
                        why=first.detail)
            return first
        second = reproducibility.check(
            artifact,
            execute=run,
            expected_hash=reproducibility.content_hash(artifact),
            expected_output_hash=first.observed_hash,
        )
        self.decide(
            "REPRODUCED" if (second.ran and second.ok) else "REPRODUCTION_FAILED",
            subject=artifact.aid,
            chosen=second.observed_hash or "-",
            why=second.detail,
            ran=second.ran,
            ok=second.ok,
            observed_hash=second.observed_hash,
            expected_hash=second.expected_hash,
        )
        return second

    def verify(
        self,
        artifact: Artifact,
        *,
        attacks: Sequence[Any],
        reproductions: Sequence[Any],
        evidence_for: Sequence[Evidence],
        evidence_against: Sequence[Evidence] = (),
        verifier: str | None = None,
    ) -> dict[str, Any]:
        outcome = verification_gate(
            artifact,
            verifier=verifier or self.verifier,
            attacks=attacks,
            reproductions=reproductions,
            evidence_for=evidence_for,
            evidence_against=evidence_against,
        )
        verification = outcome.get("verification")
        if verification is not None:
            self.log("verification", **verification.to_dict())
        else:
            self.decide(
                "VERIFICATION_REFUSED",
                subject=artifact.aid,
                chosen=outcome.get("state_after", "REJECTED"),
                why="; ".join(outcome.get("refusals") or []) or "; ".join(outcome.get("reasons") or []),
            )
        return outcome

    def record_outcome(
        self,
        artifact: Artifact,
        *,
        evidence: Sequence[Evidence],
        kind: str = "MEASURED_CHANGE",
        before: Any = None,
        after: Any = None,
        real_world: bool = False,
        notes: str = "",
    ) -> Any:
        outcome = make_outcome(
            artifact=artifact.aid, kind=kind, evidence=tuple(e.eid for e in evidence),
            before=before, after=after, real_world=real_world, notes=notes,
        )
        self.log("outcome", **outcome.to_dict())
        return outcome

    # ------------------------------------------------------------------ #
    # The loop
    # ------------------------------------------------------------------ #

    def run(
        self,
        raw: str,
        *,
        answers: Mapping[str, str] | None = None,
        dataset: Any = None,
        datasets: Sequence[Any] = (),
        rows: Sequence[Mapping[str, Any]] | None = None,
        authority: str | None = None,
        measurement_assumption: str | None = None,
        artifact_kind: str = "DECISION_RULE",
        real_world: bool = False,
        before: Any = None,
        after: Any = None,
        columns: Sequence[str] = (),
    ) -> RunReport:
        supplied = {k: v for k, v in dict(answers or {}).items() if v}
        report = RunReport(question=raw)
        # Operator answers are STATED facts about the question, so they belong at
        # decomposition. Applying them later, one blocking slot per revision, meant
        # a brief that answered `authority` never reached the hypotheses unless
        # `authority` happened to be the slot the engine chose to ask about -- and
        # then the artifact was rejected for having no authority it had in fact
        # been given.
        question = self.ask(raw, answers=supplied)
        frames = list(datasets) or ([dataset] if dataset is not None else [])
        columns = tuple(columns) or tuple(columns_of(frames[0] if frames else None))

        # -- the question model, revised until it is answerable ---------- #
        for revision in range(self.max_revisions + 1):
            analysis = self.analyze(question)
            blocking_slots = question.blocking()
            blocking_ambiguities = [a for a in analysis["open_ambiguities"]
                                    if a.severity == "BLOCKING"]
            report.stages.append({
                "stage": f"analyze (v{question.version})",
                "filled": sorted(question.filled()),
                "unresolved": question.unresolved(),
                "blocking": blocking_slots,
                "ambiguities": len(analysis["ambiguities"]),
                "closed_by_brief": len(analysis["closed_ambiguities"]),
                "blocking_ambiguities": len(blocking_ambiguities),
            })
            if not blocking_slots and not blocking_ambiguities:
                break
            # ask only about ambiguities the brief did *not* already settle: a
            # question the operator has answered is not a question to put again
            revision_result = self.revise(question, ambiguities=analysis["open_ambiguities"])
            chosen = revision_result["chosen"]
            if chosen is None:
                break
            report.stages.append({
                "stage": f"revise (v{question.version})",
                "asked": chosen.text,
                "kind": chosen.kind,
                "trigger": chosen.trigger,
                "slot": chosen.slot_targeted,
            })
            if blocking_slots:
                # a blocking slot nobody supplied. Guessing it is exactly what
                # R-QUE-1 forbids, so the loop stops and names the question.
                report.blocked = True
                self.decide(
                    "BLOCKED",
                    subject=question.qid,
                    chosen=chosen.text,
                    why=(f"R-QUE-1: blocking slot(s) {', '.join(blocking_slots)} unresolved; "
                         f"the next question to ask is '{chosen.text}' and nothing may be consumed "
                         f"until it is answered"),
                )
                report.stages.append({"stage": "blocked",
                                      "slot": chosen.slot_targeted,
                                      "next_question": chosen.text})
                report.next_question = chosen.text
                report.metrics = self.metrics()
                return report
            # Every slot the brief covers is answered. The engine asked, the answer
            # was not in what it was given, and it continues with the ambiguity
            # recorded as still open rather than inventing one -- so it stays counted
            # in BSR instead of being quietly dropped.
            self.decide(
                "PROCEED_WITH_AMBIGUITY",
                subject=question.qid,
                chosen=chosen.text,
                why=(f"no supplied answer settles this ambiguity: {chosen.trigger}. The "
                     f"investigation proceeds with it open and it remains counted in BSR"),
            )
            report.stages.append({"stage": "ambiguity-open",
                                  "asked": chosen.text,
                                  "kind": chosen.kind,
                                  "slot": chosen.slot_targeted})
            break

        # -- inversion and competing explanations ------------------------ #
        inverted = self.invert(question)
        report.stages.append({
            "stage": "invert",
            "axioms": len(inverted["ail"].axioms()),
            "inversions": len(inverted["accepted"]),
            "refused": len(inverted["rejected"]),
            "experts": len(inverted["experts"]),
            "disagreements_between_experts": len(inverted["measured"].get("disagreement", [])),
        })

        hypotheses = self.hypothesize(
            question,
            inverted["accepted"],
            authority=authority,
            measurement_assumption=measurement_assumption,
        )
        report.stages.append({
            "stage": "hypothesize",
            "hypotheses": len(hypotheses),
            "structures": sorted({h.signature() for h in hypotheses}),
        })
        if not hypotheses:
            report.blocked = True
            report.metrics = self.metrics()
            return report

        # -- experiments and evidence ------------------------------------ #
        planned = self.plan(question, hypotheses, columns=columns)
        report.stages.append({
            "stage": "plan",
            "experiments": len(planned["experiments"]),
            "unfalsifiable": planned["audit"].get("unfalsifiable", []),
            "weak": sorted(planned["audit"].get("weak", {})),
        })

        evidence: list[Evidence] = []
        experiment_results: list[dict[str, Any]] = []
        if frames:
            ran = self.run_experiments(planned["experiments"], frames)
            evidence = ran["evidence"]
            experiment_results = ran["results"]
            report.stages.append({
                "stage": "run",
                "experiments": len(planned["experiments"]),
                "sources": [getattr(f, "name", "dataset") for f in frames],
                "ran": sum(1 for r in ran["results"] if r.get("ran")),
                "not_run": sum(1 for r in ran["results"] if not r.get("ran")),
                "evidence": len(evidence),
            })

        found = disagreement_mod.find(hypotheses, evidence)
        for item in found:
            self.log("decision", did=new_id("DEC", "DISAGREEMENT", item.did), kind="DISAGREEMENT",
                     subject=item.topic, chosen=item.topic,
                     why="; ".join(p.get("basis", "") for p in item.positions))
        report.stages.append({"stage": "disagree", "disagreements": len(found)})

        # Missing evidence, named rather than implied. A hypothesis the run cannot
        # decide is a knowledge gap, and the gap is what the next question is for.
        gaps = verification_evidence.unsupported(hypotheses, evidence)
        for hid in gaps:
            self.decide(
                "KNOWLEDGE_GAP",
                subject=hid,
                chosen="insufficient-evidence",
                why="no usable evidence reaching the bar supports this explanation, so it stays open",
            )
        survey = uncertainty_survey(question, hypotheses=hypotheses, evidence=evidence, gaps=gaps)
        if survey:
            loaded = uncertainty_load(survey)
            self.decide(
                "UNCERTAINTY",
                subject=question.qid,
                chosen=f"{loaded['n']} named uncertainties (ordinal {loaded['ordinal']})",
                why="; ".join(sorted({u.kind for u in survey})),
                by_kind=loaded["by_kind"],
            )
        report.stages.append({"stage": "gaps", "unsupported": gaps, "uncertainties": len(survey)})

        # -- synthesis: evidence, never a head-count ---------------------- #
        choice = synthesis.select(hypotheses, evidence)
        self.decide(
            "SYNTHESIS",
            subject=question.qid,
            chosen=str(choice.get("winner")),
            why=str(choice.get("why", "")),
            minority_wins=bool(choice.get("minority_wins")),
            table=choice.get("table", []),
        )
        report.stages.append({
            "stage": "synthesize",
            "winner": choice.get("winner"),
            "runner_up": choice.get("runner_up"),
            "minority_wins": choice.get("minority_wins"),
            "why": choice.get("why"),
        })

        winner = next((h for h in hypotheses if h.hid == choice.get("winner")), None)
        if winner is None:
            report.stages.append({"stage": "stop", "reason": "no hypothesis cleared the evidence bar"})
            report.metrics = self.metrics()
            report.next_question = self._ask_next(question, [], planned["experiments"], found, report)
            return report

        for_support = [e for e in evidence if e.hypothesis == winner.hid and e.supports]
        against = [e for e in evidence if e.hypothesis == winner.hid and not e.supports]

        # -- build -------------------------------------------------------- #
        built = self.build(winner, evidence, artifact_kind=artifact_kind, columns=tuple(columns))
        artifact: Artifact = built["artifact"]
        report.stages.append({
            "stage": "build",
            "artifact": artifact.aid,
            "kind": artifact.kind,
            "title": artifact.title,
            "rule": built["rule"],
        })

        rows_used = list(
            rows if rows is not None
            else (getattr(frames[0], "rows", None) if frames else None) or []
        )
        executed = execute(artifact, rows=rows_used)
        report.stages.append({
            "stage": "execute",
            "ran": executed.get("ran"),
            "ok": executed.get("ok"),
            "flagged": (executed.get("observed") or {}).get("flagged"),
            "reason": executed.get("reason", ""),
        })

        # -- attack ------------------------------------------------------- #
        reproduction = self.reproduce(artifact, rows=rows_used)
        attacks = self.attack(
            artifact,
            hypothesis=winner,
            evidence_for=for_support,
            evidence_against=against,
            results=experiment_results,
            reproductions=[reproduction],
        )
        report.stages.append({
            "stage": "attack",
            "attacks": len(attacks),
            "landed": [a.kind for a in adversary.landed(attacks)],
            "verdict": adversary.verdict(attacks),
        })

        # The gate reads the artifact's own attack list, so the attacks have to be
        # attached to it before verification, and the artifact re-logged so replay
        # sees the same thing the gate saw.
        artifact.attacks = [item.atid for item in attacks]
        artifact.state = "ATTACKED"
        self.log("artifact", **artifact.to_dict())

        # -- verify ------------------------------------------------------- #
        outcome = self.verify(
            artifact, attacks=attacks, reproductions=[reproduction],
            evidence_for=for_support, evidence_against=against,
        )
        report.stages.append({
            "stage": "verify",
            "ok": outcome.get("ok"),
            "refusals": outcome.get("refusals"),
            "reasons": outcome.get("reasons"),
            "state_after": outcome.get("state_after"),
        })

        verification = outcome.get("verification")
        if outcome.get("ok"):
            artifact.verifications = [verification.vid] if verification is not None else []
            artifact.state = "VERIFIED"
        else:
            artifact.state = "REJECTED"
        self.log("artifact", **artifact.to_dict())

        if outcome.get("ok"):
            self.record_outcome(
                artifact, evidence=for_support,
                kind="MEASURED_CHANGE" if real_world else "ARTIFACT_DEPLOYED",
                before=before, after=after, real_world=real_world,
                notes="verified artifact; outcome recorded from the run's own evidence",
            )
            report.stages.append({"stage": "outcome", "recorded": True, "real_world": real_world})

        # -- and the next question ---------------------------------------- #
        report.next_question = self._ask_next(question, hypotheses, planned["experiments"], found, report)
        report.metrics = self.metrics()
        return report

    def _ask_next(
        self,
        question: Question,
        hypotheses: Sequence[Hypothesis],
        experiments: Sequence[Experiment],
        disagreements: Sequence[Any],
        report: RunReport,
    ) -> str | None:
        """Close the loop: ask what to ask next, and record that it was asked."""
        revision = self.revise(
            question, hypotheses=hypotheses, experiments=experiments, disagreements=disagreements
        )
        chosen = revision["chosen"]
        if chosen is None:
            return None
        self.log(
            "question",
            qid=new_id("Q", chosen.text, "next"),
            version=1,
            raw=chosen.text,
            slots={name: None for name in SLOTS},
            parent=question.qid,
            revision_of=question.qid,
            revision_reason=chosen.rationale,
            trigger=chosen.trigger,
        )
        report.stages.append({
            "stage": "question-revision",
            "next": chosen.text,
            "kind": chosen.kind,
            "trigger": chosen.trigger,
        })
        return chosen.text


def feedback_rank(candidates: Sequence[Any], state: Any) -> dict[str, Any]:
    """The control layer's ranking. Kept as a module function so a test can call it
    with a hand-built state instead of having to run the whole loop."""
    from . import feedback

    return feedback.gain_report(candidates, state)


__all__ = ["Engine", "RunReport", "ContractError", "DEFAULT_BUILDER", "DEFAULT_VERIFIER",
           "MAX_REVISIONS", "columns_of", "feedback_rank"]
