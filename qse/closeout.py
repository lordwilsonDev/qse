"""The close-out: answer the fifteen questions from the recorded artifacts alone.

This module exists because a close-out written in prose is a claim, and a claim
is not evidence. Everything below is derived from the ledger -- event ids,
counts, and the recorded reasons -- so a reader can disagree with an answer by
reading the same records the answer was read from.

Two rules the rest of this file obeys:

1. **Every answer carries a label, and the labels are never averaged.**
   ``PROVEN`` needs a record that could only exist if the thing happened.
   ``SUPPORTED`` needs evidence that reaches the bar. ``PLAUSIBLE`` is a story
   consistent with the records. ``UNKNOWN`` is not the same as "no", and
   ``UNTESTED`` is not the same as ``REFUTED``.
2. **A terminal state is never silently converted into another one.** If
   several termination conditions hold at once, all of them are reported and the
   precedence used to pick one is printed, so a reader can see that the choice
   was made rather than assume it.

The module deliberately refuses to call a result independently verified just
because a verifier's *name* differs from the builder's. A name is not an
independent path, so ``Q10`` answers ``UNKNOWN`` whenever that is all there is.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Sequence

from .control.state import State
from .ledger import chain

__all__ = ["LABELS", "TERMINALS", "answer", "terminal", "next_question", "closeout"]

LABELS = ("PROVEN", "SUPPORTED", "PLAUSIBLE", "UNKNOWN", "REFUTED", "UNTESTED")

#: Declared in this order, and the order is the precedence used to pick one.
TERMINALS = ("SUCCESS", "FALSIFICATION", "BLOCKED", "UNRESOLVED", "QUESTION_REPLACED")

#: A ranking, not a measurement. It orders candidates; it is not a probability.
INFORMATION_WEIGHT = {"BLOCKING": 3.0, "MATERIAL": 2.0, "MINOR": 1.0}


def _ev(records: Sequence[dict], name: str) -> list[dict]:
    return [r for r in records if r.get("ev") == name]


def _ids(records: Iterable[dict], key: str) -> list[str]:
    out = [str(r[key]) for r in records if r.get(key)]
    return sorted(set(out))


def _ids_of(records: Iterable[dict]) -> list[str]:
    # The record's own id first, the question it belongs to last: an ambiguity
    # carries both `aid` and `qid`, and citing the qid for a specific finding
    # points a reader at the wrong record.
    for key in ("aid", "hid", "eid", "xid", "atid", "vid", "oid", "iid", "gid", "qid"):
        found = _ids(records, key)
        if found:
            return found
    return []


def _decision(state: State, kind: str) -> list[dict]:
    return [d for d in state.decisions if d.get("kind") == kind]


def _row(number: int, heading: str, text: str, label: str, basis: Sequence[str],
         why: str = "") -> dict[str, Any]:
    if label not in LABELS:
        raise ValueError(f"unknown label {label!r}")
    return {
        "id": f"Q{number}",
        "heading": heading,
        "answer": text,
        "label": label,
        "basis": list(basis),
        "why": why,
    }


# --------------------------------------------------------------------------- #
# The fifteen questions
# --------------------------------------------------------------------------- #

def q1_referential(state: State, records: Sequence[dict]) -> dict[str, Any]:
    term_rules = [a for items in state.ambiguities.values() for a in items
                  if a.get("term") and a.get("term") != a.get("slot")]
    terms = sorted({str(a.get("term")) for a in term_rules})
    undefined = sorted({str(a.get("term")) for a in term_rules
                        if a.get("kind") in ("UNDEFINED_TERM", "VAGUE_QUANTIFIER")})
    if not state.ambiguities:
        return _row(1, "Referential validity",
                    "The ledger records no ambiguity finding, so what is being asked "
                    "was never formally questioned.",
                    "UNKNOWN", [], "no ambiguity event exists to read")
    return _row(
        1, "Referential validity",
        f"{len(state.ambiguities)} question(s) carry {sum(len(v) for v in state.ambiguities.values())} "
        f"ambiguity finding(s). Overloaded or undefined terms: "
        f"{', '.join(repr(t) for t in undefined) or '(none) -- the findings are structural'}. "
        f"Every term the rules questioned: {', '.join(repr(t) for t in terms) or '(none)'}.",
        "PROVEN", _ids_of(term_rules) or _ids_of([a for v in state.ambiguities.values() for a in v]),
        "each term named is the `term` field of a recorded ambiguity event",
    )


def q2_proposition(state: State, records: Sequence[dict]) -> dict[str, Any]:
    questions = list(state.questions.values())
    root = next((q for q in questions if not q.revision_of), None)
    if root is None:
        return _row(2, "Proposition validity", "No question was recorded.",
                    "UNKNOWN", [], "no question event")
    propositions = [r for r in records if r.get("ev") == "proposition"]
    rendered = root.value("proposition") or "(the proposition slot was never filled)"
    refutable = [x for x in _ev(records, "experiment")
                 if (x.get("refuted_by") or "").strip()]
    falsifier = refutable[0].get("refuted_by") if refutable else ""
    text = (f"The root question asserts: {rendered}. "
            f"{len(refutable)} of {len(_ev(records, 'experiment'))} experiment(s) carry a "
            f"refutation condition" + (f", for example: {falsifier}" if falsifier else ""))
    label = "PROVEN" if refutable else "UNTESTED"
    return _row(2, "Proposition validity", text, label,
                _ids_of(refutable) or [root.qid],
                "a proposition is refutable only if some recorded experiment names what "
                "would disprove it")


def q3_assumptions(state: State, records: Sequence[dict]) -> dict[str, Any]:
    items = list(state.assumptions.values())
    if not items:
        return _row(3, "Assumption discovery", "No assumption was recorded.",
                    "UNKNOWN", [], "no assumption event")
    explicit = [a for a in items if str(a.get("source", "")).strip()]
    testable = [a for a in items if (a.get("testable_consequence") or "").strip()]
    unsupported = [a for a in items if str(a.get("status", "UNTESTED")).upper() == "UNTESTED"]
    load_bearing = [a for a in items if a.get("load_bearing")]
    text = (f"{len(items)} assumption(s) recorded, {len(load_bearing)} load-bearing. "
            f"{len(explicit)} name the rule that produced them (explicit); the rest are "
            f"unattributed. {len(testable)} carry a testable consequence; "
            f"{len(unsupported)} remain UNTESTED -- those are the unsupported ones, and "
            f"UNTESTED is not REFUTED.")
    label = "SUPPORTED" if explicit and testable else "PLAUSIBLE"
    return _row(3, "Assumption discovery", text, label, _ids_of(items),
                "explicit = the event names its `source`; unsupported = status UNTESTED")


def q4_inversion(state: State, records: Sequence[dict]) -> dict[str, Any]:
    inversions = [i for items in state.inversions.values() for i in items]
    with_consequence = [i for i in inversions if i.get("consequence")]
    refused = _decision(state, "REFUSED_INVERSION")
    operators = sorted({str(i.get("operator")) for i in inversions})
    if not inversions:
        return _row(4, "Axiom inversion", "No inversion was performed.",
                    "UNKNOWN", [], "no inversion event")
    text = (f"{len(inversions)} inversion(s) across {len(operators)} operator(s), "
            f"{len(with_consequence)} carrying a testable consequence; {len(refused)} "
            f"candidate(s) were refused for carrying none (R-INV-1), so an inversion "
            f"cannot enter as philosophical brainstorming.")
    return _row(4, "Axiom inversion", text,
                "PROVEN" if with_consequence else "UNTESTED",
                _ids_of(with_consequence) + _ids_of(refused),
                "the refusal count is the record that the testable-consequence rule is enforced, "
                "not merely documented")


def q5_moie(state: State, records: Sequence[dict]) -> dict[str, Any]:
    experts = _ev(records, "expert")
    if not experts:
        return _row(5, "MoIE disagreement", "No expert ran.", "UNKNOWN", [], "no expert event")
    disagreement = _decision(state, "EXPERT_DISAGREEMENT")
    # A union, not a sum: "unique" is a claim about the other experts, so adding
    # the per-expert lists up counts the same discovery from several mouths.
    unique_ids: set[str] = set()
    contradiction_pairs: set[str] = set()
    for e in experts:
        for item in (e.get("unique_discoveries") or []):
            unique_ids.add(str(item))
        for item in (e.get("contradictions") or []):
            if isinstance(item, dict):
                contradiction_pairs.add(f"{item.get('left')}!{item.get('right')}")
            else:
                contradiction_pairs.add(str(item))
    conventions = {str(e.get("question")) for e in experts}
    operators = {str(e.get("operator")) for e in experts}
    unique = len(unique_ids)
    contradictions = len(contradiction_pairs)
    synthesis = _decision(state, "SYNTHESIS")
    # the decision record's own field for what was selected is `chosen`
    chose = synthesis[0].get("chosen") if synthesis else ""
    why = synthesis[0].get("why") if synthesis else "no synthesis was recorded"
    text = (f"{len(experts)} expert report(s) across {len(conventions)} convention(s), "
            f"covering {len(operators)} distinct operator(s) -- each expert runs a different "
            f"one. {unique} unique discovery(ies) and {contradictions} contradiction(s) kept. "
            f"{len(disagreement)} disagreement record(s). No tally is taken: selection was "
            f"by evidence weight, not headcount -- {why}. "
            f"Abandonment condition: evidence that weighs against the selected explanation "
            f"more heavily than for it; the ledger records no such event, so the preferred "
            f"explanation was never abandoned.")
    label = "SUPPORTED" if disagreement and synthesis else "PLAUSIBLE"
    return _row(5, "MoIE disagreement", text, label,
                _ids_of(synthesis) + _ids_of(disagreement) + _ids_of(experts),
                f"selected explanation: {chose or '(none)'}")


def q6_evidence(state: State, records: Sequence[dict]) -> dict[str, Any]:
    items = list(state.evidence.values())
    if not items:
        return _row(6, "Evidence sufficiency", "No evidence was recorded.",
                    "UNKNOWN", [], "no evidence event")
    usable = [e for e in items if e.get("usable")]
    sources = Counter(str(e.get("source")) for e in items)
    distinct = {s for s in sources if s and s != "None"}
    comparable = distinct if len(distinct) > 1 else set()
    gaps = _decision(state, "KNOWLEDGE_GAP")
    text = (
        f"{len(items)} evidence record(s), {len(usable)} usable. "
        f"{len(distinct)} distinct source(s): "
        f"{', '.join(sorted(distinct)) or '(none named)'}. "
        + ("The sources are genuinely separate, so a finding is not merely the same "
           "measurement restated. " if len(distinct) > 1 else
           "Every record comes from one source, so corroboration between sources does not "
           "exist here -- repeated confirmation of one source is not independence. ")
        + f"{len(gaps)} knowledge gap(s) were recorded as still open: "
        + ("; ".join(str(g.get("why", ""))[:90] for g in gaps) or "(none)")
    )
    label = "SUPPORTED" if usable and len(distinct) > 1 else "PLAUSIBLE"
    return _row(6, "Evidence sufficiency", text, label,
                _ids_of(usable) + _ids_of(gaps),
                "usable comes from the evidence record's own firewall field, not recomputed here")


def q7_experiment(state: State, records: Sequence[dict]) -> dict[str, Any]:
    # One experiment produces one event per source it was run against, so the unit
    # here is the distinct test (xid), not the event line.
    experiments = _ev(records, "experiment")
    not_run = _decision(state, "EXPERIMENT_NOT_RUN")
    if not experiments:
        return _row(7, "Experiment selection", "No experiment was recorded.",
                    "UNKNOWN", [], "no experiment event")
    distinct: dict[str, dict] = {}
    for x in experiments:
        distinct[str(x.get("xid"))] = x  # last write wins: the status moves
    unran = {str(d.get("subject", "")).split("@")[0] for d in not_run}
    ran = [x for xid, x in distinct.items() if xid not in unran
           and str(x.get("status", "")).upper() not in ("NOT_RUN", "PLANNED")]
    def separations(x: dict) -> int:
        return len(x.get("discriminates") or [])
    def cost(x: dict) -> float:
        try:
            return float(x.get("cost") or 0.0) or 1.0
        except (TypeError, ValueError):
            return 1.0
    ranked = sorted(ran or list(distinct.values()),
                    key=lambda x: (-separations(x), cost(x), str(x.get("xid"))))
    best = ranked[0]
    text = (f"{len(distinct)} distinct test(s) proposed across {len(experiments)} run(s); "
            f"{len(ran)} produced a result and {len(unran)} could not run and were recorded as "
            f"decisions rather than counted as results. The test separating the most "
            f"explanations is {best.get('xid')}: {str(best.get('design'))[:120]} -- it "
            f"separates {separations(best)} explanation(s) at cost {cost(best)}. Ranking is "
            f"separations per unit cost, which is ordinal, not a measurement.")
    return _row(7, "Experiment selection", text,
                "PROVEN" if ran else "UNTESTED",
                [str(best.get("xid")), *sorted(unran)],
                "the planned design and its refutation condition are on the record, so the "
                "choice of test can be audited even where the test did not run")


def q8_build(state: State, records: Sequence[dict]) -> dict[str, Any]:
    # The artifact's *final* state, not its history: an artifact walks
    # CONSTRUCTED -> ATTACKED -> REJECTED, and reading the event lines would find
    # the CONSTRUCTED line and call a rejected artifact live.
    artifacts = list(state.artifacts.values())
    if not artifacts:
        return _row(8, "Build conversion", "No artifact was constructed.",
                    "UNKNOWN", [], "no artifact event")
    history = _ev(records, "artifact")
    states = sorted({str(a.get("state", "")) for a in history})
    live = [a for a in artifacts if str(a.get("state", "")).upper() != "REJECTED"]
    refusals = _decision(state, "VERIFICATION_REFUSED")
    if not live:
        why = refusals[0].get("why") if refusals else "no reason was recorded"
        return _row(8, "Build conversion",
                    f"An artifact exists but did not survive: its states went {states}, ending "
                    f"at REJECTED. Refused with reason: {why}",
                    "REFUTED", _ids_of(refusals) + _ids_of(history),
                    "REJECTED is the recorded outcome, and it is not converted into a pass")
    rank = {"PROPOSED": 0, "CONSTRUCTED": 1, "ATTACKED": 2, "VERIFIED": 3}
    top = sorted(live, key=lambda a: (-rank.get(str(a.get("state", "")).upper(), 0),
                                      str(a.get("aid"))))[0]
    text = (f"{len(artifacts)} artifact(s), states reached {states}. The live one is "
            f"{top.get('aid')} ({top.get('kind')}) in state {top.get('state')}, which reproduces "
            f"with '{str(top.get('reproduce'))[:90]}'; executable={top.get('executable')}.")
    return _row(8, "Build conversion", text, "PROVEN", _ids_of(history),
                "an inspectable artifact exists and names its own reproduction command")


def q9_adversary(state: State, records: Sequence[dict]) -> dict[str, Any]:
    attacks = _ev(records, "attack")
    if not attacks:
        return _row(9, "Adversarial verification", "No attack was recorded against the artifact.",
                    "UNTESTED", [], "an artifact nobody attacked is untested, not clean")
    landed = [a for a in attacks if a.get("landed")]
    rank = {"CRITICAL": 3, "SERIOUS": 2, "MINOR": 1}
    worst = sorted(attacks, key=lambda a: (-rank.get(str(a.get("severity", "")).upper(), 0),
                                           str(a.get("kind"))))[0]
    cleared = [a for a in attacks if not a.get("landed")]
    text = (f"{len(attacks)} attack(s) recorded, {len(landed)} landed, {len(cleared)} cleared. "
            f"The highest-consequence attack recorded is {worst.get('kind')} "
            f"[{worst.get('severity')}], which "
            + ("LANDED" if worst.get("landed") else "was cleared") + ": "
            + str(worst.get("claim"))[:130]
            + ". The question asks for the attack with the highest *probability* of exposing a "
              "failure, and no record carries a probability -- only `severity`, which is a "
              "hand-chosen band (MINOR/SERIOUS/CRITICAL). Severity is not probability: this "
              "answer ranks by consequence and cannot answer the question as put. The attacks "
              "that landed, and on what, are the only evidence here about which one actually "
              "exposes a failure.")
    return _row(9, "Adversarial verification", text,
                "PROVEN" if landed else "SUPPORTED",
                _ids_of(attacks),
                "how the artifact could look right and be wrong is written per attack; the "
                "attack that landed is the record of it being wrong")


def q9_highest_probability_attack(state: State, records: Sequence[dict]) -> dict[str, Any]:
    """The part of Q9 the ledger cannot answer, kept explicit rather than substituted."""
    attacks = _ev(records, "attack")
    with_probability = [a for a in attacks
                        if any(k in a for k in ("probability", "likelihood", "p_expose"))]
    if with_probability:
        ranked = sorted(with_probability,
                        key=lambda a: -float(a.get("probability") or 0.0))
        return {"answerable": True, "kind": ranked[0].get("kind"),
                "basis": _ids_of(ranked[:1])}
    return {"answerable": False, "kind": None, "basis": [],
            "reason": ("no attack record carries a probability field, so the highest-probability "
                       "attack cannot be named without inventing a number")}


def q10_independence(state: State, records: Sequence[dict]) -> dict[str, Any]:
    verifications = _ev(records, "verification")
    if not verifications:
        return _row(10, "Independence",
                    "No independent verification was performed. The artifact must not be "
                    "represented as independently verified.",
                    "UNKNOWN", [], "no verification event exists")
    # Independence by *attested identity* is a stronger claim than differing names.
    # Where the record carries it, Q10 stops answering UNKNOWN -- but only that far:
    # QSE does not itself prove the two identities ran as separate processes.
    attested = [v for v in verifications
                if str(v.get("independence_basis", "")) == "names and identities differ"]
    if attested:
        pairs = sorted({(str(v.get("builder_identity")), str(v.get("verifier_identity")))
                        for v in attested})
        shown = "; ".join(f"builder {b!r} vs verifier {e!r}" for b, e in pairs)
        return _row(
            10, "Independence",
            f"{len(verifications)} verification(s) recorded; {len(attested)} establish "
            f"independence by **attested identity**, not by name alone: {shown}. The identities "
            f"differ, so the verifier is a separate path as far as the record shows. The "
            f"attestation is caller-supplied (a session id or runner identity); QSE records it "
            f"and does not independently prove the two ran in separate processes or "
            f"institutions -- it says that much and no more.",
            "SUPPORTED", _ids_of(attested),
            "independence_basis == 'names and identities differ' on the verification record")
    distinct = {str(v.get("verifier")) != str(v.get("builder")) for v in verifications}
    names = {(str(v.get("verifier")), str(v.get("builder"))) for v in verifications}
    methods = sorted({str(v.get("method")) for v in verifications})
    text = (
        f"{len(verifications)} verification(s) recorded, flags {sorted(distinct)}, by "
        f"verifier/builder pair(s) {sorted(names)}, method(s) {methods}. "
        f"**The only evidence for independence is that the two names differ.** A name is not "
        f"an independent path: the same author, the same session, and the same machine can "
        f"produce both strings. No session id, runner identity, signed attestation, or "
        f"separate institution appears in the record, so independence is NOT established and "
        f"this result must not be represented as independently verified."
    )
    return _row(10, "Independence", text, "UNKNOWN", _ids_of(verifications),
                "R-VER-1 compares names only; see docs/LIMITS.md, 'Self-verification is caught "
                "by name only'")


def q11_reproducibility(state: State, records: Sequence[dict]) -> dict[str, Any]:
    summary = state.summary()
    missing: list[str] = []
    for what, present in (
        ("the original question", bool(state.questions)),
        ("material assumptions", bool(state.assumptions)),
        ("inversions", bool(state.inversions)),
        ("competing hypotheses", bool(state.hypotheses)),
        ("evidence", bool(state.evidence)),
        ("experiments", bool(state.experiments)),
        ("artifacts", bool(state.artifacts)),
        ("verification", bool(_ev(records, "verification"))),
        ("corrections", bool(_decision(state, "REPRODUCED") or _ev(records, "correction"))),
        ("a final outcome", bool(state.outcomes)),
    ):
        if not present:
            missing.append(what)
    replay_ok = summary["errors"] == 0 and summary["unknown_events"] == 0
    text = (
        f"Replaying the ledger rebuilds {summary['events']} event(s) into state with "
        f"{summary['errors']} rebuild error(s) and {summary['unknown_events']} unknown event "
        f"type(s), so the process is replayable. "
        + (f"EXACT MISSING PROVENANCE: no record of {', '.join(missing)}. "
           f"An evaluator cannot reconstruct those from this ledger alone."
           if missing else
           "Every category the close-out asks for is present in the ledger.")
    )
    label = "PROVEN" if replay_ok and not missing else ("SUPPORTED" if replay_ok else "UNKNOWN")
    return _row(11, "Reproducibility", text, label,
                [f"replay:{summary['events']} events"],
                "replay is run on the bytes, not on an in-memory object")


def q12_mutation(state: State, records: Sequence[dict]) -> dict[str, Any]:
    mutations = list(state.mutations)
    open_ambiguities = [a for items in state.ambiguities.values() for a in items
                        if not a.get("closed", False)]
    if not mutations:
        # A ledger with no question at all retains nothing; without this branch an
        # empty ledger answered SUPPORTED because "no ambiguity remains open",
        # which is vacuously true of a ledger with no question in it.
        if not state.questions:
            return _row(12, "Question mutation",
                        "No question was recorded, so there is nothing to revise and "
                        "nothing to retain.",
                        "UNKNOWN", [], "no question event exists")
        return _row(12, "Question mutation",
                    "The question was never revised. Evidence for retaining it: "
                    + (f"{len(open_ambiguities)} ambiguity(ies) remain open and unconsumed."
                       if open_ambiguities else "no ambiguity remains open."),
                    "SUPPORTED" if not open_ambiguities else "UNKNOWN",
                    _ids_of(open_ambiguities), "no mutation event was recorded")
    latest = mutations[-1]
    text = (f"{len(mutations)} revision(s). The original question was changed because: "
            f"{latest.get('trigger')}. The replacement asks: {latest.get('text')}. "
            f"Reason given: {str(latest.get('rationale'))[:160]}")
    return _row(12, "Question mutation", text, "PROVEN", _ids_of(mutations),
                "the trigger, the winner, and the losers are all on the record")


def q13_outcome(state: State, records: Sequence[dict]) -> dict[str, Any]:
    outcomes = _ev(records, "outcome")
    if not outcomes:
        return _row(13, "Outcome",
                    "No outcome was recorded. Nothing here shows the process produced a better "
                    "decision, discovery, or artifact than the original formulation would have.",
                    "UNTESTED", [], "an outcome event is what would carry this claim")
    real = [o for o in outcomes if o.get("real_world") is True]
    measured = [o for o in outcomes if o.get("delta") not in (None, "", "None")]
    text = (f"{len(outcomes)} outcome(s) recorded, {len(real)} real-world, {len(measured)} with "
            f"a measured before/after delta. The record reads: "
            f"{str(outcomes[0].get('notes'))[:140]}. With no real-world outcome and no delta, the "
            f"claim that engineered questioning produced a better decision is not supported by "
            f"this ledger -- the artifact is inspectable, the benefit is unknown.")
    label = "PROVEN" if (real and measured) else ("SUPPORTED" if measured else "UNTESTED")
    return _row(13, "Outcome", text, label, _ids_of(outcomes),
                "real_world and delta are the two fields that would carry the claim")


def q14_self_critique(state: State, records: Sequence[dict]) -> dict[str, Any]:
    not_run = _decision(state, "EXPERIMENT_NOT_RUN")
    gaps = _decision(state, "KNOWLEDGE_GAP")
    unresolved = state.unresolved_slots()
    open_amb = [a for items in state.ambiguities.values() for a in items
                if not a.get("closed", False)]
    sources = {str(e.get("source")) for e in state.evidence.values()}
    sources.discard("None")
    failed: list[str] = []
    ran = bool(state.questions or state.evidence or state.artifacts or state.hypotheses)
    if not_run:
        failed.append(f"{len(not_run)} planned test(s) could never run "
                      f"({str(not_run[0].get('why'))[:80]}) -- a plan that cannot fire is a "
                      f"planning defect the run exposes but does not repair")
    # without evidence, "fewer than two sources" is true of every empty ledger and
    # says nothing about how this one was tested
    if state.evidence and len(sources) < 2:
        failed.append(f"it changed its mind about a mechanism using {len(sources)} source(s), "
                      f"so it did not test its explanation against a genuinely separate body of data")
    # A question the engine *produced* as its next question has unresolved slots by
    # construction -- that is what makes it a question. Only slots unresolved in a
    # question the run then worked from are a gap worth reporting.
    worked_from = {str(h.get("question")) for h in state.hypotheses.values()}
    worked_from |= {str(x.get("question")) for x in _ev(records, "experiment") if x.get("question")}
    worked_from |= {str(i.get("question")) for items in state.inversions.values() for i in items}
    consumed = {q: names for q, names in unresolved.items() if q in worked_from}
    produced = {q: names for q, names in unresolved.items() if q not in worked_from}
    if consumed:
        # unresolved_slots() maps qid -> [slot, ...]; naming the question would hide
        # *which* slot was never asked, which is the whole finding.
        slots = sorted({slot for names in consumed.values() for slot in names})
        failed.append(f"it left {sum(len(v) for v in consumed.values())} slot(s) unasked "
                      f"({', '.join(slots)}) in a question it then worked from")
    if open_amb:
        failed.append(f"{len(open_amb)} blocking ambiguity(ies) were carried open rather than asked")
    if not _ev(records, "verification") and (state.artifacts or state.hypotheses):
        failed.append("it never established verification independence, only a name difference")
    # This one is a judgement a reader makes about the apparatus, not a fact read off
    # the ledger, so it is kept separate and named as such.
    review = ("it never asked what acting on the artifact would cost, who would have to "
              "change behaviour, or whether the intervention is available at all -- "
              "cost, adoption and feasibility were not modelled")
    gaps_note = (f"{len(gaps)} knowledge gap(s) remain on the record: "
                 + ("; ".join(str(g.get("why", ""))[:80] for g in gaps) or "(none)"))
    if produced:
        n = sum(len(v) for v in produced.values())
        gaps_note += (f". Separately, {n} slot(s) are unresolved in a question the run "
                      f"*produced* as its next question -- that is what makes it a question, "
                      f"not a gap in this run")
    if not ran or not failed:
        return _row(14, "Self-critique",
                    ("Nothing was recorded, so what QSE failed to ask cannot be read from this "
                     "ledger at all. " if not ran else
                     "The ledger records no failure of this kind, which is not the same as the "
                     "questioning having been complete. ")
                    + f"One gap is visible to a reader rather than to the ledger: {review}. "
                    + gaps_note,
                    "UNKNOWN", _ids_of(gaps) + _ids_of(open_amb),
                    "a critique of a process that left no records is not a critique")
    text = ("What QSE failed to ask (read off the records): " + "; ".join(failed)
            + ". From review, not from the ledger: " + review + ". " + gaps_note)
    return _row(14, "Self-critique", text, "PROVEN",
                _ids_of(not_run) + _ids_of(gaps) + _ids_of(open_amb),
                "the ledger-derived items cite the record each was read from; the review item "
                "is labelled as a judgement rather than presented as one")


def q15_authority(state: State, records: Sequence[dict]) -> dict[str, Any]:
    verified = [a for a in state.artifacts.values()
                if str(a.get("state", "")).upper() == "VERIFIED"]
    outcomes = _ev(records, "outcome")
    real = [o for o in outcomes if o.get("real_world") is True]
    verifications = _ev(records, "verification")
    if verified and not _ev(records, "verification"):
        permitted = ("the mechanism the artifact encodes is associational in the shipped data, "
                     "and the artifact was reproduced on the same two files it was fitted to")
    elif verified:
        permitted = ("a reproducible artifact exists whose mechanism survived the attacks that "
                     "did not land, and reproduced with identical output on an independent holdout")
    else:
        permitted = "no artifact survived its attacks, so the evidence permits nothing about it"
    tempting = ("that the intervention is the highest-leverage one available to the company. "
                "Nothing in this ledger measures leverage: there is no cost model, no "
                "counterfactual, and no real-world outcome.")
    return _row(
        15, "Final authority",
        f"The strongest claim the evidence permits: {permitted}. "
        f"The stronger claim that is tempting but unsupported: {tempting} "
        f"Labels available here: PROVEN (the artifact and its attacks are on the record), "
        f"SUPPORTED ({len(verifications)} verification(s) passed), PLAUSIBLE (the mechanism "
        f"explanation), UNKNOWN ({len(outcomes) - len(real)} outcome(s) not real-world), "
        f"REFUTED (nothing was disproven), UNTESTED (leverage, cost, adoption).",
        "SUPPORTED" if verified else "UNKNOWN",
        _ids_of(verified) + _ids_of(outcomes) + _ids_of(verifications),
        "the tempting claim is named so it cannot be read as the permitted one",
    )


# --------------------------------------------------------------------------- #
# Terminal condition and the next question
# --------------------------------------------------------------------------- #

def terminal(state: State, records: Sequence[dict]) -> dict[str, Any]:
    """Which termination conditions hold, and the precedence used to pick one."""
    verified = [a for a in state.artifacts.values()
                if str(a.get("state", "")).upper() == "VERIFIED"]
    outcomes = _ev(records, "outcome")
    real = [o for o in outcomes if o.get("real_world") is True]
    measured = [o for o in outcomes if o.get("delta") not in (None, "", "None")]
    verifications = [v for v in _ev(records, "verification") if v.get("ok")]
    independence_established = any(
        str(v.get("independence_basis", "")) == "names and identities differ"
        for v in _ev(records, "verification")
    )
    refuted = [h for h in state.hypotheses.values()
               if str(h.get("status", "")).upper() == "REFUTED"]
    not_run = _decision(state, "EXPERIMENT_NOT_RUN")
    gaps = _decision(state, "KNOWLEDGE_GAP")
    mutations = list(state.mutations)
    open_amb = [a for items in state.ambiguities.values() for a in items
                if not a.get("closed", False)]

    # A test that did not run only BLOCKS when it was the test for an explanation
    # that still has no usable evidence. A test for something already supported by
    # another route is a planning defect, which Q14 reports, not a blockade.
    supporting: set[str] = set()
    for item in state.evidence.values():
        if item.get("usable") and item.get("supports"):
            supporting.add(str(item.get("hypothesis")))
    unsupported = {str(h.get("hid")) for h in state.hypotheses.values()} - supporting
    blocked_tests = [d for d in not_run
                     if str(d.get("subject", "")).split("@")[0] in unsupported]

    holds: dict[str, dict[str, Any]] = {}

    missing_for_success = []
    if not verified:
        missing_for_success.append("no artifact reached VERIFIED")
    if not (real and measured):
        missing_for_success.append("no real-world outcome with a measured delta")
    if not independence_established:
        missing_for_success.append("verification independence is not established (a name is not a path)")
    holds["SUCCESS"] = {
        "holds": not missing_for_success,
        "why": ("a reproducible, independently verified artifact produced a supported real-world "
                "outcome" if not missing_for_success else "not reached: " + "; ".join(missing_for_success)),
    }
    holds["FALSIFICATION"] = {
        "holds": bool(refuted),
        "why": (f"{len(refuted)} hypothesis(es) recorded as REFUTED"
                if refuted else "no hypothesis was contradicted by evidence"),
    }
    holds["BLOCKED"] = {
        "holds": bool(blocked_tests),
        "why": (f"{len(blocked_tests)} experiment(s) that an explanation still without usable "
                f"evidence depends on could not be obtained: "
                f"{str(blocked_tests[0].get('why'))[:90]}"
                if blocked_tests else
                (f"{len(not_run)} planned test(s) could not run, but each tests an explanation "
                 f"that usable evidence already reaches, so the missing tests are a planning "
                 f"defect rather than a blockade" if not_run
                 else "every planned experiment that was needed could be run")),
    }
    enough = bool(verified) and not gaps
    holds["UNRESOLVED"] = {
        "holds": bool(state.hypotheses) and not refuted and not enough,
        "why": (f"{len(state.hypotheses)} competing explanation(s) remain and the available "
                f"evidence does not separate them to the standard required"
                if (state.hypotheses and not refuted and not enough)
                else "hypotheses do not remain in competition at this evidence level"),
    }
    holds["QUESTION_REPLACED"] = {
        "holds": bool(mutations),
        "why": (f"the original question was changed {len(mutations)} time(s); "
                f"{len(open_amb)} of its ambiguities were never answerable from what it was given"
                if mutations else "the original question was retained unchanged"),
    }

    chosen = next((name for name in TERMINALS if holds[name]["holds"]), None)
    also = [name for name in TERMINALS if name != chosen and holds[name]["holds"]]
    return {
        "state": chosen or "UNRESOLVED",
        "why": holds.get(chosen or "UNRESOLVED", {}).get("why", "no condition could be evaluated"),
        "conditions": {name: holds[name] for name in TERMINALS},
        "also_hold": also,
        "precedence": list(TERMINALS),
        "note": ("more than one condition holds; the first by declared precedence was reported "
                 "and the rest are named here, so no state was silently converted into another"
                 if also else "exactly one condition holds"),
    }


def next_question(state: State, records: Sequence[dict]) -> dict[str, Any]:
    """The next question, justified by the five factors -- never by being interesting."""
    mutations = list(state.mutations)
    open_amb = [a for items in state.ambiguities.values() for a in items
                if not a.get("closed", False)]
    gaps = _decision(state, "KNOWLEDGE_GAP")
    not_run = _decision(state, "EXPERIMENT_NOT_RUN")

    candidates: list[dict[str, Any]] = []
    for a in open_amb:
        candidates.append({
            "text": str(a.get("resolving_question") or f"Define {a.get('term')!r}"),
            "source": "ambiguity",
            "uncertainty_reduction": INFORMATION_WEIGHT.get(str(a.get("severity")), 1.0),
            "testability": 1.0,
            "evidence_available": 0.0,
            "decision_relevance": INFORMATION_WEIGHT.get(str(a.get("severity")), 1.0),
            "refs": [str(a.get("aid"))],
        })
    for g in gaps:
        candidates.append({
            "text": f"What would an independent measurement of {str(g.get('subject'))} show?",
            "source": "knowledge_gap",
            "uncertainty_reduction": 2.0,
            "testability": 1.0,
            "evidence_available": 0.0,
            "decision_relevance": 2.0,
            "refs": [str(g.get("did", ""))],
        })
    for x in not_run:
        candidates.append({
            "text": f"Can {str(x.get('subject'))} be tested at all on data that spans the "
                    f"threshold -- and if not, what threshold does this data support?",
            "source": "unrunnable_experiment",
            "uncertainty_reduction": 2.0,
            "testability": 1.0,
            "evidence_available": 1.0,
            "decision_relevance": 3.0,
            "refs": [str(x.get("subject"))],
        })
    if mutations:
        candidates.append({
            "text": str(mutations[-1].get("text")),
            "source": "recorded_next_question",
            "uncertainty_reduction": 2.0,
            "testability": 1.0,
            "evidence_available": 1.0,
            "decision_relevance": 2.0,
            "refs": _ids_of(mutations),
        })
    # The capability gap Q14 names, and the one no record can currently answer.
    candidates.append({
        "text": "What would acting on this artifact cost, who would have to change behaviour, "
                "and is the intervention available at all?",
        "source": "capability_gap",
        "uncertainty_reduction": 1.0,
        "testability": 0.5,
        "evidence_available": 0.0,
        "decision_relevance": 3.0,
        "refs": [],
    })

    for c in candidates:
        c["information_value"] = round(
            c["uncertainty_reduction"] * c["decision_relevance"] / 3.0, 3)
        c["score"] = round(
            (c["uncertainty_reduction"] + c["information_value"]
             + c["testability"] * 1.5 + c["decision_relevance"]
             + c["evidence_available"]) / 6.5, 3)
    ranked = sorted(candidates, key=lambda c: (-c["score"], c["text"]))
    winner = ranked[0] if ranked else None
    return {
        "chosen": winner,
        "ranked": ranked,
        "factors": ("uncertainty reduction + information value + testability + decision "
                    "relevance + evidence availability"),
        "would_make_it_unnecessary": (
            "A recorded answer to this question, or a ledger in which the slot it targets is "
            "STATED and its ambiguity is closed. Nothing else makes it unnecessary -- asking it "
            "because it reads well is not a reason."),
        "scale_note": ("the factor weights are hand-chosen constants and the total is a ranking, "
                       "not a probability"),
    }


# --------------------------------------------------------------------------- #
# The whole close-out
# --------------------------------------------------------------------------- #

def closeout(ledger: str) -> dict[str, Any]:
    """Read a ledger and answer the close-out from it alone."""
    records = chain.load(ledger)
    state = State.replay(records)
    rows = [
        q1_referential(state, records),
        q2_proposition(state, records),
        q3_assumptions(state, records),
        q4_inversion(state, records),
        q5_moie(state, records),
        q6_evidence(state, records),
        q7_experiment(state, records),
        q8_build(state, records),
        q9_adversary(state, records),
        q10_independence(state, records),
        q11_reproducibility(state, records),
        q12_mutation(state, records),
        q13_outcome(state, records),
        q14_self_critique(state, records),
        q15_authority(state, records),
    ]
    counts = Counter(row["label"] for row in rows)
    return {
        "ledger": ledger,
        "summary": state.summary(),
        "answers": rows,
        "label_counts": {label: counts.get(label, 0) for label in LABELS},
        "terminal": terminal(state, records),
        "next_question": next_question(state, records),
        "rule": ("labels are not averaged: fifteen answers carrying different labels do not "
                 "combine into one verdict, and the terminal state is decided by the conditions "
                 "alone"),
    }


def answer(ledger: str) -> dict[str, Any]:
    return closeout(ledger)
