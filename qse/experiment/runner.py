"""Deterministic experiment runners over a declared dataset.

This is the part of QSE that computes rather than describes. Seven small
procedures live here, each over columns named in the experiment's
``required_data``.

Three rules hold for all of them, and they are why this module can be trusted:

1. **A missing column is reported, never guessed at.** A runner that cannot see
   its inputs returns ``ran: False`` with the names it wanted. It never invents a
   number to keep a pipeline moving.
2. **Inconclusive is an answer.** ``supported`` may be ``None``; that means the
   data did not decide, which is different from deciding against.
3. **Nothing is random and nothing is expensive.** No sampling, no fitting, no
   hidden state: the same dataset always produces the same observed dict.

The thresholds below are declared constants, not tuned parameters. They are
deliberately crude and visible so a reader can disagree with them in one place.
"""

from __future__ import annotations

import csv
import io
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from ..core.experiment import RUNNERS as DECLARED_RUNNERS, Experiment

__all__ = [
    "Dataset", "NeedsColumns", "RUNNERS", "available", "run", "bindings",
    "CORRELATION_FLOOR", "VARIANCE_RATIO_SUPPORT", "VARIANCE_RATIO_REFUTE",
    "COVERAGE_GAP_SUPPORT", "DISCRIMINATION_MARGIN_FLOOR", "MIN_GROUPS",
]

#: Below this, a correlation is treated as no relationship at all.
CORRELATION_FLOOR = 0.10
#: Dispersion ratio at or above which groups are "materially different".
VARIANCE_RATIO_SUPPORT = 2.0
#: Dispersion ratio at or below which groups are "the same".
VARIANCE_RATIO_REFUTE = 1.2
#: Missing fraction at or above which a column has gaps big enough to explain a pattern.
COVERAGE_GAP_SUPPORT = 0.20
#: Separation margin below which two explanations cannot be told apart.
DISCRIMINATION_MARGIN_FLOOR = 0.10
#: Groups needed before a comparison across groups means anything.
MIN_GROUPS = 2

_TRUE_WORDS = {"1", "true", "yes", "y", "late", "failed", "sla_violated", "violated"}
_FALSE_WORDS = {"0", "false", "no", "n", "on_time", "ok", "delivered", "met"}


class NeedsColumns(Exception):
    """The runner cannot run because the data it was promised is absent."""


# --------------------------------------------------------------------------- #
# Dataset
# --------------------------------------------------------------------------- #

@dataclass
class Dataset:
    """An in-memory table of rows, plus declared column names.

    ``name`` is provenance: it becomes the source of every piece of evidence a
    run produces, so an unnamed dataset is refused rather than labelled later.
    """

    name: str
    rows: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not str(self.name).strip():
            raise ValueError("a dataset needs a name; it becomes the evidence source")
        self.rows = [dict(row) for row in self.rows]

    def keys(self) -> set[str]:
        found: set[str] = set()
        for row in self.rows:
            found |= {str(k) for k in row}
        return found

    def resolve(self, column: str) -> str:
        """The stored spelling of ``column``, so a caller's casing need not match."""
        wanted = str(column).lower()
        for key in sorted(self.keys()):
            if key.lower() == wanted:
                return key
        return str(column)

    def has(self, *columns: str) -> bool:
        known = {k.lower() for k in self.keys()}
        return all(str(c).lower() in known for c in columns)

    def column(self, name: str) -> list:
        key = self.resolve(name)
        return [row.get(key) for row in self.rows]

    def groups(self, key: str) -> dict[str, list[dict]]:
        resolved = self.resolve(key)
        out: dict[str, list[dict]] = {}
        for row in self.rows:
            if resolved not in row or row[resolved] is None:
                continue
            label = str(row[resolved])
            out.setdefault(label, []).append(row)
        return out

    @classmethod
    def from_csv_text(cls, text: str, *, name: str = "csv") -> "Dataset":
        """Header row plus values; numbers are coerced when they parse."""
        rows: list[dict] = []
        for raw in csv.DictReader(io.StringIO(text)):
            row: dict = {}
            for key, value in raw.items():
                if key is None:
                    continue
                row[str(key).strip()] = _coerce(value)
            rows.append(row)
        return cls(name=name, rows=rows)


