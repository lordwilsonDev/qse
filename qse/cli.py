"""QSE command line.

Exit codes, which are the verdict and nothing else:

    0   the command did what it says, and every acceptance check it ran holds
    1   a defect, a refusal, or an acceptance check that does not hold
    2   the input could not be used at all (missing file, unreadable ledger, bad JSON)

``checks`` is the moonshot's own acceptance list as an executable command: it
reads a ledger and answers each of the sixteen required conditions plus the
auditability question. It exits 0 only when all of them hold, so "the moonshot
passes" is a command a machine runs rather than a claim a report makes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, baseline as baseline_mod, closeout as closeout_mod, metrics as metrics_mod
from .control.controller import (
    DEFAULT_BUILDER,
    DEFAULT_VERIFIER,
    MAX_REVISIONS,
    Engine,
)
from .control.policy import RULES
from .control.state import State
from .experiment.runner import Dataset
from .ids import freeze, parse_ts
from .inversion.ail import AILEngine
from .ledger import chain, receipts
from .question_engine import ambiguity as ambiguity_mod
from .question_engine import decomposer, dependency
from .inversion import moie

OK, DEFECT, UNUSABLE = 0, 1, 2


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _print(payload: Any, as_json: bool, text: str = "") -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    elif text:
        print(text)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _load_json(path: str, what: str) -> Any:
    target = Path(path)
    if not target.exists():
        raise Unusable(f"{what} not found: {path}")
    try:
        return json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Unusable(f"{what} is not valid JSON ({exc})") from exc


class Unusable(RuntimeError):
    """Input QSE cannot use. Exit 2."""


def _load_ledger(path: str) -> list[dict[str, Any]]:
    """A missing ledger is unusable input (exit 2). A tampered one is a defect
    QSE detected (exit 1), which is a different answer and is reported as one."""
    if not Path(path).exists():
        raise Unusable(f"ledger not found: {path}")
    return chain.load(path)


def _scenario(path: str) -> Dataset:
    payload = _load_json(path, "scenario")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise Unusable(f"scenario {path} has no rows")
    return Dataset(name=str(payload.get("name") or Path(path).stem), rows=rows)


def _freeze_if_given(value: str | None) -> None:
    moment = parse_ts(value) if value else None
    if value and moment is None:
        raise Unusable(f"--now {value!r} is not an ISO timestamp")
    freeze(moment)


# --------------------------------------------------------------------------- #
# The acceptance list
# --------------------------------------------------------------------------- #

ACCEPTANCE = (
    ("A01", "question represented formally"),
    ("A02", "ambiguities detected"),
    ("A03", "assumptions extracted"),
    ("A04", "AIL inversion performed"),
    ("A05", "multiple structurally different hypotheses generated"),
    ("A06", "disagreement preserved"),
    ("A07", "missing evidence identified"),
    ("A08", "experiment proposed"),
    ("A09", "experiment executable"),
    ("A10", "artifact constructed"),
    ("A11", "artifact attacked"),
    ("A12", "independent verification performed"),
    ("A13", "evidence provenance recorded"),
    ("A14", "original question revised when warranted"),
    ("A15", "final artifact reproducible"),
    ("A16", "entire process replayable"),
    ("A17", "another process can reconstruct why each question was asked"),
)


def acceptance(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Evaluate the moonshot's own acceptance list against a ledger.

    Every row carries the count or the ids it was decided from, so a reader can
    disagree with a PASS by looking at the same evidence the check looked at.
    """
    state = State.replay(records)
    labels = dict(ACCEPTANCE)
    rows: list[dict[str, Any]] = []

    def add(cid: str, ok: bool, why: str, **evidence: Any) -> None:
        rows.append({"id": cid, "label": labels[cid], "ok": bool(ok),
                     "why": why, "evidence": evidence})

    questions = [q for q in state.questions.values()]
    slots_ok = [q for q in questions if set(q.slots) == set(decomposer.SLOTS)]
    add("A01", bool(slots_ok), f"{len(slots_ok)} question(s) carry all seven slots",
        qids=[q.qid for q in slots_ok])

    add("A02", bool(state.ambiguities), f"{len(state.ambiguities)} question(s) with ambiguities",
        n=len(state.ambiguities))

    add("A03", bool(state.assumptions), f"{len(state.assumptions)} assumption(s) recorded",
        n=len(state.assumptions))

    with_consequence = [i for items in state.inversions.values() for i in items if i.get("consequence")]
    add("A04", bool(with_consequence), f"{len(with_consequence)} inversion(s) carrying a testable consequence",
        n=len(with_consequence))

    hypotheses = list(state.hypotheses.values())
    signatures = {h.get("signature") or h.get("mechanism") for h in hypotheses}
    add("A05", len(hypotheses) >= 2 and len(signatures) >= 2,
        f"{len(hypotheses)} hypothesis(es) in {len(signatures)} distinct structures",
        n=len(hypotheses), structures=len(signatures))

    expert_contradictions = sum(len(e.get("contradictions") or []) for e in state.experts.values())
    disagreement_records = [d for d in state.decisions if d.get("kind") == "DISAGREEMENT"]
    expert_disagreement = [d for d in state.decisions if d.get("kind") == "EXPERT_DISAGREEMENT"]
    preserved = sum(len(d.get("disagreements") or []) for d in expert_disagreement)
    add("A06", bool(expert_contradictions or disagreement_records or expert_disagreement),
        f"{expert_contradictions} contradiction(s) between experts, "
        f"{len(expert_disagreement)} expert-disagreement record(s) carrying {preserved} position(s), "
        f"{len(disagreement_records)} hypothesis disagreement(s) recorded",
        expert_contradictions=expert_contradictions, disagreements=len(disagreement_records),
        expert_disagreement=preserved)

    gaps = [d for d in state.decisions if d.get("kind") == "KNOWLEDGE_GAP"]
    add("A07", bool(gaps), f"{len(gaps)} knowledge gap(s) named", hids=[d.get("subject") for d in gaps])

    experiments = list(state.experiments.values())
    add("A08", bool(experiments), f"{len(experiments)} experiment(s) proposed", n=len(experiments))

    runnable = [x for x in experiments if x.get("runner") and (x.get("refuted_by") or "").strip()]
    add("A09", bool(runnable), f"{len(runnable)} experiment(s) name a runner and a refutation condition",
        n=len(runnable))

    artifacts = list(state.artifacts.values())
    constructed = [a for a in artifacts if a.get("state") in ("CONSTRUCTED", "ATTACKED", "VERIFIED")]
    add("A10", bool(constructed), f"{len(constructed)} artifact(s) reached CONSTRUCTED or beyond",
        aids=[a["aid"] for a in constructed])

    attacked = [items for items in state.attacks.values() if items]
    add("A11", bool(attacked), f"{sum(len(i) for i in attacked)} attack(s) recorded "
        f"against {len(attacked)} artifact(s)", n=sum(len(i) for i in attacked))

    independent = [v for v in state.verifications.values()
                   if v.get("independent") is True and v.get("ok") is True]
    add("A12", bool(independent), f"{len(independent)} independent verification(s) passed",
        vids=[v["vid"] for v in independent])

    evidence = list(state.evidence.values())
    provenanced = [e for e in evidence
                   if (e.get("source") or "").strip() and (e.get("method") or "").strip()]
    add("A13", bool(evidence) and len(provenanced) == len(evidence),
        f"{len(provenanced)}/{len(evidence)} evidence record(s) carry both source and method",
        n=len(evidence), provenanced=len(provenanced))

    mutations = [m for m in state.mutations if (m.get("trigger") or "").strip()]
    add("A14", bool(mutations), f"{len(mutations)} question revision(s) with a recorded trigger",
        gids=[m.get("gid") for m in mutations])

    reproduced = [d for d in state.decisions
                  if d.get("kind") == "REPRODUCED" and d.get("ok") is True]
    add("A15", bool(reproduced), f"{len(reproduced)} artifact(s) reproduced with identical output",
        n=len(reproduced))

    expected = {"question": len(state.questions), "ambiguity": sum(len(v) for v in state.ambiguities.values()),
                "hypothesis": len(state.hypotheses), "evidence": len(state.evidence),
                "artifact": len(state.artifacts)}
    # An empty ledger replays perfectly and has no question whose reasons are
    # missing. Both facts are true and both are vacuous, so neither check is
    # allowed to PASS on nothing -- "it replays" is a claim about a run, and there
    # was no run.
    if not records:
        add("A16", False, "there are no events to replay", unknown=state.unknown, counts=expected)
    else:
        replayed_ok = (
            isinstance(state, State)
            and state.unknown == 0
            and not state.errors
            and expected["hypothesis"] == sum(1 for r in records if r.get("ev") == "hypothesis")
        )
        add("A16", replayed_ok,
            "the ledger replays into a state with no unknown event types and no rebuild errors",
            unknown=state.unknown, errors=len(state.errors), counts=expected)

    if not state.questions:
        add("A17", False, "no question was recorded, so there is no reason chain to reconstruct")
    else:
        unaudited: list[str] = []
        for qid in state.questions:
            answer = receipts.why(records, qid)
            if not answer.get("found") or not answer.get("complete"):
                unaudited.append(qid)
        add("A17", not unaudited,
            f"every one of {len(state.questions)} question(s) has a complete, replayable reason chain",
            unaudited=unaudited)

    return rows


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_rules(args: argparse.Namespace) -> int:
    _print({"rules": [{"id": k, "protects": v} for k, v in RULES.items()]}, args.json,
           "\n".join(f"{k}  {v}" for k, v in RULES.items()))
    return OK


