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
from .experiment.runner import _pearson, _xy_pairs

__all__ = ["rank_correlates", "naive_pick", "audit", "SEPARABILITY_MARGIN"]

#: How far a column's out-of-sample correlation may fall short of the driver's
#: before it counts as collapsed. A convention, named so it can be argued with.
SEPARABILITY_MARGIN = 0.15

#: Columns that are identifiers rather than measurements.
NOT_MEASUREMENTS = ("order_id", "ts_h")


def _numeric_columns(rows: Sequence[Mapping[str, Any]], outcome: str) -> list[str]:
    """Columns that yield enough paired numbers to correlate at all."""
    if not rows:
        return []
    columns = []
    for name in rows[0]:
        if name == outcome or name in NOT_MEASUREMENTS:
            continue
        if len(_xy_pairs(rows, name, outcome)) >= 3:
            columns.append(str(name))
    return sorted(columns)


def rank_correlates(
    fit: Sequence[Mapping[str, Any]],
    holdout: Sequence[Mapping[str, Any]] | None = None,
    *,
    outcome: str = "failed",
) -> list[dict[str, Any]]:
    """Every candidate column's correlation with the outcome, on both samples.

    Sorted by the fitting sample, because that is the only sample the naive arm
    would have seen. ``holdout`` is what the fixture is judged on; passing none
    leaves those fields ``None`` rather than zero, since "not measured" and "no
    correlation" are different findings.
    """
    out: list[dict[str, Any]] = []
    for column in _numeric_columns(fit, outcome):
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
) -> dict[str, Any]:
    """Can this fixture tell a mechanism apart from a strong correlate?

    ``separable`` is True only when the naive arm's pick *collapses* out of sample
    while the named driver holds. Every branch states its reason, so a reader can
    reject the verdict without re-deriving it.
    """
    ranked = rank_correlates(fit, holdout, outcome=outcome)
    pick = naive_pick(ranked)
    if not ranked:
        return {
            "separable": False, "naive_pick": None, "driver": driver, "ranked": [],
            "reason": "no candidate column yields enough paired numbers to correlate",
            "collapsed_non_drivers": [], "survivors": [],
        }
    if holdout is None:
        return {
            "separable": False, "naive_pick": pick, "driver": driver, "ranked": ranked,
            "reason": ("no holdout was supplied, so nothing can collapse out of sample and the "
                       "comparison cannot be run at all"),
            "collapsed_non_drivers": [], "survivors": [],
        }

    if driver is None:
        return {
            "separable": False, "naive_pick": pick, "driver": None, "ranked": ranked,
            "reason": ("no driver was named, so there is nothing for the naive pick to be "
                       "measured against"),
            "collapsed_non_drivers": [], "survivors": [],
        }

    by_name = {r["column"]: r for r in ranked}
    driver_row = by_name.get(driver)
    if driver_row is None or driver_row["fit"] is None:
        return {
            "separable": False, "naive_pick": pick, "driver": driver, "ranked": ranked,
            "reason": f"the named driver {driver!r} is not a measurable column in this fixture",
            "collapsed_non_drivers": [], "survivors": [],
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
        "reason": reason,
    }


def rows_of(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Rows out of a scenario file, with the columns it declares."""
    rows = payload.get("rows")
    if not isinstance(rows, Iterable):
        raise ValueError("payload has no rows")
    return [dict(r) for r in rows]