def _coerce(value: object) -> object:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _flag(value: object) -> int | None:
    """A binary outcome as 0/1, or None when the value is not a binary outcome."""
    if isinstance(value, bool):
        return 1 if value else 0
    number = _number(value)
    if number is not None and number in (0.0, 1.0):
        return int(number)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_WORDS:
            return 1
        if lowered in _FALSE_WORDS:
            return 0
    return None


# --------------------------------------------------------------------------- #
# Small statistics, implemented here so no result comes from nowhere
# --------------------------------------------------------------------------- #

def _xy_pairs(rows: Iterable[Mapping], x: str, y: str) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for row in rows:
        first, second = _number(row.get(x)), _number(row.get(y))
        if first is not None and second is not None:
            out.append((first, second))
    return out


def _outcome_pairs(rows: Iterable[Mapping], column: str, outcome: str) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    for row in rows:
        value, flag = _number(row.get(column)), _flag(row.get(outcome))
        if value is not None and flag is not None:
            out.append((value, flag))
    return out


def _pearson(pairs: Sequence[tuple[float, float]]) -> float | None:
    if len(pairs) < 3:
        return None
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    mean_x, mean_y = statistics.fmean(xs), statistics.fmean(ys)
    dx = [v - mean_x for v in xs]
    dy = [v - mean_y for v in ys]
    cov = sum(a * b for a, b in zip(dx, dy))
    norm = (sum(a * a for a in dx) * sum(b * b for b in dy)) ** 0.5
    if norm == 0:
        return None
    return cov / norm


def _youden(pairs: Sequence[tuple[float, int]]) -> tuple[float, float | None, float, float, int]:
    """Best threshold separation for a numeric predictor of a binary outcome.

    Returns ``(youden_j, threshold, sensitivity, specificity, n)``. Youden's J is
    sensitivity + specificity - 1: 0 means the predictor carries no signal, 1
    means perfect separation. Ties go to the lowest threshold so the answer is
    deterministic.
    """
    if len(pairs) < 4:
        return 0.0, None, 0.0, 0.0, len(pairs)
    positives = sum(1 for _, flag in pairs if flag == 1)
    negatives = len(pairs) - positives
    if not positives or not negatives:
        return 0.0, None, 0.0, 0.0, len(pairs)
    best = (0.0, None, 0.0, 0.0, len(pairs))
    for threshold in sorted({value for value, _ in pairs}):
        tp = sum(1 for value, flag in pairs if value >= threshold and flag == 1)
        fn = positives - tp
        fp = sum(1 for value, flag in pairs if value >= threshold and flag == 0)
        tn = negatives - fp
        sens = tp / positives
        spec = tn / negatives
        j = sens + spec - 1.0
        if best[1] is None or j > best[0] + 1e-12:
            best = (j, threshold, sens, spec, len(pairs))
    return best


def _sign(value: float | None, floor: float) -> int:
    if value is None or abs(value) < floor:
        return 0
    return 1 if value > 0 else -1


def _result(**fields) -> dict:
    """Every runner returns through here, so ``supported``/``refuted`` are never
    absent from an observed dict and never non-JSON types."""
    fields.setdefault("supported", None)
    fields.setdefault("refuted", False)
    for key, value in list(fields.items()):
        if isinstance(value, float) and (value != value or value in (float("inf"), float("-inf"))):
            raise ValueError(f"runner produced a non-finite value for {key!r}; that is not a result")
    return fields


# --------------------------------------------------------------------------- #
# Argument binding
# --------------------------------------------------------------------------- #

