"""Shared fixtures. Kept small and explicit so a test's inputs are visible in it."""

from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..ids import freeze
from ..core.evidence import make_evidence

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"

FORTUNE = (
    "Can we predict operational bottlenecks at Fortune 500 companies before they "
    "become expensive failures?"
)


def pin_clock(moment: str = "2026-10-07T12:00:00Z") -> None:
    """Pin time so a run is reproducible. Every test class does this in setUp."""
    freeze(datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone(timezone.utc))


class Workspace:
    """A temporary directory that cleans itself up."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="qse-test-"))

    def file(self, name: str) -> Path:
        return self.path / name

    def ledger(self, name: str = "ledger.jsonl") -> str:
        return str(self.path / name)

    def close(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def scenario_payload(name: str = "orders_scenario.json") -> dict:
    with (EXAMPLES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def rows_of(name: str = "orders_scenario.json") -> list[dict]:
    return scenario_payload(name)["rows"]


def facts_of(name: str = "orders_scenario.json") -> dict:
    return scenario_payload(name)["facts"]


def strong_evidence(hypothesis: str, *, source: str = "orders.csv", supports: bool = True):
    """Usable, MEASURED, with provenance -- the only kind that may move a score."""
    return make_evidence(
        "handoffs predict the breach",
        hypothesis=hypothesis,
        kind="MEASURED",
        source=source,
        method="pearson correlation on complete pairs",
        collected_at="2026-10-07T12:00:00Z",
        observed={"field": "handoffs", "threshold": 5, "statistic": 0.71, "n": 516},
        supports=supports,
        strength="STRONG",
    )


def model_proposal(hypothesis: str):
    """A model proposal: recorded, displayed, and never counted."""
    return make_evidence(
        "the model thinks latency is the cause",
        hypothesis=hypothesis,
        kind="MODEL_PROPOSAL",
        source="qse-llm",
        method="sampling",
        collected_at="2026-10-07T12:00:00Z",
    )