def cmd_ask(args: argparse.Namespace) -> int:
    answers = _load_json(args.answers, "answers") if args.answers else None
    question = decomposer.decompose(args.question, answers=answers)
    found = ambiguity_mod.detect(question)
    payload = {
        "qid": question.qid,
        "seven_slots": decomposer.seven_slot_report(question),
        "blocking": question.blocking(),
        "blocked_by": dependency.blocked_by(question),
        "ambiguities": [a.to_dict() for a in found],
    }
    lines = [f"{question.qid}  filled={sorted(question.filled())}  blocking={question.blocking()}"]
    for name, row in payload["seven_slots"].items():
        lines.append(f"  {name:<12} {row['confidence']:<10} {(row['value'] or '--')[:96]}")
    lines.append("")
    for item in found:
        lines.append(f"  {item.severity:<8} {item.kind:<20} {item.term!r:<22} {item.resolving_question[:70]}")
    _print(payload, args.json, "\n".join(lines))
    return OK


def cmd_invert(args: argparse.Namespace) -> int:
    answers = _load_json(args.answers, "answers") if args.answers else None
    question = decomposer.decompose(args.question, answers=answers)
    engine = AILEngine(question)
    accepted = engine.invert()
    rejected = engine.rejected()
    measured = moie.measure(moie.convene(question, engine))
    payload = {"qid": question.qid, "axioms": [a.to_dict() for a in engine.axioms()],
               "accepted": [i.to_dict() for i in accepted], "rejected": rejected,
               "measured": measured}
    lines = [f"{len(engine.axioms())} axiom(s), {len(accepted)} inversion(s) accepted, "
             f"{len(rejected)} refused for having no testable consequence"]
    for item in accepted[:8]:
        lines.append(f"  {item.operator:<20} {item.statement[:84]}")
    lines.append(f"agreement={len(measured.get('agreement', []))} "
                 f"disagreement={len(measured.get('disagreement', []))} "
                 f"contradictions={len(measured.get('contradictions', []))}")
    _print(payload, args.json, "\n".join(lines))
    return OK


