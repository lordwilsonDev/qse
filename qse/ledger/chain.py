"""The hash-chained JSONL event ledger.

The scheme is the one the north-star scorecard proved out, reused rather than
reinvented: each line is one JSON object, ``seq`` is its 1-based line number,
``prev`` is the sha256 of the **exact stored text** of the previous line, and the
first line's ``prev`` is ``GENESIS``. Records are serialised with
``sort_keys=True`` so the same event always produces the same bytes.

Honest limits. Both are structural, not bugs to be fixed later:

* The chain cannot vouch for the **last** line. Nothing follows it to disagree
  with it. ``tail()`` publishes its hash so a later reader can notice a change,
  and that is the most this design can do.
* ``verify_chain`` reports the **first** break only. Once a link is broken every
  later ``prev`` is untrustworthy by construction, so listing the rest adds
  noise rather than information.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # POSIX. On a platform without it the lock degrades to the fsync guarantee.
    import fcntl
except ImportError:  # pragma: no cover - exercised only off-POSIX
    fcntl = None  # type: ignore[assignment]

GENESIS = "0" * 64


class LedgerCorrupt(RuntimeError):
    """The ledger exists and cannot be trusted. Never extend or overwrite one."""


def line_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_lines(path: str | os.PathLike[str]) -> list[str]:
    """Every non-blank stored line, verbatim. Blank lines are ignored rather than
    fatal so that a trailing newline is not mistaken for corruption."""
    target = Path(path)
    if not target.exists():
        return []
    text = target.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def tail(path: str | os.PathLike[str]) -> str | None:
    """The hash of the last line, or None for an empty ledger.

    Published in reports because the chain cannot cover the last line by itself.
    """
    lines = read_lines(path)
    return line_sha(lines[-1]) if lines else None


def verify_chain(lines: Iterable[str]) -> tuple[int, int | None, str]:
    """Return ``(line_count, first_bad_seq_or_None, reason)``."""
    stored = list(lines)
    prev = GENESIS
    for n, text in enumerate(stored, 1):
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            return len(stored), n, f"line {n}: not JSON ({exc.msg})"
        if not isinstance(event, dict):
            return len(stored), n, f"line {n}: not a JSON object"
        if event.get("seq") != n:
            return len(stored), n, f"line {n}: seq is {event.get('seq')!r}, expected {n}"
        if event.get("prev") != prev:
            return len(stored), n, f"line {n}: chain broken (prev does not match the previous line)"
        prev = line_sha(text)
    return len(stored), None, f"{len(stored)} line(s), chain intact"


def parse(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Parse stored lines into records, refusing anything unreadable.

    Unlike ``verify_chain`` this does not care about ``seq`` or ``prev``; it is
    the reader used after the chain has already been checked.
    """
    out: list[dict[str, Any]] = []
    for n, text in enumerate(lines, 1):
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            raise LedgerCorrupt(f"line {n}: not JSON ({exc.msg})") from exc
        if not isinstance(event, dict):
            raise LedgerCorrupt(f"line {n}: not a JSON object")
        out.append(event)
    return out


def load(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read a ledger. Raises ``LedgerCorrupt`` if the chain is broken, so a caller
    can never quietly consume a tampered history."""
    lines = read_lines(path)
    count, bad, reason = verify_chain(lines)
    if bad is not None:
        raise LedgerCorrupt(f"{reason} (ledger {path} has {count} line(s))")
    return parse(lines)


def append(path: str | os.PathLike[str], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Chain one record onto the ledger, atomically, refusing a broken ledger.

    Read-verify-write happens under a single exclusive lock, so two processes
    cannot both decide they are line *n*.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            lines = [line for line in handle.read().splitlines() if line.strip()]
            count, bad, reason = verify_chain(lines)
            if bad is not None:
                raise LedgerCorrupt(f"refusing to extend a broken ledger: {reason}")
            record = {k: v for k, v in payload.items() if k not in ("seq", "prev")}
            record["seq"] = count + 1
            record["prev"] = line_sha(lines[-1]) if lines else GENESIS
            text = json.dumps(record, sort_keys=True)
            handle.seek(0, os.SEEK_END)
            handle.write(text + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            return record
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