def bindings(experiment: Experiment) -> dict[str, str]:
    """Parse ``role=value`` entries out of ``required_data``.

    A repeated role is an error rather than a silent last-one-wins: the planner
    binds ``columns=a,b,c`` precisely so a list cannot lose its members here.
    """
    out: dict[str, str] = {}
    for item in experiment.required_data:
        text = str(item)
        if "=" not in text:
            continue
        role, _, value = text.partition("=")
        role = role.strip()
        if role in out:
            raise NeedsColumns(
                f"role {role!r} is bound twice in required_data ({out[role]!r} and {value!r}); "
                "use a comma list for multi-valued roles"
            )
        out[role] = value.strip()
    return out


def _binding_list(bound: Mapping[str, str], role: str) -> list[str]:
    return [part.strip() for part in str(bound.get(role, "")).split(",") if part.strip()]


def _need(dataset: Dataset, bound: Mapping[str, str], role: str) -> str:
    column = bound.get(role)
    if not column:
        raise NeedsColumns(f"needs {role}=<column> in required_data")
    if not dataset.has(column):
        raise NeedsColumns(
            f"needs columns: {column} (role {role!r}); dataset {dataset.name!r} has {sorted(dataset.keys())}"
        )
    return dataset.resolve(column)


# --------------------------------------------------------------------------- #
# The seven runners
# --------------------------------------------------------------------------- #

def precursor_detection(experiment: Experiment, dataset: Dataset) -> dict:
    """Does a measurable precursor precede the outcome, by at least N hours?

    Scans every distinct precursor value as a threshold and keeps the one with the
    best separation. When a time column is bound it also reports the median hours
    between the precursor crossing and the outcome; without one it reports no lead
    time rather than manufacturing one from row order.
    """
    bound = bindings(experiment)
    precursor = _need(dataset, bound, "precursor")
    outcome = _need(dataset, bound, "outcome")
    time_column = dataset.resolve(bound["time"]) if bound.get("time") and dataset.has(bound["time"]) else None
    minimum_hours = float(bound.get("min_hours", 6) or 6)

    rows: list[tuple[float, int, float]] = []
    for index, row in enumerate(dataset.rows):
        value, flag = _number(row.get(precursor)), _flag(row.get(outcome))
        if value is None or flag is None:
            continue
        when = _number(row.get(time_column)) if time_column else float(index)
        if when is None:
            continue
        rows.append((value, flag, when))
    if len(rows) < 4:
        raise NeedsColumns(
            f"needs at least 4 complete rows of {precursor!r} and {outcome!r}; got {len(rows)}"
        )
    if not any(flag == 1 for _, flag, _ in rows):
        raise NeedsColumns(f"{outcome!r} has no positive rows, so nothing can be predicted")

    separation, threshold, sensitivity, specificity, n = _youden([(v, f) for v, f, _ in rows])
    lead_hours: float | None = None
    if threshold is not None and time_column:
        leads: list[float] = []
        earlier = sorted(rows, key=lambda r: r[2])
        first_positive = next((i for i, r in enumerate(earlier) if r[1] == 1), None)
        if first_positive is not None:
            crossing = next(
                (earlier[i][2] for i in range(first_positive - 1, -1, -1) if earlier[i][0] >= threshold),
                None,
            )
            if crossing is not None:
                leads.append(earlier[first_positive][2] - crossing)
        lead_hours = statistics.median(leads) if leads else None

    # A declared lead time that could not be measured must never be treated as met.
    # This used to read ``lead_hours is None or lead_hours >= minimum_hours``, which
    # reported SUPPORTED for a test whose decisive quantity was never computed --
    # the exact failure mode this apparatus exists to catch, sitting in the runner
    # itself. An unmeasurable lead is INCONCLUSIVE, and a measured short lead is a
    # refutation of the claim being made.
    if separation <= 0:
        supported: bool | None = False
        refuted = True
    elif time_column and lead_hours is None:
        supported = None
        refuted = False
    elif time_column and lead_hours < minimum_hours:
        supported = False
        refuted = True
    else:
        supported = True
        refuted = False
    return _result(
        precursor=precursor,
        threshold=threshold,
        separation=round(separation, 4),
        sensitivity=round(sensitivity, 4),
        specificity=round(specificity, 4),
        lead_hours=None if lead_hours is None else round(lead_hours, 3),
        min_hours=minimum_hours,
        lead_column=time_column,
        lead_measured=lead_hours is not None,
        n=n,
        supported=supported,
        refuted=refuted,
    )


