"""Planning: turn a hypothesis into a specific, runnable test.

A planner that emits the same boilerplate design for every hypothesis is not
planning. The design, predictions and refutation condition here are written from
the hypothesis's own five structural fields, and the runner is chosen by a
documented ``(mechanism, locus)`` table, so "staffing capacity" and "the metric
is an aggregation artifact" get tests that could actually tell them apart.

``required_data`` doubles as the runner's argument list. That convention is:

* a bare name is a column the runner needs;
* ``role=column`` binds a role (``precursor``, ``outcome``, ``x``, ``y``,
  ``group``, ``value``, ``field``, ``candidates``) to a column;
* ``min_hours=N`` and ``threshold=N`` carry declared numeric parameters.

It lives in ``required_data`` rather than in a parallel field so a plan stays one
object that can be logged, replayed and re-run unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from ..core.experiment import Experiment, make_experiment
from ..core.hypothesis import Hypothesis

__all__ = ["RUNNER_FOR", "propose", "discriminating", "best_to_run", "coverage"]

#: Which runner a hypothesis's structure calls for. Order matters only for reads.
RUNNER_FOR: dict[tuple[str, str], str] = {
    ("LATENCY", "*"): "precursor_detection",
    ("CAPACITY", "*"): "coverage_scan",
    ("MEASUREMENT", "*"): "aggregation_check",
    ("AGGREGATION", "*"): "aggregation_check",
    ("VARIANCE", "*"): "variance_compare",
    ("COORDINATION", "*"): "variance_compare",
    ("EXTERNAL", "*"): "correlation_split",
    ("SEQUENCING", "*"): "correlation_split",
    ("POLICY", "*"): "counterfactual_replay",
    ("EXTERNAL", "SUPPLIER"): "correlation_split",
    ("COORDINATION", "COMMUNICATION"): "correlation_split",
    ("CAPACITY", "STAFFING"): "variance_compare",
}

_DEFAULT_RUNNER = "discrimination_scan"

#: Cost/duration by runner, so `best_to_run` can rank on more than a guess.
_COST = {
    "coverage_scan": (1.0, 1.0),
    "variance_compare": (1.0, 2.0),
    "correlation_split": (2.0, 4.0),
    "precursor_detection": (2.0, 4.0),
    "aggregation_check": (2.0, 4.0),
    "discrimination_scan": (3.0, 6.0),
    "counterfactual_replay": (4.0, 8.0),
}


def _runner_for(hypothesis: Hypothesis) -> str:
    specific = RUNNER_FOR.get((hypothesis.mechanism, hypothesis.locus))
    if specific:
        return specific
    return RUNNER_FOR.get((hypothesis.mechanism, "*"), _DEFAULT_RUNNER)


def _binder(runner: str, columns: Sequence[str]) -> tuple[str, ...]:
    """Roles bound to plausible column names, plus the columns themselves.

    Column names are guessed from conventional business-workflow field names and
    are *declared*, not assumed: a runner that cannot find its column reports
    ``ran: False`` with the missing names rather than inventing a result.
    """
    pool = list(columns)
    by_name = {c.lower(): c for c in pool}

    def pick(*preferences: str, default: str) -> str:
        for pref in preferences:
            for lowered, original in by_name.items():
                if pref in lowered:
                    return original
        return default

    outcome = pick("outcome", "late", "failed", "sla_violated", default="failed")
    time_col = pick("ts", "timestamp", "time", "hour", default="ts_h")
    precursor = pick("precursor", "queue", "wait", "latency", "lead", default="queue_wait_h")
    group = pick("shift", "team", "group", "site", "week", default="shift")
    supplier = pick("supplier", "vendor", default="supplier_lead_days")

    def declared(*names: str) -> tuple[str, ...]:
        return tuple(n for n in names if n in pool) or tuple(names[:1])

    if runner == "precursor_detection":
        return ("precursor=" + precursor, "outcome=" + outcome, "time=" + time_col, "min_hours=6") + declared(
            precursor, outcome, time_col
        )
    if runner in ("aggregation_check", "correlation_split"):
        x_col = supplier if runner == "correlation_split" and supplier in pool else precursor
        return ("x=" + x_col, "y=" + outcome, "group=" + group) + declared(x_col, outcome, group)
    if runner == "variance_compare":
        return ("value=" + precursor, "group=" + group) + declared(precursor, group)
    if runner == "coverage_scan":
        # A comma list, not repeated `column=` keys: `bindings()` returns a dict,
        # so a repeated role would silently collapse to its last value.
        watched = pool or [precursor]
        return ("columns=" + ",".join(watched),) + declared(*watched)
    if runner == "counterfactual_replay":
        return ("field=" + precursor, "op=>=", "threshold=24", "outcome=" + outcome) + declared(precursor, outcome, time_col)
    if runner == "discrimination_scan":
        candidates = ",".join(pool[:6]) if pool else precursor
        return ("outcome=" + outcome, "candidates=" + candidates) + declared(*pool)
    return declared(*pool) if pool else (precursor,)


def propose(
    hypotheses: Iterable[Hypothesis],
    *,
    question: str,
    columns: Sequence[str] = (),
) -> list[Experiment]:
    """One specific, runnable, refutable test per hypothesis."""
    out: list[Experiment] = []
    for hypothesis in hypotheses:
        runner = _runner_for(hypothesis)
        cost, duration = _COST.get(runner, (3.0, 6.0))
        design = (
            f"{runner} over the declared dataset, partitioned by {hypothesis.locus.lower()} "
            f"at the {hypothesis.timescale.lower()} timescale, to test whether "
            f"{hypothesis.mechanism.lower()} explains the observed outcome."
        )
        out.append(
            make_experiment(
                hypothesis=hypothesis.hid,
                question=question,
                design=design,
                prediction_if_true=(
                    f"If {hypothesis.text} then the {runner.replace('_', ' ')} statistic "
                    f"separates the flagged and unflagged {hypothesis.locus.lower()} groups"
                ),
                prediction_if_false=(
                    f"If {hypothesis.text} is wrong then the statistic is the same in every "
                    f"{hypothesis.locus.lower()} group and the apparent difference is noise"
                ),
                refuted_by=(
                    f"refuted if the statistic does not differ across {hypothesis.locus.lower()} "
                    f"groups, or if the difference vanishes when {hypothesis.measurement_assumption!r} "
                    "is relaxed"
                ),
                runner=runner,
                discriminates=(hypothesis.hid,),
                required_data=_binder(runner, columns),
                cost=cost,
                duration_h=duration,
            )
        )
    return out


def discriminating(
    hypotheses: Sequence[Hypothesis],
    *,
    question: str,
    columns: Sequence[str] = (),
) -> list[Experiment]:
    """One experiment that separates as many competing hypotheses as possible.

    This is the experiment you run when you cannot afford one per hypothesis, and
    it is the one QSE ranks first: a result that eliminates four explanations is
    worth more than four results that each speak to one.
    """
    if len(hypotheses) < 2:
        return []
    candidates = ",".join(columns[:8]) if columns else "queue_wait_h,supplier_lead_days,staff_hours"
    outcome = next((c for c in columns if any(k in c.lower() for k in ("outcome", "late", "failed"))), "failed")
    return [
        make_experiment(
            hypothesis=hypotheses[0].hid,
            question=question,
            design=(
                "discrimination_scan across every candidate explanation at once, ranking each by how "
                "much of the observed outcome it accounts for, so one run separates "
                f"{len(hypotheses)} competing explanations rather than one."
            ),
            prediction_if_true=(
                "If the competing explanations are distinguishable in this data then one candidate "
                "separates the groups and the runner-up is clearly behind it"
            ),
            prediction_if_false=(
                "If they are not distinguishable then every candidate scores within noise of the others"
            ),
            refuted_by=(
                "refuted if no candidate separates the outcome, or if two candidates are within "
                "0.10 separation of each other and the data cannot choose between them"
            ),
            runner="discrimination_scan",
            discriminates=tuple(h.hid for h in hypotheses),
            required_data=(f"outcome={outcome}", f"candidates={candidates}", *columns[:8]),
            cost=4.0,
            duration_h=8.0,
        )
    ]


def best_to_run(experiments: Iterable[Experiment]) -> Experiment | None:
    """Rank by hypotheses separated per unit cost, then by the id for stability."""
    ranked = sorted(
        experiments,
        key=lambda exp: (
            -(exp.separates() / max(exp.cost, 0.001)),
            exp.cost,
            exp.xid,
        ),
    )
    return ranked[0] if ranked else None


def coverage(experiments: Iterable[Experiment], *, hypotheses: Sequence[Hypothesis] = ()) -> dict:
    """Which hypotheses have a test, and which have none.

    ``total`` and ``untested`` need the hypothesis set, which experiments alone
    cannot supply; pass it, or the untested list is empty by construction rather
    than by finding.
    """
    tested: list[str] = []
    for experiment in experiments:
        for hid in experiment.discriminates or (experiment.hypothesis,):
            if hid and hid not in tested:
                tested.append(hid)
    expected = [getattr(h, "hid", str(h)) for h in hypotheses]
    untested = [hid for hid in expected if hid not in tested]
    return {
        "hypotheses_tested": len(tested),
        "total": len(expected) if expected else len(tested),
        "untested": sorted(untested),
        "tested": sorted(tested),
    }
