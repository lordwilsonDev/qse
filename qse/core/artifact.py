"""Artifacts, and the ladder they climb.

``PROPOSED -> CONSTRUCTED -> ATTACKED -> VERIFIED`` (or ``REJECTED``).

The ladder is enforced by ``qse/verification/verifier.py``; this module only
holds the shape and lets a state be read. An artifact that reaches ``VERIFIED``
must carry the attack ids that did not kill it and the verification ids that
were performed by somebody other than its builder.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from ..ids import new_id

KINDS = ("SPEC", "CODE", "DATA", "PROCESS", "DECISION_RULE")
ARTIFACT_KINDS = KINDS

STATES = ("PROPOSED", "CONSTRUCTED", "ATTACKED", "VERIFIED", "REJECTED")
ARTIFACT_STATES = STATES

_RANK = {name: i for i, name in enumerate(STATES[:4])}


@dataclass
class Artifact:
    aid: str
    hypothesis: str
    kind: str
    title: str
    builder: str
    content: str = ""
    path: str | None = None
    reproduce: str | None = None
    state: str = "PROPOSED"
    attacks: list[str] = field(default_factory=list)
    verifications: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    requires: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown artifact kind {self.kind!r}; choose from {KINDS}")
        if self.state not in STATES:
            raise ValueError(f"unknown artifact state {self.state!r}; choose from {STATES}")
        if not self.title.strip():
            raise ValueError("an artifact needs a title")

    def rank(self) -> int:
        return _RANK.get(self.state, -1)

    def constructed(self) -> bool:
        return self.rank() >= _RANK["CONSTRUCTED"]

    def attacked(self) -> bool:
        return bool(self.attacks) and self.rank() >= _RANK["ATTACKED"]

    def verified(self) -> bool:
        return self.state == "VERIFIED" and bool(self.verifications)

    def executable(self) -> bool:
        """Whether the artifact is something a machine can actually run."""
        return self.kind in ("CODE", "PROCESS", "DECISION_RULE") and bool((self.reproduce or "").strip())

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["requires"] = list(self.requires)
        out["constructed"] = self.constructed()
        out["executable"] = self.executable()
        return out

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Artifact":
        return cls(
            aid=str(payload["aid"]),
            hypothesis=str(payload.get("hypothesis", "")),
            kind=str(payload["kind"]),
            title=str(payload["title"]),
            builder=str(payload.get("builder", "unknown")),
            content=str(payload.get("content", "")),
            path=payload.get("path"),
            reproduce=payload.get("reproduce"),
            state=str(payload.get("state", "PROPOSED")),
            attacks=[str(a) for a in payload.get("attacks", ())],
            verifications=[str(v) for v in payload.get("verifications", ())],
            evidence=[str(e) for e in payload.get("evidence", ())],
            requires=tuple(str(r) for r in payload.get("requires", ())),
        )


def make_artifact(
    *,
    hypothesis: str,
    kind: str,
    title: str,
    builder: str,
    content: str = "",
    path: str | None = None,
    reproduce: str | None = None,
    requires: tuple[str, ...] = (),
) -> Artifact:
    aid = new_id("ART", hypothesis, kind, title)
    return Artifact(
        aid=aid,
        hypothesis=hypothesis,
        kind=kind,
        title=title,
        builder=builder,
        content=content,
        path=path,
        reproduce=reproduce,
        requires=requires,
    )