def cmd_run(args: argparse.Namespace) -> int:
    _freeze_if_given(args.now)
    scenario_payload = _load_json(args.scenario, "scenario")
    frames = [_scenario(args.scenario)]
    if args.holdout:
        frames.append(_scenario(args.holdout))
    facts = scenario_payload.get("facts") or {}
    if not isinstance(facts, dict):
        raise Unusable("scenario 'facts' must be an object of slot -> answer")
    question = args.question or scenario_payload.get("question")
    if not question:
        raise Unusable("no question: pass --question or put a 'question' field in the scenario file")
    engine = Engine(args.ledger, builder=args.builder, verifier=args.verifier,
                    max_revisions=args.max_revisions)
    report = engine.run(
        question,
        answers=facts,
        datasets=frames,
        rows=scenario_payload.get("rows"),
        authority=args.authority,
        real_world=args.real_world,
        before=args.before,
        after=args.after,
    )
    payload = report.to_dict()
    lines = [f"{'BLOCKED' if report.blocked else 'COMPLETED'}: {len(report.stages)} stage(s)"]
    for stage in report.stages:
        lines.append(f"  {stage.get('stage', '?'):<22} {json.dumps({k: v for k, v in stage.items() if k != 'stage'}, default=str)[:150]}")
    lines.append("")
    for key, value in report.metrics.items():
        if isinstance(value, dict) and "value" in value:
            lines.append(f"  {key:<4} {str(value['value']):>6}  ({value['numerator']}/{value['denominator']})")
    if report.next_question:
        lines.append(f"\n  next question: {report.next_question}")
    _print(payload, args.json, "\n".join(lines))
    return OK if not report.blocked else DEFECT