def discrimination_scan(experiment: Experiment, dataset: Dataset) -> dict:
    """Which of several candidate explanations does the data best support?

    One run, many candidates. Reports the full ranking and the margin over the
    runner-up, because a winner decided by less than
    ``DISCRIMINATION_MARGIN_FLOOR`` is not a decision.

    Every candidate also carries **the cut that produced its separation**
    (``op``/``threshold``/``sensitivity``/``specificity``). That cut used to be
    computed and then discarded, which meant the engine could rank explanations but
    could never turn a ranking into a rule -- the one measurement it makes about
    *which* column explains the outcome was untranslatable, so the builder fell
    through to a detector-less artifact even when the scan had decided.

    When the scan **does** decide it reports the rule it decided on under
    ``detector``, so a consumer reads a decision rather than reconstructing one from
    the ranking. When it does not, it reports ``contenders``: the candidates within
    the margin floor of the best. A refusal that names no alternatives is
    indistinguishable from finding no candidates at all.

    ``_youden`` measures one direction (``value >= threshold``), so the reported
    operator is the direction the separation was actually measured in rather than an
    inferred one.
    """
    bound = bindings(experiment)
    outcome = _need(dataset, bound, "outcome")
    wanted = _binding_list(bound, "candidates")
    if not wanted:
        raise NeedsColumns("needs candidates=<comma separated columns> in required_data")
    # The outcome column is not a candidate explanation for itself. Scoring it
    # against itself is a tautology, and it wins every time -- this runner used to
    # rank the outcome first, which is exactly the defect a discriminating test is
    # supposed to catch. Excluded, and reported as excluded rather than dropped.
    resolved_outcome = dataset.resolve(outcome)
    excluded = [c for c in wanted if dataset.resolve(c) == resolved_outcome]
    present = [c for c in wanted if dataset.has(c) and dataset.resolve(c) != resolved_outcome]
    if not present:
        raise NeedsColumns(
            f"needs columns: {', '.join(wanted)} (excluding the outcome {resolved_outcome!r}); "
            f"dataset {dataset.name!r} has {sorted(dataset.keys())}"
        )

    ranking: list[dict] = []
    for column in present:
        pairs = _outcome_pairs(dataset.rows, dataset.resolve(column), outcome)
        separation, threshold, sensitivity, specificity, count = _youden(pairs)
        entry = {"column": column, "separation": round(separation, 4), "n": count}
        if count < 4:
            entry["note"] = "too few complete rows to separate"
        else:
            entry["op"] = ">="
            entry["threshold"] = None if threshold is None else round(threshold, 4)
            entry["sensitivity"] = round(sensitivity, 4)
            entry["specificity"] = round(specificity, 4)
        ranking.append(entry)
    ranking.sort(key=lambda item: (-abs(item["separation"]), item["column"]))

    best = ranking[0]
    runner_up = ranking[1] if len(ranking) > 1 else None
    margin = abs(best["separation"]) - (abs(runner_up["separation"]) if runner_up else 0.0)
    decides = abs(best["separation"]) > CORRELATION_FLOOR and margin >= DISCRIMINATION_MARGIN_FLOOR
    # The measurement as a rule, whether or not the scan was entitled to name it. A
    # candidate with no threshold separated nothing, so there is no rule to report.
    detector = (
        {"field": best["column"], "op": best["op"], "threshold": best["threshold"]}
        if decides and best.get("threshold") is not None
        else None
    )
    contenders = [] if decides else [
        {"column": row["column"], "separation": row["separation"],
         "op": row.get("op"), "threshold": row.get("threshold")}
        for row in ranking[1:]
        if row.get("threshold") is not None
        and abs(best["separation"]) - abs(row["separation"]) < DISCRIMINATION_MARGIN_FLOOR
    ]
    return _result(
        ranking=ranking,
        excluded_circular=excluded,
        favours=best["column"] if decides else None,
        decided=decides,
        detector=detector,
        contenders=contenders,
        best_separation=abs(best["separation"]),
        margin=round(margin, 4),
        runner_up=runner_up["column"] if runner_up else None,
        candidates_tested=len(ranking),
        supported=True if decides else None,
        refuted=bool(abs(best["separation"]) <= CORRELATION_FLOOR),
    )


