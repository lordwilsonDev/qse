"""Build conversion: proposed artifacts versus executable ones.

``BC = executable_artifacts / proposed_artifacts``.

"Executable" is deliberately narrower than "verified": a MARKDOWN recommendation
that a human agrees with is not something a machine can run. It has to be a
CODE, PROCESS or DECISION_RULE artifact, it has to have survived to VERIFIED,
and it has to carry the command that regenerates it.
"""

from __future__ import annotations

from typing import Any

from ..control.state import State
from .question_quality import measure, ratio

__all__ = ["EXECUTABLE_KINDS", "build_quality"]

EXECUTABLE_KINDS = ("CODE", "PROCESS", "DECISION_RULE")


def _is_executable(record: dict[str, Any]) -> bool:
    return (
        str(record.get("state", "")) == "VERIFIED"
        and str(record.get("kind", "")) in EXECUTABLE_KINDS
        and bool(str(record.get("reproduce") or "").strip())
    )


def build_quality(state: State) -> dict[str, Any]:
    proposed = sorted(state.artifacts)
    executable = sorted(aid for aid, rec in state.artifacts.items() if _is_executable(rec))
    unexecutable = [aid for aid in proposed if aid not in executable]

    states: dict[str, int] = {}
    for rec in state.artifacts.values():
        key = str(rec.get("state", "PROPOSED"))
        states[key] = states.get(key, 0) + 1

    return measure(
        ratio(len(executable), len(proposed)),
        len(executable),
        len(proposed),
        "executable_artifacts / proposed_artifacts",
        states=states,
        executable=executable,
        unexecutable=unexecutable,
        kinds={aid: str(state.artifacts[aid].get("kind", "")) for aid in proposed},
    )
