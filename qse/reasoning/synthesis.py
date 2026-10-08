"""Synthesis: choosing between explanations without counting votes.

This is the module where the moonshot's claim is falsifiable. If selection were a
head-count, a minority explanation could never win, and the whole "no majority
vote" line would be a slogan. So selection takes *only* hypotheses and evidence,
and the one route by which a tally could arrive — an optional ``holders``
argument — is wired into ``policy.forbid_majority_vote`` before anything else
runs.

Weight comes from ``Evidence.weight()``, which is zero for anything the firewall
rejects. A MODEL_PROPOSAL cannot move a score, and neither can eleven of them.

What is real: the arithmetic, the firewall, and the refusal. What is not
calibrated: the strength values (WEAK/MODERATE/STRONG -> 1/2/3) are an ordinal
scale chosen for legibility, not a probability. The module says so rather than
implying a confidence it does not have.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from ..control.policy import forbid_majority_vote
from ..core.evidence import Evidence
from ..core.hypothesis import Hypothesis

#: Deliberately not a probability. Ordinal only.
SCALE_NOTE = "strength is ordinal (WEAK=1, MODERATE=2, STRONG=3), not a calibrated probability"


def weigh(hypotheses: Iterable[Hypothesis], evidence: Iterable[Evidence]) -> list[dict[str, Any]]:
    """Per-hypothesis support and contradiction from usable evidence alone."""
    evidence = list(evidence)
    rows: list[dict[str, Any]] = []
    for hypothesis in hypotheses:
        mine = [e for e in evidence if e.hypothesis == hypothesis.hid]
        usable = [e for e in mine if e.usable()]
        unusable = [e for e in mine if not e.usable()]
        support = sum(e.weight() for e in usable if e.supports)
        contradiction = sum(e.weight() for e in usable if not e.supports)
        rows.append(
            {
                "hid": hypothesis.hid,
                "text": hypothesis.text,
                "support": round(support, 6),
                "contradiction": round(contradiction, 6),
                "net": round(support - contradiction, 6),
                "usable": len(usable),
                "unusable": len(unusable),
                "for": sorted(e.eid for e in usable if e.supports),
                "against": sorted(e.eid for e in usable if not e.supports),
                "excluded": sorted(e.eid for e in unusable),
            }
        )
    return rows


def select(
    hypotheses: Sequence[Hypothesis],
    evidence: Iterable[Evidence],
    *,
    holders: Mapping[str, int] | None = None,
    minimum_evidence: int = 1,
) -> dict[str, Any]:
    """Pick the explanation the evidence best supports. Never by head-count.

    ``holders`` exists only so that a caller reaching for a vote is *refused*
    with rule R-SYN-1 rather than quietly getting vote-based selection. Passing
    None is the normal path.
    """
    if holders:
        forbid_majority_vote(holders, sum(holders.values()))

    table = weigh(hypotheses, evidence)
    eligible = [row for row in table if row["usable"] >= minimum_evidence]
    ranked = sorted(eligible, key=lambda row: (-row["net"], row["hid"]))

    if not ranked:
        return {
            "winner": None,
            "runner_up": None,
            "net": None,
            "margin": None,
            "minority_wins": False,
            "table": table,
            "insufficient": True,
            "minimum_evidence": minimum_evidence,
            "why": (
                f"no hypothesis met the minimum of {minimum_evidence} usable observation(s); "
                "QSE does not select on an empty evidence base"
            ),
            "scale": SCALE_NOTE,
            "vote": None,
        }

    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = None if runner_up is None else round(winner["net"] - runner_up["net"], 6)

    # Strength beating count is the case that matters: the minority explanation
    # wins because its evidence is stronger, not because it is more popular.
    minority_wins = bool(
        runner_up is not None
        and winner["net"] > runner_up["net"]
        and winner["usable"] < runner_up["usable"]
    )

    if runner_up is None:
        why = f"only {winner['hid']} met the evidence bar, so there was nothing to choose between"
    elif minority_wins:
        why = (
            f"{winner['hid']} wins on {winner['usable']} usable observation(s) against "
            f"{runner_up['usable']} for {runner_up['hid']}: fewer observations, stronger ones"
        )
    else:
        why = (
            f"{winner['hid']} has the highest net support ({winner['net']}) "
            f"against {runner_up['net']} for {runner_up['hid']}"
        )

    return {
        "winner": winner["hid"],
        "runner_up": None if runner_up is None else runner_up["hid"],
        "net": winner["net"],
        "margin": margin,
        "minority_wins": minority_wins,
        "table": table,
        "insufficient": False,
        "minimum_evidence": minimum_evidence,
        "why": why,
        "scale": SCALE_NOTE,
        "vote": None,
    }
