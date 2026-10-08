"""One synthetic company's cloud bill, built to be answerable -- and to be able to fail.

The question is the one finance actually asks:

    Which lever actually reduces the cloud bill -- instance sizing, idle
    capacity, storage, egress, retry storms, or the way the bill is attributed?

The answer built into the data is **provisioned-but-unused capacity**
(``idle_hours``). Everything else on the list is either a genuine but smaller
term, or a **fitting-period artifact** that collapses when the confound goes away.

What makes this fixture honest
-----------------------------
Two periods, one mechanism:

* **fit period** (``cloud_fit.json``, 600 rows) -- a historical month. The
  idleness metric was estimated by a sampling agent that was wrong in both
  directions, so the *recorded* ``idle_hours`` is the true idleness plus error. The
  instance class (``vcpus``) was taken from the cost team's review list, which
  tracked the true idleness -- so on this period ``vcpus`` is a **better**
  predictor than ``idle_hours`` is. An analyst given only this month reaches for
  ``vcpus``, and is not being stupid: on that data it is the better column.
* **holdout period** (``cloud_holdout.json``, 400 rows) -- the next month, after
  the telemetry was fixed and instance class was recorded prospectively. The
  mechanism is unchanged, so ``idle_hours`` holds; ``vcpus`` is now independent
  of the outcome and carries nothing.

That is the necessary condition for a mechanism-versus-correlate comparison to be
runnable at all, and it is all it is: ``qse.cli fixture`` checks that the columns
which outrank the driver on the fit *collapse* on the holdout. It does not make
the engineered arm win -- the engineered arm still has to name the mechanism.

Two columns are deliberately **not** candidates for any rule
------------------------------------------------------------
``EXCLUDED`` names ``billed_usd``. The overspend flag is *defined* as "the bill
exceeded the committed amount", so the bill is not an explanation for the
overspend -- it is the overspend. A pipeline that is not told this will happily
build ``billed_usd >= 218.0`` as its top-ranked detector and score it near
perfectly, for the same reason ``failed >= 24`` scored perfectly once: the rule
is reading the thing it is supposed to predict. You cannot infer that from the
data (a perfect correlate and a perfect predictor look identical there), so it is
declared. ``ROLES`` is the rest of the same declaration: which column is the
outcome, which groups the analysis, which carries time.

Deterministic: same seed -> byte-identical file.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

__all__ = [
    "QUESTION", "FACTS", "NOTE",
    "FIT_SEED", "HOLDOUT_SEED", "FIT_ROWS", "HOLDOUT_ROWS",
    "BUDGET_USD", "EXCLUDED", "IDLE_MEASUREMENT_SIGMA", "ROLES",
    "fit_rows", "holdout_rows", "fit_payload", "holdout_payload", "write",
]

QUESTION = (
    "A company's cloud bill keeps growing and finance cannot explain it. Nobody can "
    "tell whether the driver is instance sizing, provisioned-but-unused capacity, "
    "storage growth, egress, retry storms, or the way the bill is attributed across "
    "teams. Find the highest-leverage lever and prove why it is the highest-leverage "
    "one, rather than the one that happens to look biggest this month."
)

FACTS: dict[str, str] = {
    "referential": (
        "an over-budget resource-month: a machine, disk or managed service whose bill "
        "for the period exceeded the committed amount for it, measured per resource"
    ),
    "proposition": (
        "A provisioned-but-unused capacity state can be identified before the period "
        "closes, and reclaiming it reduces the bill."
    ),
    "scope": (
        "one cloud account, three teams, three regions, 600+400 resource-months over "
        "two consecutive periods; historical billing records, not live telemetry"
    ),
    "authority": (
        "the finance owner owns the definition of over budget; the billing export owns "
        "the numbers; the platform team owns the instance-class catalogue"
    ),
    "obligation": (
        "must prove the lever generalises to a period the fit never saw, and must never "
        "claim the bill explains the bill"
    ),
    "temporal": (
        "definitions valid for the whole window; no pricing change recorded during it"
    ),
    "consumption": (
        "the platform lead; decision = reclaim idle capacity or resize instance classes; "
        "if the result is wrong, the reclaim work is spent and the bill does not fall"
    ),
}

NOTE = (
    "Synthetic. The real driver is provisioned-but-unused capacity (idle_hours). "
    "billed_usd is what the overspend flag is computed from, so it is not a candidate "
    "explanation -- it is the overspend. vcpus outranks the driver on the fitting "
    "period only because instance class was recorded from the review list that period, "
    "while the idleness metric that period was estimated by a sampling agent that was "
    "wrong in both directions; untagged_fraction is the same artifact in the "
    "cost-attribution data. egress_gb is missing for 17% of resource-months. Nobody "
    "tells the engine any of this."
)

FIT_SEED = 20261008
HOLDOUT_SEED = 20261009
FIT_ROWS = 600
HOLDOUT_ROWS = 400

#: The committed amount for one resource-month, in dollars. A flat committed standard
#: rather than a per-resource budget, so the overspend flag is one comparison instead
#: of two fitted numbers.
BUDGET_USD = 218.0

#: Columns that are derived from the outcome and are therefore not candidate
#: explanations or artifact inputs. Declared, not inferred -- see the module docstring.
EXCLUDED = ("billed_usd",)

#: Hours. How wrong the fitting period's idleness sampling agent was. Named so it can
#: be argued with, like every other threshold in this repository.
IDLE_MEASUREMENT_SIGMA = 4.5

#: The roles the engine is told, instead of the roles it would guess. ``_binder`` in
#: ``qse/experiment/planner.py`` guesses *orders-domain* names; a cloud table has none
#: of them, so every experiment came back ``ran: False`` until these were declared.
ROLES: dict[str, str] = {
    "outcome": "over_budget",
    "group": "team",
    "time": "ts_h",
    "precursor": "idle_hours",
    "value": "idle_hours",
    "field": "idle_hours",
    "x": "egress_gb",
    "y": "over_budget",
    "candidates": (
        "idle_hours,vcpus,avg_cpu_pct,mem_pct,storage_gb,egress_gb,retries_millions,"
        "requests_millions,untagged_fraction"
    ),
    "columns": (
        "idle_hours,vcpus,avg_cpu_pct,mem_pct,storage_gb,egress_gb,retries_millions,"
        "requests_millions,untagged_fraction"
    ),
    "exclude": "billed_usd",
}

_TEAMS = ("platform", "data", "product")
_REGIONS = ("us-central1", "europe-west1", "asia-east1")
_CAUSES = ("autoscaling", "autoscaling", "oversizing", "retry_storm")


def _class_for(idle: int) -> int:
    """The instance class that would carry this much idle capacity."""
    return 2 ** min(6, max(1, idle // 4 + 1))


def _billed(idle: int, storage: float, rng: random.Random) -> float:
    """The bill for one resource-month: idle capacity priced, plus storage, plus noise."""
    return round(100.0 + 9.0 * idle + 0.01 * storage + rng.gauss(0.0, 6.0), 2)


def _fit_rows(n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        idle_true = rng.randint(0, 20)
        storage = round(rng.uniform(400.0, 1600.0), 1)
        billed = _billed(idle_true, storage, rng)
        over = 1 if billed > BUDGET_USD else 0

        # CONFOUND 1 -- this period's idleness metric was estimated by a sampling agent
        # that was wrong in BOTH directions, so the recorded idle_hours is the true
        # idleness plus error. That is what lets a coarser correlate outrank the
        # mechanism on this period: the mechanism is still the mechanism, but the
        # column that records it is noisy here and accurate in the next period.
        idle = max(0, min(24, round(idle_true + rng.gauss(0.0, IDLE_MEASUREMENT_SIGMA))))

        # CONFOUND 2 -- instance class was recorded from the cost team's review list,
        # which tracked the true idleness. On this period it is a *better* predictor
        # than the recorded telemetry, and it is a recording practice, not a mechanism.
        reviewed = rng.random() < 0.98
        vcpus = _class_for(idle_true) if reviewed else _class_for(rng.randint(0, 20))

        # The same artifact in the attribution data.
        untagged = round(
            min(0.6, 0.05 + 0.09 * idle_true + rng.gauss(0.0, 0.06)) if reviewed
            else rng.uniform(0.02, 0.35), 3,
        )

        rows.append({
            "resource_id": f"R{i:04d}",
            "ts_h": round(i * 12.0, 1),
            "team": _TEAMS[i % 3],
            "region": _REGIONS[i % 3],
            "instance_class": f"n2-{vcpus}",
            "vcpus": vcpus,
            "idle_hours": idle,
            "avg_cpu_pct": round(max(1.0, 55.0 - 1.6 * idle_true + rng.gauss(0.0, 18.0)), 2),
            "mem_pct": round(max(1.0, 48.0 - 1.1 * idle_true + rng.gauss(0.0, 17.0)), 2),
            "storage_gb": storage,
            # 17% of resource-months have no egress reading at all
            "egress_gb": None if rng.random() < 0.17 else round(rng.uniform(5.0, 900.0), 1),
            "retries_millions": round(max(0.0, 1.5 + 0.35 * idle_true + rng.gauss(0.0, 3.0)), 3),
            "requests_millions": round(rng.uniform(0.4, 90.0), 3),
            "untagged_fraction": untagged,
            "billed_usd": billed,
            "reported_cause": _CAUSES[i % 4],
            "over_budget": over,
        })
    return rows


def _holdout_rows(n: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        idle_true = rng.randint(0, 20)
        storage = round(rng.uniform(400.0, 1600.0), 1)
        billed = _billed(idle_true, storage, rng)
        over = 1 if billed > BUDGET_USD else 0
        rows.append({
            "resource_id": f"H{i:04d}",
            "ts_h": round(i * 12.0, 1),
            "team": _TEAMS[i % 3],
            "region": _REGIONS[i % 3],
            # telemetry fixed: idle is recorded accurately
            "idle_hours": idle_true,
            # instance class recorded prospectively, independent of the outcome
            "vcpus": _class_for(rng.randint(0, 20)),
            "avg_cpu_pct": round(max(1.0, 55.0 - 1.6 * idle_true + rng.gauss(0.0, 18.0)), 2),
            "mem_pct": round(max(1.0, 48.0 - 1.1 * idle_true + rng.gauss(0.0, 17.0)), 2),
            "storage_gb": storage,
            "egress_gb": None if rng.random() < 0.17 else round(rng.uniform(5.0, 900.0), 1),
            "retries_millions": round(max(0.0, 1.5 + 0.35 * idle_true + rng.gauss(0.0, 3.0)), 3),
            "requests_millions": round(rng.uniform(0.4, 90.0), 3),
            "untagged_fraction": round(rng.uniform(0.02, 0.35), 3),
            "billed_usd": billed,
            "reported_cause": _CAUSES[i % 4],
            "over_budget": over,
        })
    return rows


def fit_rows(n: int = FIT_ROWS, seed: int = FIT_SEED) -> list[dict[str, Any]]:
    return _fit_rows(n, seed)


def holdout_rows(n: int = HOLDOUT_ROWS, seed: int = HOLDOUT_SEED) -> list[dict[str, Any]]:
    return _holdout_rows(n, seed)


def fit_payload(n: int = FIT_ROWS, seed: int = FIT_SEED) -> dict[str, Any]:
    return {"name": "cloud-fit", "question": QUESTION, "facts": dict(FACTS),
            "note": NOTE, "rows": _fit_rows(n, seed)}


def holdout_payload(n: int = HOLDOUT_ROWS, seed: int = HOLDOUT_SEED) -> dict[str, Any]:
    return {"name": "cloud-holdout",
            "note": (f"Second period for the cloud cost scenario. Same mechanism as the "
                     f"fit period (the bill is priced from idle capacity), with the "
                     f"fitting-period recording confounds absent: idle is recorded "
                     f"accurately and instance class is drawn independently of the "
                     f"outcome. Generated by qse.cloud.scenario, seed {seed}."),
            "rows": _holdout_rows(n, seed)}


def write(directory: str | Path) -> tuple[Path, Path]:
    """Write both periods beside each other. Returns the two paths."""
    import json

    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    fit = out / "cloud_fit.json"
    hold = out / "cloud_holdout.json"
    fit.write_text(json.dumps(fit_payload(), indent=2) + "\n", encoding="utf-8")
    hold.write_text(json.dumps(holdout_payload(), indent=2) + "\n", encoding="utf-8")
    return fit, hold
