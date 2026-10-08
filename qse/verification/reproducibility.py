"""Reproducibility: run it again and see whether the same thing comes out.

What is actually being compared matters. Two hashes are kept and they answer
different questions:

* ``expected_hash`` -- sha256 of the artifact's **source**. "Is this the same
  artifact?" A change here means the thing was edited, which invalidates any
  verification performed against the earlier bytes.
* ``observed_hash`` -- sha256 of the **stdout of the run**. "Does it do the same
  thing?" A change here with an unchanged source means the artifact is not
  deterministic, which is a defect in the artifact and not in this module.

``ok`` is never true for a run that did not happen. That is the whole point of
the gate rule this feeds: a green test in one process, reported by the process
that wrote the code, is not reproducibility.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import Any, Callable, Mapping

from ..core.artifact import Artifact
from ..ids import new_id

#: Runners return this shape; the default is qse.build.executor.execute.
RunResult = Mapping[str, Any]


@dataclass
class Reproduction:
    rid: str
    artifact: str
    command: str
    ran: bool
    ok: bool
    observed_hash: str
    expected_hash: str
    detail: str
    stdout: str = ""
    exit: int | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["stdout"] = self.stdout[:2000]
        return out


def content_hash(artifact: Artifact) -> str:
    """sha256 of the artifact's source text. Identifies the artifact, not its output."""
    return hashlib.sha256((artifact.content or "").encode("utf-8")).hexdigest()


def output_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _default_execute(artifact: Artifact, **_kwargs: Any) -> RunResult:
    """Import the build executor at call time.

    A module-level import would make this verification module unimportable
    whenever the build package is unavailable, so a defect in the thing being
    verified would take down the verifier with it. That is the arrangement this
    whole package exists to avoid.
    """
    from ..build.executor import execute  # noqa: PLC0415 - deliberate, see docstring

    return execute(artifact)


def check(
    artifact: Artifact,
    *,
    execute: Callable[..., RunResult] | None = None,
    expected_hash: str | None = None,
    expected_output_hash: str | None = None,
) -> Reproduction:
    """Execute the artifact once and record whether the run is usable.

    ``expected_hash`` names the **source** hash the run is being compared
    against. When it is omitted this call is the first run and it establishes
    the reference; ``ok`` then means only "it ran and exited cleanly", which is
    weaker, and the returned ``detail`` says so.

    ``expected_output_hash`` names the **stdout** hash from an earlier run. Supply
    it and ``ok`` additionally requires byte-identical output, which is what
    "reproducible" is supposed to mean. Without it, a reproduction only proves
    the source did not change -- a much weaker claim, so say so when reporting.
    """
    runner = execute or _default_execute
    rid = new_id("REP", artifact.aid, expected_hash or "first", str(artifact.reproduce or ""))
    command = str(artifact.reproduce or "")
    source = content_hash(artifact)

    if expected_hash is not None and expected_hash != source:
        return Reproduction(
            rid=rid, artifact=artifact.aid, command=command, ran=False, ok=False,
            observed_hash="", expected_hash=expected_hash,
            detail=(
                "the artifact's source changed since it was verified "
                f"({source[:12]} != {expected_hash[:12]}); the earlier verification "
                "does not cover these bytes"
            ),
        )

    if not (artifact.content or "").strip():
        return Reproduction(
            rid=rid, artifact=artifact.aid, command=command, ran=False, ok=False,
            observed_hash="", expected_hash=source,
            detail="the artifact has no content, so there is nothing to reproduce",
        )

    try:
        result = runner(artifact)
    except Exception as exc:  # a runner that raises is a failed reproduction, not a crash
        return Reproduction(
            rid=rid, artifact=artifact.aid, command=command, ran=False, ok=False,
            observed_hash="", expected_hash=source,
            detail=f"the runner raised {type(exc).__name__}: {exc}",
        )

    result = result or {}
    ran = bool(result.get("ran"))
    if not ran:
        return Reproduction(
            rid=rid, artifact=artifact.aid, command=command, ran=False, ok=False,
            observed_hash="", expected_hash=source,
            detail=str(result.get("reason") or "the artifact did not run"),
            stdout=str(result.get("stdout", "")),
            exit=result.get("exit"),
        )

    stdout = str(result.get("stdout", ""))
    observed = output_hash(stdout)
    clean = result.get("ok") is True
    if expected_hash is None:
        ok = clean
        detail = (
            "first run established the reference source hash"
            if clean else "the run did not exit cleanly, so it cannot be a reference"
        )
    else:
        ok = clean
        detail = "the same source ran again and exited cleanly" if clean else "the rerun failed"
        if expected_output_hash is not None:
            if observed != expected_output_hash:
                ok = False
                detail = (
                    "the artifact ran twice and produced different output "
                    f"({observed[:12]} != {expected_output_hash[:12]}); it does not reproduce"
                )
            elif clean:
                detail = "the artifact ran twice on the same source with identical output"
    return Reproduction(
        rid=rid, artifact=artifact.aid, command=command, ran=True, ok=ok,
        observed_hash=observed, expected_hash=source, detail=detail,
        stdout=stdout, exit=result.get("exit"),
    )


def record(reproductions: Any) -> dict[str, Any]:
    """Summarise a set of reproductions. ``rate`` is None when nothing was run.

    None rather than 0.0: "we never tried" and "we tried and it failed" are
    different facts, and a rate that renders them identically is a rate that
    will eventually be quoted as a success.
    """
    items = [r for r in (reproductions or ()) if r is not None]
    ran = [r for r in items if getattr(r, "ran", False)]
    ok = [r for r in ran if getattr(r, "ok", False)]
    return {
        "n": len(items),
        "ran": len(ran),
        "rate": (len(ok) / len(items)) if items else None,
        "reproduced": sorted(r.rid for r in ok),
        "failed": sorted(r.rid for r in ran if not r.ok),
        "unrun": sorted(r.rid for r in items if not r.ran),
    }