def aggregation_check(experiment: Experiment, dataset: Dataset) -> dict:
    """Is the apparent relationship an artifact of pooling the groups?

    Supported when the pooled correlation reverses sign inside at least one group
    while remaining above the floor: the relationship exists only in the
    aggregate, which is Simpson's paradox and is usually a measurement artefact.
    """
    bound = bindings(experiment)
    x = _need(dataset, bound, "x")
    y = _need(dataset, bound, "y")
    group = _need(dataset, bound, "group")

    pooled = _pearson(_xy_pairs(dataset.rows, x, y))
    if pooled is None:
        raise NeedsColumns(f"needs at least 3 complete numeric rows of {x!r} and {y!r}")
    per_group = {
        label: (None if (r := _pearson(_xy_pairs(rows, x, y))) is None else round(r, 4))
        for label, rows in dataset.groups(group).items()
    }
    defined = {k: v for k, v in per_group.items() if v is not None}
    if len(defined) < MIN_GROUPS:
        raise NeedsColumns(
            f"needs at least {MIN_GROUPS} groups of {group!r} with 3+ complete numeric rows; got {len(defined)}"
        )

    pooled_sign = _sign(pooled, CORRELATION_FLOOR)
    flips = sorted(k for k, v in defined.items() if pooled_sign != 0 and _sign(v, CORRELATION_FLOOR) == -pooled_sign)
    same = all(_sign(v, CORRELATION_FLOOR) == pooled_sign for v in defined.values())
    return _result(
        pooled_correlation=round(pooled, 4),
        pooled_sign=pooled_sign,
        per_group=per_group,
        flips=flips,
        groups=len(defined),
        supported=bool(flips and abs(pooled) >= CORRELATION_FLOOR),
        refuted=bool(not flips and same and abs(pooled) >= CORRELATION_FLOOR),
    )


def correlation_split(experiment: Experiment, dataset: Dataset) -> dict:
    """Does the relationship between x and y hold inside every group, or only some?

    Supported when the sign of the relationship is not the same in every group;
    refuted when every group agrees on a non-trivial sign.
    """
    bound = bindings(experiment)
    x = _need(dataset, bound, "x")
    y = _need(dataset, bound, "y")
    group = _need(dataset, bound, "group")

    per_group = {
        label: (None if (r := _pearson(_xy_pairs(rows, x, y))) is None else round(r, 4))
        for label, rows in dataset.groups(group).items()
    }
    defined = {k: v for k, v in per_group.items() if v is not None}
    if len(defined) < MIN_GROUPS:
        raise NeedsColumns(
            f"needs at least {MIN_GROUPS} groups of {group!r} with 3+ complete numeric rows; got {len(defined)}"
        )
    signs = {_sign(v, CORRELATION_FLOOR) for v in defined.values()}
    strong = {label: value for label, value in defined.items() if abs(value) >= CORRELATION_FLOOR}
    return _result(
        per_group=per_group,
        signs=sorted(signs),
        groups=len(defined),
        strong_groups=sorted(strong),
        supported=len(signs) > 1,
        refuted=bool(len(signs) == 1 and 0 not in signs and len(strong) == len(defined)),
    )