def cmd_replay(args: argparse.Namespace) -> int:
    records = _load_ledger(args.ledger)
    state = State.replay(records)
    payload = {"lines": len(records), "tail": chain.tail(args.ledger),
               "chain": chain.verify_chain(chain.read_lines(args.ledger))[2],
               "summary": state.summary(), "unknown_events": state.unknown,
               "rebuild_errors": state.errors}
    _print(payload, args.json,
           f"{len(records)} line(s); {payload['chain']}\n"
           + "\n".join(f"  {k:<16} {v}" for k, v in sorted(state.summary().items())))
    return OK if (state.unknown == 0 and not state.errors) else DEFECT


def cmd_receipt(args: argparse.Namespace) -> int:
    records = _load_ledger(args.ledger)
    _print(records, args.json, receipts.receipt(records))
    return OK


def cmd_why(args: argparse.Namespace) -> int:
    records = _load_ledger(args.ledger)
    answer = receipts.why(records, args.qid)
    if not answer.get("found"):
        print(answer.get("reason", "question not in this ledger"), file=sys.stderr)
        return DEFECT
    answer["decisions"] = [d for d in receipts.referenced_by(records, args.qid)
                           if d.get("ev") == "decision"]
    lines = [f"{args.qid}: root={answer['root']} complete={answer['complete']}"]
    for step in answer["chain"]:
        lines.append(f"  {step['qid']} v{step.get('version')}")
        lines.append(f"    asked:  {(step.get('raw') or '')[:100]}")
        if step.get("trigger"):
            lines.append(f"    because: {step['trigger'][:100]}")
        if step.get("mutation"):
            lines.append(f"    mutation {step['mutation'].get('kind')}: {str(step['mutation'].get('trigger'))[:90]}")
    for decision in answer["decisions"]:
        lines.append(f"  decision {decision.get('kind')}: {str(decision.get('why'))[:110]}")
    _print(answer, args.json, "\n".join(lines))
    return OK if answer.get("complete") else DEFECT


def cmd_metrics(args: argparse.Namespace) -> int:
    records = _load_ledger(args.ledger)
    scorecard = metrics_mod.scorecard(State.replay(records))
    lines = []
    for key in ("QBY", "BSR", "EC", "BC", "VI", "OC"):
        row = scorecard.get(key) or {}
        lines.append(f"  {key:<4} {str(row.get('value')):>7}  "
                     f"({row.get('numerator')}/{row.get('denominator')})  {row.get('definition')}")
    lines.append("")
    lines.extend(f"  limit: {item}" for item in scorecard.get("limits", []))
    _print(scorecard, args.json, "\n".join(lines))
    return OK


def cmd_checks(args: argparse.Namespace) -> int:
    records = _load_ledger(args.ledger)
    rows = acceptance(records)
    failed = [r for r in rows if not r["ok"]]
    lines = []
    for row in rows:
        mark = "PASS" if row["ok"] else "FAIL"
        lines.append(f"  [{mark}] {row['id']}  {row['label']}: {row['why']}")
    lines.append("")
    lines.append(f"{len(rows) - len(failed)}/{len(rows)} hold. "
                 + ("The moonshot's acceptance list passes." if not failed
                    else "The moonshot does not pass yet."))
    _print({"checks": rows, "passed": len(rows) - len(failed), "total": len(rows)}, args.json,
           "\n".join(lines))
    return OK if not failed else DEFECT


