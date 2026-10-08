"""The control arm, and whether a fixture can carry one at all.

The moonshot's terminal test is not "did QSE produce something" -- it is *does
engineered questioning create measurable capability that would not otherwise
exist*. That is a comparison, so it needs a counterfactual. The cheapest honest
counterfactual is a competent analyst given the same table and **no** question
engineering: rank every candidate column by its correlation with the outcome and
take the top one.

This module does that ranking and then asks the question that decides whether the
comparison is worth running at all:

    Can this fixture tell a mechanism apart from a strong correlate?

It can only do so if the naive arm's pick is **punished out of sample** -- that
is, if the columns that outrank the driver on the fitting data collapse on data
the fit never saw. If the naive pick stays as predictive out-of-sample as the
driver, then nothing in the fixture distinguishes "found the mechanism" from
"found a correlate", and any claim that the engineered arm did better is
unfounded. Reporting that is the point: a fixture which cannot fail the naive arm
cannot credit the engineered one either.

The correlation is imported from the experiment runner rather than reimplemented,
so this audit cannot form a second opinion about the engine's own statistic.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

# Deliberately the engine's own primitives: a reimplementation could disagree with
# the number the engine acts on, which would make the audit worthless.
from .experiment.runner import (
    DISCRIMINATION_MARGIN_FLOOR,
    _outcome_pairs,
    _pearson,
    _xy_pairs,
    _youden,
)

__all__ = ["rank_correlates", "naive_pick", "audit", "SEPARABILITY_MARGIN",
           "best_threshold_rule", "score_rule", "score_arms"]

#: How far a column's out-of-sample correlation may fall short of the driver's
#: before it counts as collapsed. A convention, named so it can be argued with.
SEPARABILITY_MARGIN = 0.15

#: Columns that are identifiers rather than measurements.
NOT_MEASUREMENTS = ("order_id", "ts_h")


def _numeric_columns(rows: Sequence[Mapping[str, Any]], outcome: str,
                     exclude: Sequence[str] = ()) -> list[str]:
    """Columns that yield enough paired numbers to correlate at all."""
    if not rows:
        return []
    banned = {str(name) for name in exclude} | {outcome} | set(NOT_MEASUREMENTS)
    columns = []
    for name in rows[0]:
        if name in banned:
            continue
        if len(_xy_pairs(rows, name, outcome)) >= 3:
            columns.append(str(name))
    return sorted(columns)


def rank_correlates(
    fit: Sequence[Mapping[str, Any]],
    holdout: Sequence[Mapping[str, Any]] | None = None,
    *,
    outcome: str = "failed",
    exclude: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """Every candidate column's correlation with the outcome, on both samples.

    Sorted by the fitting sample, because that is the only sample the naive arm
    would have seen. ``holdout`` is what the fixture is judged on; passing none
    leaves those fields ``None`` rather than zero, since "not measured" and "no
    correlation" are different findings.

    ``exclude`` names columns that are derived from the outcome -- a cloud bill, when
    the outcome *is* "the bill was over budget". Such a column correlates with the
    outcome near-perfectly and explains nothing; leaving it in the ranking would make
    the naive arm look unbeatable and the whole comparison meaningless. It cannot be
    inferred from the data (a perfect predictor and a perfect correlate look
    identical there), so it is declared by the caller.
    """
    out: list[dict[str, Any]] = []
    for column in _numeric_columns(fit, outcome, exclude):
        fit_pairs = _xy_pairs(fit, column, outcome)
        fit_r = _pearson(fit_pairs)
        if fit_r is None:
            continue
        row: dict[str, Any] = {
            "column": column,
            "fit": round(fit_r, 4),
            "n_fit": len(fit_pairs),
            "holdout": None,
            "n_holdout": 0,
        }
        if holdout is not None:
            hold_pairs = _xy_pairs(holdout, column, outcome)
            hold_r = _pearson(hold_pairs)
            row["holdout"] = None if hold_r is None else round(hold_r, 4)
            row["n_holdout"] = len(hold_pairs)
        out.append(row)
    out.sort(key=lambda r: (-abs(r["fit"]), r["column"]))
    return out


def naive_pick(ranked: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """What an analyst with no question engineering would reach for first."""
    return dict(ranked[0]) if ranked else None


def audit(
    fit: Sequence[Mapping[str, Any]],
    holdout: Sequence[Mapping[str, Any]] | None = None,
    *,
    outcome: str = "failed",
    driver: str | None = None,
    margin: float = SEPARABILITY_MARGIN,
    exclude: Sequence[str] = (),
) -> dict[str, Any]:
    """Can this fixture tell a mechanism apart from a strong correlate?

    ``separable`` is True only when the naive arm's pick *collapses* out of sample
    while the named driver holds. Every branch states its reason, so a reader can
    reject the verdict without re-deriving it. ``exclude`` is passed to
    ``rank_correlates`` -- see there for why an outcome-derived column cannot be
    left in the ranking.
    """
    ranked = rank_correlates(fit, holdout, outcome=outcome, exclude=exclude)
    pick = naive_pick(ranked)
    if not ranked:
        return {
            "separable": False, "naive_pick": None, "driver": driver, "ranked": [],
            "reason": "no candidate column yields enough paired numbers to correlate",
            "collapsed_non_drivers": [], "survivors": [], "excluded": list(exclude),
        }
    if holdout is None:
        return {
            "separable": False, "naive_pick": pick, "driver": driver, "ranked": ranked,
            "reason": ("no holdout was supplied, so nothing can collapse out of sample and the "
                       "comparison cannot be run at all"),
            "collapsed_non_drivers": [], "survivors": [], "excluded": list(exclude),
        }

    if driver is None:
        return {
            "separable": False, "naive_pick": pick, "driver": None, "ranked": ranked,
            "reason": ("no driver was named, so there is nothing for the naive pick to be "
                       "measured against"),
            "collapsed_non_drivers": [], "survivors": [], "excluded": list(exclude),
        }

    by_name = {r["column"]: r for r in ranked}
    driver_row = by_name.get(driver)
    if driver_row is None or driver_row["fit"] is None:
        return {
            "separable": False, "naive_pick": pick, "driver": driver, "ranked": ranked,
            "reason": f"the named driver {driver!r} is not a measurable column in this fixture",
            "collapsed_non_drivers": [], "survivors": [], "excluded": list(exclude),
        }

    driver_strength = abs(driver_row["holdout"] or 0.0)
    # columns the naive arm would prefer over the driver on the fitting sample
    contenders = [r for r in ranked if r["column"] != driver and abs(r["fit"]) >= abs(driver_row["fit"])]
    survivors = [r for r in contenders if abs(r["holdout"] or 0.0) >= driver_strength - margin]
    collapsed = [r for r in contenders if r not in survivors]

    if pick["column"] == driver:
        reason = (
            f"the naive arm's strongest correlate IS the named driver ({driver}), so this "
            f"fixture would credit the naive arm, not punish it"
        )
        separable = False
    elif survivors:
        names = ", ".join(f"{r['column']} (fit {r['fit']:+.3f}, holdout {r['holdout']:+.3f})" for r in survivors)
        reason = (
            f"{len(survivors)} column(s) outrank the driver on the fitting sample and stay as "
            f"predictive out of sample: {names}. The fixture therefore cannot tell a mechanism "
            f"from a strong correlate, and a win for the engineered arm here would be unfounded"
        )
        separable = False
    else:
        reason = (
            f"every column that outranks {driver} on the fitting sample collapses on the "
            f"holdout (margin {margin}), so the naive arm is punished out of sample and the "
            f"comparison can distinguish them"
        )
        separable = True

    return {
        "separable": separable,
        "naive_pick": pick,
        "driver": driver,
        "driver_strength": round(driver_strength, 4),
        "ranked": ranked,
        "contenders": contenders,
        "collapsed_non_drivers": collapsed,
        "survivors": survivors,
        "margin": margin,
        "excluded": list(exclude),
        "reason": reason,
    }


def best_threshold_rule(
    rows: Sequence[Mapping[str, Any]],
    column: str,
    *,
    outcome: str = "failed",
) -> dict[str, Any] | None:
    """The best single-threshold detector on ``column``, *fit* on ``rows``.

    This is the naive arm's rule made concrete: pick one column, then choose the
    direction and the cut that best separates the outcome on the fitting sample.
    Both directions are scanned, so a column that is protective (low values flag)
    gets a ``<=`` rule. Returns ``None`` when the column carries no usable pairs.
    """
    pairs = _outcome_pairs(rows, column, outcome)
    best: dict[str, Any] | None = None
    for op, sign in ((">=", 1.0), ("<=", -1.0)):
        j, threshold, _, _, n = _youden([(sign * v, f) for v, f in pairs])
        if threshold is None:
            continue
        real = threshold if op == ">=" else -threshold
        candidate = {
            "field": str(column),
            "op": op,
            "threshold": round(real, 4),
            "youden": round(j, 4),
            "n": n,
            # fit on the fitting sample, so it is a measured rule in QSE's sense --
            # which is exactly why the comparison scores it rather than excusing it
            "validated": True,
        }
        if best is None or candidate["youden"] > best["youden"]:
            best = candidate
    return best


def score_rule(
    rule: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
    *,
    outcome: str = "failed",
) -> dict[str, Any]:
    """Score a ``{field, op, threshold}`` rule as a detector of ``outcome``.

    The *same* statistic for both arms -- Youden's J of the rule's flagged set
    against the outcome -- so the naive and engineered arms are measured on one
    axis and neither gets a friendlier metric. A rule whose field *is* the outcome
    is reported as naming the outcome rather than scored, because a rule that
    reads ``failed`` to predict ``failed`` is circular and would score perfectly
    for the wrong reason.
    """
    field = rule.get("field")
    op = rule.get("op", ">=")
    threshold = rule.get("threshold")
    if not isinstance(field, str) or not field:
        return {"scored": False, "reason": "the rule names no field"}
    if not isinstance(threshold, (int, float)):
        return {"scored": False, "reason": "the rule has no numeric threshold",
                "field": field, "op": op}
    if str(field) == outcome:
        return {"scored": False, "names_the_outcome": True, "field": field, "op": op,
                "reason": (f"the rule flags on {outcome!r}, the outcome it would be scored "
                           "against -- circular, so it is not scored")}
    pairs = _outcome_pairs(rows, field, outcome)
    if not pairs:
        return {"scored": False, "reason": f"no numeric pairs of {field!r} and {outcome!r}",
                "field": field, "op": op}
    positives = sum(1 for _, f in pairs if f == 1)
    negatives = len(pairs) - positives
    if not positives or not negatives:
        return {"scored": False, "reason": f"{outcome!r} has only one class in these rows",
                "field": field, "op": op}
    # Score the rule AT ITS OWN threshold. Taking the best threshold instead would
    # report the field's potential rather than the rule's behaviour -- a rule that
    # flags nothing would look excellent.
    flagged_flags = [f for v, f in pairs if (v <= threshold if op == "<=" else v >= threshold)]
    flagged = len(flagged_flags)
    true_positives = sum(flagged_flags)
    false_positives = flagged - true_positives
    sensitivity = true_positives / positives
    specificity = (negatives - false_positives) / negatives
    return {
        "scored": True,
        "field": field,
        "op": op,
        "threshold": threshold,
        "youden": round(sensitivity + specificity - 1.0, 4),
        "sensitivity": round(sensitivity, 4),
        "specificity": round(specificity, 4),
        "flagged": flagged,
        "n": len(pairs),
    }


def score_arms(
    naive_rule: Mapping[str, Any],
    engineered_rule: Mapping[str, Any],
    fit: Sequence[Mapping[str, Any]],
    holdout: Sequence[Mapping[str, Any]],
    *,
    outcome: str = "failed",
    margin: float = DISCRIMINATION_MARGIN_FLOOR,
) -> dict[str, Any]:
    """Score both arms by one statistic and decide, in **one** place, whether to credit.

    The decision rule, not the phrasing, is what has to be single-sourced: the
    moonshot's terminal claim is "engineered questioning beats the analyst with no
    question engineering", and if two callers each decided that for themselves they
    could disagree without either being wrong by its own lights.

    An unvalidated rule (chosen by construction, not by measurement) is never
    credited, however good its separation looks: a rule that wins by luck is not
    evidence that questioning created the capability.
    """
    arms: list[dict[str, Any]] = []
    for name, rule in (("naive", naive_rule), ("engineered", engineered_rule)):
        arms.append({
            "arm": name,
            "validated": bool(rule.get("validated")),
            "basis": str(rule.get("basis", "")),
            "fit": score_rule(rule, fit, outcome=outcome),
            "holdout": score_rule(rule, holdout, outcome=outcome),
        })
    naive_score, engineered_score = arms[0]["holdout"], arms[1]["holdout"]
    both_scored = bool(naive_score.get("scored") and engineered_score.get("scored"))
    return {
        "arms": arms,
        "margin": margin,
        "engineered_wins": bool(
            arms[1]["validated"] and both_scored
            and engineered_score["youden"] > naive_score["youden"] + margin
        ),
        "engineered_unscored": None if engineered_score.get("scored")
        else str(engineered_score.get("reason", "")),
        "engineered_unvalidated": bool(engineered_score.get("scored")) and not arms[1]["validated"],
    }


def rows_of(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rows out of a scenario file, with the columns it declares."""
    rows = payload.get("rows")
    if not isinstance(rows, Iterable):
        raise ValueError("payload has no rows")
    return [dict(r) for r in rows]