def variance_compare(experiment: Experiment, dataset: Dataset) -> dict:
    """Do the groups have materially different dispersion?

    Compares the widest and narrowest group spread. A ratio at or above
    ``VARIANCE_RATIO_SUPPORT`` is a difference; at or below
    ``VARIANCE_RATIO_REFUTE`` it is not. A zero-variance group makes the ratio
    undefined, and reported as such rather than as a very large number.
    """
    bound = bindings(experiment)
    value_column = _need(dataset, bound, "value")
    group = _need(dataset, bound, "group")

    per_group: dict[str, dict] = {}
    spreads: dict[str, float] = {}
    for label, rows in dataset.groups(group).items():
        values = [v for v in (_number(row.get(value_column)) for row in rows) if v is not None]
        if len(values) < 2:
            continue
        spread = statistics.stdev(values)
        spreads[label] = spread
        per_group[label] = {
            "n": len(values),
            "mean": round(statistics.fmean(values), 4),
            "stdev": round(spread, 4),
        }
    if len(spreads) < MIN_GROUPS:
        raise NeedsColumns(
            f"needs at least {MIN_GROUPS} groups of {group!r} with 2+ numeric rows of "
            f"{value_column!r}; got {len(spreads)}"
        )

    low, high = min(spreads.values()), max(spreads.values())
    if low > 0:
        ratio: float | None = high / low
        note = ""
    elif high > 0:
        ratio, note = None, "a group has zero variance, so the ratio is undefined"
    else:
        ratio, note = 1.0, "every group has zero variance"
    return _result(
        per_group=per_group,
        widest=max(spreads, key=lambda k: (spreads[k], k)),
        narrowest=min(spreads, key=lambda k: (spreads[k], k)),
        ratio=None if ratio is None else round(ratio, 4),
        note=note,
        supported=True if (ratio is None and high > 0) else (None if ratio is None else ratio >= VARIANCE_RATIO_SUPPORT),
        refuted=False if ratio is None else ratio <= VARIANCE_RATIO_REFUTE,
    )


def coverage_scan(experiment: Experiment, dataset: Dataset) -> dict:
    """Do any series have gaps big enough to explain an apparent pattern?

    Reported per column: missing count and fraction, and the longest consecutive
    run of missing values. Supported when some column clears
    ``COVERAGE_GAP_SUPPORT``, because an apparent pattern can then be produced by
    when the data was recorded rather than by what happened.
    """
    bound = bindings(experiment)
    wanted = _binding_list(bound, "columns") or sorted(dataset.keys())
    present = [c for c in wanted if dataset.has(c)]
    if not present:
        raise NeedsColumns(f"needs columns: {', '.join(wanted)}; dataset {dataset.name!r} has {sorted(dataset.keys())}")
    if not dataset.rows:
        raise NeedsColumns("needs at least one row")

    report: dict[str, dict] = {}
    for column in present:
        values = dataset.column(dataset.resolve(column))
        missing = sum(1 for v in values if v is None)
        longest = run = 0
        for value in values:
            run = run + 1 if value is None else 0
            longest = max(longest, run)
        report[column] = {
            "rows": len(values),
            "missing": missing,
            "missing_fraction": round(missing / len(values), 4) if values else 0.0,
            "longest_gap": longest,
        }
    worst = max(report.items(), key=lambda item: (item[1]["missing_fraction"], item[0]))
    return _result(
        per_column=report,
        worst_column=worst[0],
        worst_missing_fraction=worst[1]["missing_fraction"],
        supported=any(entry["missing_fraction"] >= COVERAGE_GAP_SUPPORT for entry in report.values()),
        refuted=all(entry["missing_fraction"] < COVERAGE_GAP_SUPPORT for entry in report.values()),
    )