def cmd_fixture(args: argparse.Namespace) -> int:
    """Can this fixture tell a mechanism apart from a strong correlate?

    Exit 0 when it can carry the comparison, 1 when it cannot. A fixture that
    cannot punish the naive arm cannot credit the engineered one either, so this
    is the gate on whether the moonshot's terminal test is measurable here.
    """
    payload = _load_json(args.scenario, "scenario")
    rows = payload.get("rows") or []
    if not rows:
        raise Unusable("scenario has no rows to correlate")
    hold_rows = None
    if args.holdout:
        hold_rows = _load_json(args.holdout, "holdout").get("rows") or []
        if not hold_rows:
            raise Unusable("holdout has no rows to correlate")
    out = baseline_mod.audit(rows, hold_rows, outcome=args.outcome, driver=args.driver)

    lines = [f"  {len(out['ranked'])} measurable column(s), ranked on the fitting sample:",
             f"    {'column':<20} {'fit r':>8} {'holdout r':>10}"]
    for row in out["ranked"]:
        hold = "n/a" if row["holdout"] is None else f"{row['holdout']:+.3f}"
        lines.append(f"    {row['column']:<20} {row['fit']:>+8.3f} {hold:>10}")
    pick = out["naive_pick"]
    lines.append("")
    if pick:
        lines.append(f"  the naive arm (top correlate, no question engineering) picks "
                     f"{pick['column']!r}")
    lines.append(f"  the named driver is {out['driver']!r}")
    lines.append("")
    lines.append(f"  SEPARABLE: {out['separable']}")
    lines.append(f"      {out['reason']}")
    _print(out, args.json, "\n".join(lines))
    return OK if out["separable"] else DEFECT


def cmd_closeout(args: argparse.Namespace) -> int:
    """Answer the fifteen close-out questions from the ledger alone.

    Exit 0 only on SUCCESS. Every other terminal condition is exit 1, because a
    close-out that reports "not yet" is the point of running it.
    """
    _load_ledger(args.ledger)  # chain-checked before anything is read as evidence
    out = closeout_mod.closeout(args.ledger)
    term = out["terminal"]
    lines: list[str] = []
    for row in out["answers"]:
        lines.append(f"  [{row['label']:<9}] {row['id']:<4} {row['heading']}")
        lines.append(f"      {row['answer']}")
        if row["why"]:
            lines.append(f"      why: {row['why']}")
        if row["basis"]:
            shown = ", ".join(row["basis"][:6])
            extra = f" (+{len(row['basis']) - 6} more)" if len(row["basis"]) > 6 else ""
            lines.append(f"      basis: {shown}{extra}")
    lines.append("")
    lines.append("  labels (never averaged): " + "  ".join(
        f"{label}={out['label_counts'][label]}" for label in closeout_mod.LABELS))
    lines.append("")
    lines.append(f"  TERMINAL: {term['state']}")
    lines.append(f"      {term['why']}")
    if term["also_hold"]:
        lines.append(f"      also hold, not silently dropped: {', '.join(term['also_hold'])}")
        lines.append(f"      precedence applied: {' > '.join(term['precedence'])}")
    chosen = out["next_question"]["chosen"]
    if chosen:
        lines.append("")
        lines.append(f"  NEXT QUESTION: {chosen['text']}")
        lines.append(f"      justified by {out['next_question']['factors']}; score {chosen['score']}")
        lines.append(f"      unnecessary if: {out['next_question']['would_make_it_unnecessary']}")
    _print(out, args.json, "\n".join(lines))
    return OK if term["state"] == "SUCCESS" else DEFECT


