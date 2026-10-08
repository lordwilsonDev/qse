#!/usr/bin/env python3
"""MOONSHOT-C -- the cloud cost question singularity engine.

One command. One page. The exit code is the answer.

    python3 moonshot_cloud.py                      # the shipped synthetic fixture
    python3 moonshot_cloud.py --write examples     # write the fixture out and stop
    python3 moonshot_cloud.py --fit my_bill.json --holdout next_month.json \
        --outcome over_budget --driver idle_hours

What it does, in order, and stops at the first one it cannot do honestly:

1. **Can this data answer the question at all?**  A comparison needs a
   counterfactual, so it needs a fixture in which the analyst with no question
   engineering is *punished* -- the columns that outrank the real lever on one
   period must collapse on a period the fit never saw. If they do not, no result
   from this data could mean anything, and the script says so and exits 1 rather
   than producing a number.

2. **What did the engineered process build, and does it beat the naive analyst?**
   The naive arm is given one period and reaches for the strongest correlate in
   it. The engineered arm is the whole QSE loop, run on both periods. Both rules
   are scored by the same statistic on the holdout, at each rule's own threshold.

3. **Does the whole run hold up?**  The moonshot's 17-item acceptance list,
   evaluated against the run's own ledger by the same code the CLI uses.

Then it prints where the engineered arm's field came from, because a win is not a
win until you know which period named it. In this domain they come apart: the
fitting period's own scan decides confidently on a column that collapses, and the
field that ships is the one the *second* period named and the first still
supports. That is the finding, and it is printed rather than left in a footnote.

Exit codes: `0` the data can carry the comparison, the engineered arm is validated
and wins by the margin, and every acceptance check holds; `1` it did not; `2`
input the script cannot use.

Standard library only, like the engine it drives. It changes nothing outside the
files you ask it to write and the ledger it is given: no cloud credentials, no
network, no billing account.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qse import baseline, cli  # noqa: E402
from qse.cloud import scenario  # noqa: E402
from qse.control.controller import Engine  # noqa: E402
from qse.experiment.runner import Dataset  # noqa: E402
from qse.ids import freeze, parse_ts  # noqa: E402
from qse.ledger import chain  # noqa: E402

OK, DEFECT, UNUSABLE = 0, 1, 2


class Unusable(RuntimeError):
    """Input this script cannot use at all. Exit 2 -- and a returned code, not a raise:
    ``SystemExit`` with a string exits 1, which would report unusable input as a
    defect and make the exit code a different answer from the printed one."""

#: Frozen so a run is reproducible. The verdict is clock-free; the ledger is not.
DEFAULT_NOW = "2026-10-08T12:00:00Z"


def _load(path: str, what: str) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        raise Unusable(f"{what} not found: {path}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise Unusable(f"{what} is not valid JSON ({exc})")
    if not isinstance(payload.get("rows"), list) or not payload["rows"]:
        raise Unusable(f"{what} {path} has no rows")
    return payload


def _period(args: argparse.Namespace) -> tuple[dict, dict, dict[str, str], str, str, tuple[str, ...]]:
    """The two periods, the declared roles, and what the comparison is built around.

    Synthetic by default so the script is runnable with no data at all. Given
    ``--fit`` and ``--holdout`` it reads real exports instead, and then the caller has
    to name the outcome and the lever: those cannot be guessed from column names
    without inventing them, which is the defect this script's own domain found.
    """
    if not args.fit and not args.holdout:
        roles = dict(scenario.ROLES)
        fit = scenario.fit_payload()
        hold = scenario.holdout_payload()
        return fit, hold, roles, scenario.QUESTION, "idle_hours", scenario.EXCLUDED

    if not args.fit or not args.holdout:
        raise Unusable("pass both --fit and --holdout, or neither (neither generates the "
                        "shipped synthetic fixture)")
    if not args.outcome or not args.driver:
        raise Unusable("real data needs --outcome COLUMN and --driver COLUMN. Which column is "
                        "the outcome, and which lever are you betting on? The engine will not "
                        "guess: guessing is what broke it on cloud data.")
    fit = _load(args.fit, "fit period")
    hold = _load(args.holdout, "holdout period")
    excluded = tuple(p.strip() for p in (args.exclude or "").split(",") if p.strip())
    roles: dict[str, str] = {}
    for item in args.role or ():
        role, separator, value = str(item).partition("=")
        if not separator or not role.strip():
            raise Unusable(f"--role {item!r} is not ROLE=COLUMN")
        roles[role.strip()] = value.strip()
    roles["outcome"] = args.outcome
    if excluded:
        roles["exclude"] = ",".join(excluded)
    question = args.question or (fit.get("facts") and None) or fit.get("question")
    if not question:
        raise Unusable("no question. Pass --question, or put a 'question' field in the fit file.")
    return fit, hold, roles, str(question), args.driver, excluded


def _receipt(
    *,
    question: str,
    fit: dict, hold: dict,
    excluded: tuple[str, ...],
    gate: Mapping[str, Any],
    naive_rule: Mapping[str, Any],
    engineered_rule: Mapping[str, Any],
    scored: Mapping[str, Any],
    provenance: Mapping[str, Any],
    built: Mapping[str, Any] | None,
    attacked: Mapping[str, Any] | None,
    verify: Mapping[str, Any] | None,
    rows: list[dict[str, Any]],
    metrics: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Everything the run found, as one page and one object."""
    arms = list(scored.get("arms") or [])
    passed = [row for row in rows if row["ok"]]
    failed = [row for row in rows if not row["ok"]]
    holds = bool(rows) and not failed
    verdict_ok = bool(scored["engineered_wins"] and holds)

    lines: list[str] = []
    lines.append("MOONSHOT-C  cloud cost question singularity engine")
    lines.append("")
    lines.append(f"  question   {question[:96]}")
    lines.append(f"  fit        {fit.get('name', 'fit')} ({len(fit['rows'])} resource-months)")
    lines.append(f"  holdout    {hold.get('name', 'holdout')} ({len(hold['rows'])} resource-months)")
    if excluded:
        lines.append(f"  excluded   {', '.join(excluded)}  <- derived from the outcome, so not "
                     "an explanation for it")
    lines.append("")

    lines.append("1. CAN THIS DATA ANSWER THE QUESTION?")
    lines.append("   the naive arm (no question engineering, one period) reaches for "
                 f"{str(gate.get('naive_pick', {}).get('column') if gate.get('naive_pick') else None)!r}")
    lines.append(f"   the lever this was built around is {gate.get('driver')!r}")
    top = list(gate.get("ranked") or [])[:6]
    if top:
        lines.append(f"     {'column':<22} {'fit r':>8} {'holdout r':>10}")
        for row in top:
            hold_r = "n/a" if row["holdout"] is None else f"{row['holdout']:+.3f}"
            lines.append(f"     {row['column']:<22} {row['fit']:>+8.3f} {hold_r:>10}")
    lines.append(f"   SEPARABLE: {bool(gate.get('separable'))}")
    lines.append(f"     {gate.get('reason')}")
    lines.append("")

    lines.append("2. WHAT DID THE ENGINEERED PROCESS BUILD?")
    for arm in arms:
        rule = (naive_rule if arm["arm"] == "naive" else engineered_rule) or {}
        field = rule.get("field")
        desc = ("(no detector)" if not field
                else f"{field} {rule.get('op', '>=')} {rule.get('threshold')}")
        if field and not arm["validated"]:
            desc += "  (unvalidated)"
        fit_j = arm["fit"].get("youden")
        hold_j = arm["holdout"].get("youden")
        lines.append(f"   {arm['arm']:<11} {desc:<34} "
                     f"fit J {'n/a' if fit_j is None else format(fit_j, '+.3f'):>6}  "
                     f"holdout J {'n/a' if hold_j is None else format(hold_j, '+.3f'):>7}  "
                     f"flagged {arm['holdout'].get('flagged', '-')}")
        if not arm["holdout"].get("scored"):
            lines.append(f"       note: {arm['holdout'].get('reason')}")
    lines.append(f"   engineered arm wins: {bool(scored['engineered_wins'])} "
                 f"(margin {scored['margin']})")
    lines.append("")

    lines.append("3. WHERE THE FIELD CAME FROM  (read from the run's own ledger)")
    if provenance.get("field"):
        lines.append(f"   the shipped field is {provenance['field']!r}")
        for entry in provenance.get("named_by") or ():
            lines.append(f"     named by {entry['source']}: separation {entry['separation']}, "
                         f"margin {entry['margin']} over {entry['runner_up']}")
        for entry in provenance.get("rejected") or ():
            lines.append(f"     {entry['source']} decided on {entry['decided_on']!r} instead "
                         f"(separation {entry['separation']}) -- rejected: it does not replicate")
        for entry in provenance.get("ranked_on") or ():
            lines.append(f"     {provenance['field']} on {entry['source']}: "
                         f"separation {entry['separation']}")
        for entry in provenance.get("undecided") or ():
            named = ", ".join(entry["contenders"]) or "nothing measurable"
            lines.append(f"     {entry['source']} did not decide: could not separate "
                         f"{entry['best']!r} ({entry['separation']}) from {named}")
    else:
        for entry in provenance.get("undecided") or ():
            named = ", ".join(entry["contenders"]) or "nothing measurable"
            lines.append(f"   no field was named; {entry['source']} could not separate "
                         f"{entry['best']!r} ({entry['separation']}) from {named}")
        if not provenance.get("undecided"):
            lines.append("   no field was named, and no scan reached the bar to name one")
    lines.append("")

    lines.append("4. DOES THE WHOLE RUN HOLD UP?  (the 17-item acceptance list, from the ledger)")
    lines.append(f"   {len(passed)}/{len(rows)} hold" if rows else "   no ledger to check")
    for row in failed:
        lines.append(f"     [FAIL] {row['id']}  {row['label']}: {row['why']}")
    if built:
        lines.append(f"   artifact {built.get('artifact')}  state "
                     f"{(verify or {}).get('state_after', '?')}  "
                     f"attacks {(attacked or {}).get('attacks', '?')} "
                     f"({(attacked or {}).get('verdict', 'not attacked')})")
    lines.append("")

    lines.append("VERDICT")
    if not gate.get("separable"):
        lines.append("   THIS DATA CANNOT ANSWER THE QUESTION. Read the reason in step 1: no "
                     "result from it could be credited, so none was produced.")
    elif scored["engineered_unscored"] is not None:
        lines.append(f"   NOT YET. The engineered arm named no field to score "
                     f"({scored['engineered_unscored']}).")
    elif scored["engineered_unvalidated"]:
        lines.append("   NOT YET. The engineered rule was chosen by construction, not by "
                     "measurement, so it is not credited.")
    elif scored["engineered_wins"]:
        lines.append("   THE MOONSHOT'S TERMINAL CLAIM HOLDS ON THIS FIXTURE -- read step 3 "
                     "before repeating it.")
    else:
        lines.append("   NOT YET. The engineered arm does not beat the naive analyst by the "
                     "margin, so the terminal claim does not hold here.")
    if not holds and rows:
        lines.append(f"   AND the acceptance list does not pass: {len(failed)} of {len(rows)} "
                     "checks fail, which is its own verdict.")
    lines.append("")
    lines.append(f"   QBY {metrics.get('QBY', {}).get('value')}  "
                 f"BC {metrics.get('BC', {}).get('value')}  "
                 f"EC {metrics.get('EC', {}).get('value')}  "
                 f"OC {metrics.get('OC', {}).get('value')}   "
                 "(definitions on this run, not achievements -- OC is 0 because no "
                 "real-world outcome exists here)")

    payload = {
        "separable": bool(gate.get("separable")),
        "verdict_ok": verdict_ok,
        "naive_rule": dict(naive_rule),
        "engineered_rule": dict(engineered_rule),
        "arms": arms,
        "engineered_wins": bool(scored["engineered_wins"]),
        "field_provenance": dict(provenance),
        "acceptance": {"passed": len(passed), "total": len(rows),
                       "failed": [row["id"] for row in failed]},
        "metrics": dict(metrics),
    }
    return "\n".join(lines), payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="moonshot_cloud.py",
        description="MOONSHOT-C: can this cloud cost data answer the question, what does "
                    "engineered questioning build, and does it beat the naive analyst?",
    )
    parser.add_argument("--fit", help="a real first period (JSON with 'rows')")
    parser.add_argument("--holdout", help="a real second, independent period")
    parser.add_argument("--outcome", help="the column being explained (required with --fit)")
    parser.add_argument("--driver", help="the lever this was built around (required with --fit)")
    parser.add_argument("--exclude", default="",
                        help="comma list of columns derived from the outcome")
    parser.add_argument("--role", action="append", default=[], metavar="ROLE=COLUMN",
                        help="declare what a column is; repeatable")
    parser.add_argument("--question", help="defaults to the fit file's own 'question' field")
    parser.add_argument("--ledger", help="where to record the run (default: a temp file)")
    parser.add_argument("--now", default=DEFAULT_NOW, help="freeze the clock")
    parser.add_argument("--authority", default="the finance owner")
    parser.add_argument("--write", metavar="DIRECTORY",
                        help="write the synthetic fixture into this directory and stop")
    parser.add_argument("--json", action="store_true", help="print the machine-readable object")
    args = parser.parse_args(argv)
    try:
        return _execute(args)
    except Unusable as exc:
        print(f"unusable input: {exc}", file=sys.stderr)
        return UNUSABLE


