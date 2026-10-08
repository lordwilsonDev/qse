"""Continuity: a heartbeat that can be trusted because it refuses to trust the machine.

The moonshot this implements is an *inversion*. Everyone runs an always-on Mac mini to
make it **compute**; the settled belief is that its value is the work it does. Invert
that (AIL ``TEMPORAL`` and ``AUTHORITY`` operators, see ``docs/moonshot-m.md``) and the
value is the work it can **attest** -- continuity that a long job or a customer can
lean on, which no machine can honestly produce about itself.

Three things make the record honest, and each is a small inversion of the obvious:

* **A gap is a claim, not a fact.** The next heartbeat classifies the interval before
  it instead of assuming it was one interval: ``CONTINUOUS``, ``SLEPT`` (the OS power
  log explains it), ``REBOOT`` (the boot time changed), or ``HEARTBEAT_LOST`` (nothing
  explains it, and the record says so rather than rounding to "fine").
* **The machine is not its own witness.** Sleep is established by the kernel's power
  log (``qse.witness.power``), not by the process that might have died.
* **Absence is evidence.** A watched metric that never changed is recorded and
  reported, because "the disk did not fill" is the thing a long run needs to know and
  the thing a log of changes alone can never show.

The ledger is ``qse.ledger.chain``'s hash-chained JSONL, reused rather than
reinvented, so tampering is detectable by the same code that guards the engine's own
history -- including its one structural limit, that the last line is uncatchable.
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..ledger import chain
from . import power

BEAT = "beat"

#: Seconds. The intended beat spacing, and how far past it a gap may be before it needs
#: an explanation. Both are declared conventions, not measurements.
DEFAULT_INTERVAL = 60.0
SLACK = 5.0

KINDS = ("CONTINUOUS", "SLEPT", "REBOOT", "HEARTBEAT_LOST")

_BOOT = re.compile(r"sec\s*=\s*(\d+),\s*usec\s*=\s*(\d+)")


def boot_time() -> float | None:
    """Wall-clock seconds of the last boot, from ``kern.boottime``. None if unreadable.

    This is the second OS witness: a gap during which the boot time changed is a
    restart, and no sleep can be blamed for it.
    """
    try:
        done = subprocess.run(
            ["sysctl", "-n", "kern.boottime"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    match = _BOOT.search(done.stdout)
    if not match:
        return None
    return int(match.group(1)) + int(match.group(2)) / 1e6


def beat(
    path: str | os.PathLike[str],
    *,
    wall: float | None = None,
    mono: float | None = None,
    boot: float | None = None,
    pid: int | None = None,
    watches: Mapping[str, Any] | None = None,
    interval: float = DEFAULT_INTERVAL,
    note: str = "",
) -> dict[str, Any]:
    """Record one heartbeat, hash-chained onto the ledger.

    ``wall`` and ``mono`` are recorded together because the pair says whether the
    process was *frozen* (wall advanced, monotonic did not) or merely *slow* -- a
    second, clock-based witness alongside the OS power log. Every clock is injectable
    so a test can replay a history without waiting for one.
    """
    record = {
        "ev": BEAT,
        "wall": round(float(time.time() if wall is None else wall), 6),
        "mono": round(float(time.monotonic() if mono is None else mono), 6),
        "boot": boot if boot is not None else boot_time(),
        "pid": int(os.getpid() if pid is None else pid),
        "interval": float(interval),
        "watch": {str(k): v for k, v in (watches or {}).items()},
        "note": str(note),
    }
    return chain.append(path, record)


def classify(
    previous: Mapping[str, Any],
    current: Mapping[str, Any],
    *,
    sleeps: Sequence[power.Sleep] = (),
    slack: float = SLACK,
) -> dict[str, Any]:
    """Name the interval between two beats. Four outcomes, none assumed.

    Order matters and is the point: a boot change is checked first (a restart is not a
    sleep), then the ordinary interval, then the OS power log, and only if nothing
    explains the gap is it reported as lost.
    """
    gap = float(current["wall"]) - float(previous["wall"])
    expected = float(previous.get("interval") or DEFAULT_INTERVAL)
    base: dict[str, Any] = {"gap": round(gap, 3), "expected": expected}

    if current.get("boot") != previous.get("boot"):
        return {**base, "kind": "REBOOT", "sleeps": [],
                "why": "the boot time changed, so the machine restarted; the gap is a "
                       "reboot and not a heartbeat the recorder failed to write"}

    if gap <= expected + slack:
        return {**base, "kind": "CONTINUOUS", "sleeps": [],
                "why": f"gap {gap:.3f}s is within one beat interval ({expected:.0f}s)"}

    covering = power.covering(sleeps, float(previous["wall"]), float(current["wall"]))
    if covering:
        slept = sum(
            (s.woke if s.woke is not None else float(current["wall"])) - s.entered
            for s in covering
        )
        return {**base, "kind": "SLEPT", "sleeps": [s.to_dict() for s in covering],
                "why": f"the OS power log records {len(covering)} sleep interval(s) over the "
                       f"gap ({slept:.0f}s of recorded sleep), so the machine slept rather "
                       f"than stopped"}

    return {**base, "kind": "HEARTBEAT_LOST", "sleeps": [],
            "why": "no sleep in the OS power log and no boot change explains the gap: the "
                   "recorder or the machine stopped and left no record of why"}


def verify(
    path: str | os.PathLike[str],
    *,
    sleeps: Sequence[power.Sleep] | None = None,
    slack: float = SLACK,
) -> dict[str, Any]:
    """Check the chain and classify every interval in it. Reports, never rounds up."""
    lines = chain.read_lines(path)
    count, bad, reason = chain.verify_chain(lines)
    result: dict[str, Any] = {
        "ledger": str(path),
        "lines": count,
        "chain_ok": bad is None,
        "chain_reason": reason,
        "tail": chain.tail(path),
        "beats": 0,
        "transitions": [],
        "counts": {},
        "lost": [],
        "power_sleeps": None,
        "verdict": "EMPTY",
    }
    if bad is not None:
        result["verdict"] = "TAMPERED"
        return result

    records = chain.parse(lines)
    if sleeps is None:
        sleeps = power.load()
    result["power_sleeps"] = len(sleeps)

    beats = [r for r in records if r.get("ev") == BEAT]
    result["beats"] = len(beats)
    transitions = [
        classify(a, b, sleeps=sleeps, slack=slack) for a, b in zip(beats, beats[1:])
    ]
    result["transitions"] = transitions
    counts: dict[str, int] = {}
    for row in transitions:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    result["counts"] = counts
    result["lost"] = [row for row in transitions if row["kind"] == "HEARTBEAT_LOST"]

    if not beats:
        result["verdict"] = "EMPTY"
    elif result["lost"]:
        result["verdict"] = "BROKEN"
    else:
        result["verdict"] = "CONTINUOUS"
    return result


def absences(path_or_records: str | os.PathLike[str] | Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """What did *not* change. A metric that held steady is evidence, not silence.

    This is the inversion's second edge: a log of changes can never show that nothing
    happened. A watched metric that never moved is the only record that can, so it is
    computed and reported with the same standing as a change would get.
    """
    if isinstance(path_or_records, (str, os.PathLike)):
        records = chain.load(path_or_records)
    else:
        records = list(path_or_records)

    seen: dict[str, list[Any]] = {}
    for record in records:
        if record.get("ev") != BEAT:
            continue
        for name, value in (record.get("watch") or {}).items():
            seen.setdefault(str(name), []).append(value)

    out: list[dict[str, Any]] = []
    for name, values in sorted(seen.items()):
        numeric = [v for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        row: dict[str, Any] = {"metric": name, "samples": len(values),
                               "first": values[0], "last": values[-1]}
        if numeric:
            row.update({"min": min(numeric), "max": max(numeric),
                        "changed": min(numeric) != max(numeric)})
        else:
            row["changed"] = len({str(v) for v in values}) > 1
        row["note"] = (
            "held steady across the window: evidence that this did not move, which a "
            "log of changes could never show"
            if not row["changed"] else
            "changed during the window"
        )
        out.append(row)
    return out