def counterfactual_replay(experiment: Experiment, dataset: Dataset) -> dict:
    """If the rule had fired, would it have fired on the failures?

    Applies ``field op threshold`` to every complete row and compares the outcome
    rate in the flagged rows against the unflagged ones. Supported when the rule
    lands on the bad rows more often than on the good ones; that is the weakest
    possible evidence for an intervention and it says so.

    The rule it reports is a **probe**, and it is reported under ``probe_rule`` with
    ``probe: True`` for that reason. The field and threshold are not measured here --
    they were declared by whoever planned the test, before any data was seen. This
    runner answers "what would that hypothetical rule have done", which is a real
    question, and its answer is not a measurement of where the threshold belongs.
    Reporting it under a key the builder reads as a measured rule let a data-blind
    placeholder (``threshold=24``) become the shipped artifact's detector, which is
    why the key is named for what it is. See ``docs/D1-failure-to-leverage.md``,
    entry ``qse-d1-0004``.
    """
    bound = bindings(experiment)
    field_column = _need(dataset, bound, "field")
    outcome = _need(dataset, bound, "outcome")
    operation = bound.get("op", ">=")
    if operation not in (">=", "<="):
        raise NeedsColumns(f"op must be '>=' or '<=', got {operation!r}")
    try:
        threshold = float(bound.get("threshold", 24) or 24)
    except ValueError as exc:
        raise NeedsColumns(f"threshold must be numeric, got {bound.get('threshold')!r}") from exc

    fired: list[int] = []
    quiet: list[int] = []
    for row in dataset.rows:
        value, flag = _number(row.get(field_column)), _flag(row.get(outcome))
        if value is None or flag is None:
            continue
        hit = value >= threshold if operation == ">=" else value <= threshold
        (fired if hit else quiet).append(flag)
    if not fired or not quiet:
        raise NeedsColumns(
            f"needs rows on both sides of {field_column} {operation} {threshold}; "
            f"got {len(fired)} flagged and {len(quiet)} not"
        )

    rate_fired = sum(fired) / len(fired)
    rate_quiet = sum(quiet) / len(quiet)
    return _result(
        probe=True,
        probe_rule=f"{field_column} {operation} {threshold}",
        flagged=len(fired),
        unflagged=len(quiet),
        outcome_rate_flagged=round(rate_fired, 4),
        outcome_rate_unflagged=round(rate_quiet, 4),
        improvable_outcomes=sum(fired),
        lift=round(rate_fired - rate_quiet, 4),
        supported=bool(rate_fired > rate_quiet),
        refuted=bool(rate_fired <= rate_quiet),
    )


RUNNERS: dict[str, object] = {
    "precursor_detection": precursor_detection,
    "discrimination_scan": discrimination_scan,
    "aggregation_check": aggregation_check,
    "correlation_split": correlation_split,
    "variance_compare": variance_compare,
    "coverage_scan": coverage_scan,
    "counterfactual_replay": counterfactual_replay,
}


def available() -> tuple[str, ...]:
    """The runners that exist, in the order the core type declares them."""
    return DECLARED_RUNNERS


def run(experiment: Experiment, dataset: Dataset) -> dict:
    """Run one experiment. Never raises for a data problem; reports it instead."""
    blank = {
        "xid": experiment.xid,
        "runner": experiment.runner,
        "ran": False,
        "reason": "",
        "observed": None,
        "supported": None,
        "refuted": False,
    }
    if not isinstance(dataset, Dataset):
        return {**blank, "reason": f"expected a Dataset, got {type(dataset).__name__}"}
    if experiment.runner is None:
        return {**blank, "reason": "experiment names no runner, so it cannot be executed"}
    runner = RUNNERS.get(experiment.runner)
    if runner is None:
        return {**blank, "reason": f"unknown runner {experiment.runner!r}; available: {sorted(RUNNERS)}"}
    try:
        observed = runner(experiment, dataset)  # type: ignore[operator]
    except NeedsColumns as exc:
        return {**blank, "reason": str(exc)}
    return {
        "xid": experiment.xid,
        "runner": experiment.runner,
        "ran": True,
        "reason": "",
        "observed": observed,
        "supported": observed.get("supported"),
        "refuted": bool(observed.get("refuted", False)),
    }