def _execute(args: argparse.Namespace) -> int:

    if args.write:
        fit_path, hold_path = scenario.write(args.write)
        print(f"wrote {fit_path} ({len(scenario.fit_rows())} rows)")
        print(f"wrote {hold_path} ({len(scenario.holdout_rows())} rows)")
        return OK

    moment = parse_ts(args.now)
    if moment is None:
        raise Unusable(f"--now {args.now!r} is not an ISO timestamp")
    freeze(moment)

    scratch = Path(tempfile.mkdtemp(prefix="moonshot-c-"))
    try:
        fit_payload, hold_payload, roles, question, driver, excluded = _period(args)
        fit_rows, hold_rows = fit_payload["rows"], hold_payload["rows"]
        ledger = args.ledger or str(scratch / "run.jsonl")

        # 1. Can this data answer the question at all?
        gate = baseline.audit(fit_rows, hold_rows, outcome=args.outcome or "over_budget",
                              driver=driver, exclude=excluded)

        if not gate["separable"]:
            page, payload = _receipt(
                question=question, fit=fit_payload, hold=hold_payload, excluded=excluded,
                gate=gate, naive_rule={}, engineered_rule={},
                scored={"arms": [], "margin": baseline.SEPARABILITY_MARGIN,
                        "engineered_wins": False, "engineered_unscored": None,
                        "engineered_unvalidated": False},
                provenance={}, built=None, attacked=None, verify=None, rows=[], metrics={})
            _emit(page, payload, args.json)
            return DEFECT

        # 2. What does the engineered process build?
        engine = Engine(ledger)
        report = engine.run(
            question,
            answers=fit_payload.get("facts") or {},
            datasets=[Dataset(name=str(fit_payload.get("name") or "fit"), rows=fit_rows),
                      Dataset(name=str(hold_payload.get("name") or "holdout"), rows=hold_rows)],
            rows=fit_rows,
            authority=args.authority or None,
            roles=roles,
        )
        build_stage = next((s for s in report.stages if s.get("stage") == "build"), None)
        attack_stage = next((s for s in report.stages if s.get("stage") == "attack"), None)
        verify_stage = next((s for s in report.stages if s.get("stage") == "verify"), None)
        engineered_rule = dict((build_stage or {}).get("rule") or {})

        naive_rule = baseline.best_threshold_rule(
            fit_rows, gate["naive_pick"]["column"], outcome=args.outcome or "over_budget") or {}
        scored = baseline.score_arms(naive_rule, engineered_rule, fit_rows, hold_rows,
                                     outcome=args.outcome or "over_budget")

        # 3. Does the whole run hold up?
        try:
            records = chain.load(ledger)
        except chain.LedgerCorrupt as exc:  # pragma: no cover - defensive
            print(f"ledger cannot be trusted: {exc}", file=sys.stderr)
            return DEFECT
        rows = cli.acceptance(records)
        provenance = cli.detector_provenance(
            ledger, fitting_source=str(fit_payload.get("name") or "fit"),
            field=engineered_rule.get("field")
            if isinstance(engineered_rule.get("field"), str) else None)

        page, payload = _receipt(
            question=question, fit=fit_payload, hold=hold_payload, excluded=excluded,
            gate=gate, naive_rule=naive_rule, engineered_rule=engineered_rule,
            scored=scored, provenance=provenance, built=build_stage, attacked=attack_stage,
            verify=verify_stage, rows=rows, metrics=report.metrics)
        _emit(page, payload, args.json)
        return OK if payload["verdict_ok"] else DEFECT
    finally:
        if not args.ledger:
            for leftover in scratch.glob("*"):
                leftover.unlink(missing_ok=True)
            scratch.rmdir()


def _emit(page: str, payload: Mapping[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(page)


if __name__ == "__main__":
    raise SystemExit(main())
