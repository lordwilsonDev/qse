"""Running a generated artifact, so "it works" is an observation.

The artifact is written to a fresh temporary directory and run as a separate
process with ``sys.executable``: no shell, no network, a timeout, and the
directory removed afterwards. Everything the caller is told comes from that
process's exit code and stdout -- none of it is inferred from the fact that a
file was written.

A timeout, a crash and a non-JSON stdout are three different answers and are
reported as three different answers.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from ..core.artifact import Artifact
from ..ids import slug

__all__ = ["DEFAULT_TIMEOUT", "execute", "reproduce_command"]

DEFAULT_TIMEOUT = 20.0

#: Kept short: a report is not a log dump, and the first lines carry the error.
_KEEP = 4000


def _blank(reason: str) -> dict:
    return {
        "ok": False,
        "ran": False,
        "reason": reason,
        "command": "",
        "exit": None,
        "stdout": "",
        "stderr": "",
        "observed": None,
    }


def reproduce_command(path: str | Path) -> str:
    """The command a reader would run by hand to see the same output."""
    return f"python3 {path} <rows.json>"


def execute(
    artifact: Artifact,
    *,
    rows: list[dict] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """Run the artifact over ``rows`` and report exactly what happened."""
    if not (artifact.content or "").strip():
        return _blank("artifact has no content to execute")
    if timeout <= 0:
        return _blank("timeout must be positive")

    payload = rows if rows is not None else []
    try:
        with tempfile.TemporaryDirectory(prefix="qse-run-") as workdir:
            module = Path(workdir) / f"{(slug(artifact.title) or 'artifact')}.py"
            module.write_text(artifact.content, encoding="utf-8")
            rows_path = Path(workdir) / "rows.json"
            rows_path.write_text(json.dumps(payload), encoding="utf-8")
            command = [sys.executable, str(module), str(rows_path)]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=workdir,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return {
                    **_blank(f"timed out after {timeout}s"),
                    "command": reproduce_command(artifact.title + ".py"),
                }
            except OSError as exc:
                return {
                    **_blank(f"could not start the artifact: {exc}"),
                    "command": reproduce_command(artifact.title + ".py"),
                }
    except OSError as exc:  # a temporary directory could not be made or written
        return _blank(f"could not stage the artifact for execution: {exc}")

    observed = None
    try:
        parsed = json.loads(completed.stdout)
        observed = parsed if isinstance(parsed, dict) else {"output": parsed}
    except json.JSONDecodeError:
        observed = None

    ok = completed.returncode == 0 and observed is not None
    if ok:
        reason = ""
    elif completed.returncode != 0:
        reason = f"exit {completed.returncode}: {completed.stderr.strip().splitlines()[-1] if completed.stderr.strip() else 'no stderr'}"
    else:
        reason = "stdout was not a JSON object, so the run produced no result to consume"

    return {
        "ok": ok,
        "ran": True,
        "reason": reason,
        "command": reproduce_command(f"{(slug(artifact.title) or 'artifact')}.py"),
        "exit": completed.returncode,
        "stdout": completed.stdout[:_KEEP],
        "stderr": completed.stderr[:_KEEP],
        "observed": observed,
    }