def cmd_selftest(args: argparse.Namespace) -> int:
    """Run the shipped scenario, then the acceptance list, on one ledger.

    Both steps always run: a failing run does not skip the checks, because which
    checks fail is the useful part.
    """
    here = Path(__file__).resolve().parent.parent
    scenario = str(here / "examples" / "orders_scenario.json")
    holdout = str(here / "examples" / "orders_holdout.json")
    if not Path(scenario).exists():
        raise Unusable(f"the shipped scenario is missing: {scenario}")
    run_code = cmd_run(argparse.Namespace(
        json=args.json, now=args.now, scenario=scenario,
        holdout=holdout if Path(holdout).exists() else None, ledger=args.ledger,
        question=None, authority="VP of Operations", builder=DEFAULT_BUILDER,
        verifier=DEFAULT_VERIFIER, max_revisions=MAX_REVISIONS,
        real_world=False, before=None, after=None,
    ))
    check_code = cmd_checks(argparse.Namespace(json=args.json, ledger=args.ledger))
    return DEFECT if (run_code or check_code) else OK


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qse",
        description=f"QSE {__version__} -- Question Singularity Engine (MOONSHOT-Q). "
                    "Question-to-validated-artifact transformation.",
    )
    parser.add_argument("--json", action="store_true", help="print the machine-readable object")
    subs = parser.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn, help_text: str, **kwargs: Any) -> argparse.ArgumentParser:
        sub = subs.add_parser(name, help=help_text)
        sub.set_defaults(fn=fn)
        return sub

    add("rules", cmd_rules, "print every refusal rule and what it protects")

    ask = add("ask", cmd_ask, "decompose one question into the seven slots and report ambiguities")
    ask.add_argument("question")
    ask.add_argument("--answers", help="JSON object of slot -> answer")

    invert = add("invert", cmd_invert, "run AIL and MoIE on one question")
    invert.add_argument("question")
    invert.add_argument("--answers", help="JSON object of slot -> answer")

    run = add("run", cmd_run, "run the full loop on a scenario file")
    run.add_argument("--scenario", required=True)
    run.add_argument("--holdout", help="a second, independent source, used only to test generalisation")
    run.add_argument("--ledger", required=True)
    run.add_argument("--question", help="defaults to the scenario file's own 'question' field")
    run.add_argument("--authority", default="")
    run.add_argument("--builder", default=DEFAULT_BUILDER)
    run.add_argument("--verifier", default=DEFAULT_VERIFIER)
    run.add_argument("--max-revisions", type=int, default=MAX_REVISIONS)
    run.add_argument("--real-world", action="store_true", help="count the outcome as a real-world effect")
    run.add_argument("--before", type=float, default=None)
    run.add_argument("--after", type=float, default=None)
    run.add_argument("--now", help="freeze the clock at an ISO timestamp, so a run is reproducible")

    replay = add("replay", cmd_replay, "rebuild the whole run from the ledger alone")
    replay.add_argument("--ledger", required=True)

    receipt = add("receipt", cmd_receipt, "one line per ledger event")
    receipt.add_argument("--ledger", required=True)

    why = add("why", cmd_why, "reconstruct why a question was asked, from the ledger alone")
    why.add_argument("qid")
    why.add_argument("--ledger", required=True)

    metrics = add("metrics", cmd_metrics, "the six headline metrics")
    metrics.add_argument("--ledger", required=True)

    checks = add("checks", cmd_checks, "the moonshot's acceptance list, evaluated against a ledger")
    checks.add_argument("--ledger", required=True)

    closeout = add("closeout", cmd_closeout,
                   "answer the fifteen close-out questions from the ledger alone")
    closeout.add_argument("--ledger", required=True)

    fixture = add("fixture", cmd_fixture,
                  "can this fixture tell a mechanism from a strong correlate?")
    fixture.add_argument("--scenario", required=True)
    fixture.add_argument("--holdout", help="a second, independent sample")
    fixture.add_argument("--outcome", default="failed", help="the column being explained")
    fixture.add_argument("--driver", help="the column the fixture was built around")

    selftest = add("selftest", cmd_selftest, "run the shipped scenario and then the acceptance list")
    selftest.add_argument("--ledger", default="/tmp/qse-selftest.jsonl")
    selftest.add_argument("--now", default="2026-10-07T12:00:00Z",
                          help="freeze the clock so the self-test is reproducible")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.fn(args))
    except Unusable as exc:
        print(f"unusable input: {exc}", file=sys.stderr)
        return UNUSABLE
    except chain.LedgerCorrupt as exc:
        print(f"ledger cannot be trusted: {exc}", file=sys.stderr)
        return DEFECT
    except OSError as exc:
        print(f"unusable input: {exc}", file=sys.stderr)
        return UNUSABLE
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return DEFECT


if __name__ == "__main__":
    sys.exit(main())
