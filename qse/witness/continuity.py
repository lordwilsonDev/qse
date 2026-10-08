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

#: How a *watched subject's* identity moved between two beats. Separate from the
#: recorder's own gap kinds because the two can disagree in the way that matters: a
#: recorder can keep beating perfectly while the thing it was watching dies and returns.
SUBJECT_KINDS = ("SUBJECT_UNWATCHED", "SUBJECT_OK", "SUBJECT_RESTARTED",
                 "SUBJECT_MISSING", "SUBJECT_APPEARED",
                 "SUBJECT_VOUCH_CONFLICT", "SUBJECT_TOKEN_DRIFT")

#: The two ways a subject's identity can be witnessed, and why both are kept. The
#: machine *observes* a process (name, pid, started); the subject can *declare* a token
#: (a run id it emits at start). Neither is authoritative: a token survives a process it
#: should not, and a pid is reused by a process it should not be. So the record keeps both
#: and reports where they disagree, rather than picking one to trust -- the same rule MoIE
#: applies to experts (agreement is reported, never counted into a decision).
SUBJECT_VOUCH_CONFLICT = "SUBJECT_VOUCH_CONFLICT"
SUBJECT_TOKEN_DRIFT = "SUBJECT_TOKEN_DRIFT"

#: How a consumer chooses to settle a disagreement *between the two witnesses*. The
#: policy is declared before the run (recorded on a beat) or passed to ``verify``, so the
#: verdict is fixed by a stated rule rather than by whichever witness a reader believes.
#: ``report`` is the default and resolves nothing -- the disagreement stays a break, which
#: is the honest choice when no policy was given. The others pick a winner *on the record*:
#:
#: * ``probe`` -- the machine's observation outranks the token: a new process is a restart
#:   even if the run id was preserved, and a token change on the same process is excused
#:   (the process did not stop, so the probe says the subject did not).
#: * ``token`` -- the subject's declaration outranks the probe: a preserved run id means
#:   the logical run continued across a new process, and a re-declared token is a break.
#: * ``both`` -- require both witnesses to agree the subject is continuous; any
#:   disagreement is a break.
POLICIES = ("report", "probe", "token", "both")


def resolve_subject(kind: str, policy: str) -> tuple[bool, str]:
    """Whether a subject transition is a break under a declared policy, and why.

    Returns ``(is_break, why)``. The reason is returned rather than a bare bool so the
    record can show *how the rule treated the case*, not only that a rule existed.
    """
    if policy not in POLICIES:
        raise ValueError(f"unknown subject policy {policy!r}; choose from {POLICIES}")
    if policy == "probe" and kind == SUBJECT_TOKEN_DRIFT:
        return False, ("the policy trusts the machine's observation, and the process did not "
                       "change, so the token change does not interrupt the subject")
    if policy == "token" and kind == SUBJECT_VOUCH_CONFLICT:
        return False, ("the policy trusts the declared token, and the run id did not change, "
                       "so the new process does not interrupt the logical run")
    if kind in (SUBJECT_VOUCH_CONFLICT, SUBJECT_TOKEN_DRIFT):
        return True, f"the policy {policy!r} does not excuse this disagreement"
    if kind in ("SUBJECT_RESTARTED", "SUBJECT_MISSING"):
        return True, "the subject's continuity is not established"
    return False, "no break under this policy"


#: How a subject *advances*. Liveness is not progress: a process can be perfectly
#: continuous -- same identity, same token, beats on time -- while deadlocked, waiting on
#: a lock, or looping over an empty queue. This is the fourth surface (after the recorder's
#: gaps, the subject's identity, and the two witnesses' agreement), and it catches the
#: failure the others structurally cannot: the one that keeps running and does nothing.
PROGRESS_KINDS = ("PROGRESS_ADVANCING", "PROGRESS_FLAT", "PROGRESS_REGRESSED",
                  "PROGRESS_NO_SIGNAL")

#: How many consecutive flat beats before a stall is declared. A declared convention, like
#: the beat interval and the slack -- not a measurement.
DEFAULT_STALL_AFTER = 3


def progress_of(record: Mapping[str, Any]) -> float | None:
    """The numeric progress a beat reported, or ``None`` when it reported none."""
    value = record.get("progress")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def classify_progress(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the progress signal across two beats. A flat pair is not yet a stall."""
    before = progress_of(previous)
    after = progress_of(current)
    if before is None or after is None:
        return {"kind": "PROGRESS_NO_SIGNAL",
                "why": "no numeric progress was reported on both beats"}
    delta = round(after - before, 6)
    if after > before:
        return {"kind": "PROGRESS_ADVANCING", "delta": delta,
                "why": f"the progress signal advanced by {delta:g}"}
    if after < before:
        return {"kind": "PROGRESS_REGRESSED", "delta": delta,
                "why": f"the progress signal went backwards by {abs(delta):g}, which a "
                       "monotone counter cannot do without resetting"}
    return {"kind": "PROGRESS_FLAT", "delta": 0.0,
            "why": "the progress signal did not advance between these beats"}

#: The fields of a subject identity that must not change across a restart. A pid can be
#: reused; a start time cannot be reproduced by a new process, so both are kept.
SUBJECT_FIELDS = ("name", "pid", "started")

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
    subject: Mapping[str, Any] | None = None,
    progress: float | None = None,
    policy: str | None = None,
    interval: float = DEFAULT_INTERVAL,
    note: str = "",
) -> dict[str, Any]:
    """Record one heartbeat, hash-chained onto the ledger.

    ``wall`` and ``mono`` are recorded together because the pair says whether the
    process was *frozen* (wall advanced, monotonic did not) or merely *slow* -- a
    second, clock-based witness alongside the OS power log. Every clock is injectable
    so a test can replay a history without waiting for one.

    ``subject`` is the identity of whatever this beat is a heartbeat *for* -- a job, a
    service, a process (``subject_identity`` reads one from the OS). Recorded at every
    beat rather than once, because a subject that dies and returns is only visible as a
    change across beats; compare with ``classify_subject``.
    """
    if policy is not None and policy not in POLICIES:
        raise ValueError(f"unknown subject policy {policy!r}; choose from {POLICIES}")
    if progress is not None and not isinstance(progress, (int, float)):
        raise ValueError(f"progress must be a number or None, got {type(progress).__name__}")
    record = {
        "ev": BEAT,
        "subject": dict(subject) if subject else None,
        "progress": (None if progress is None else float(progress)),
        "policy": (str(policy) if policy else None),
        "wall": round(float(time.time() if wall is None else wall), 6),
        "mono": round(float(time.monotonic() if mono is None else mono), 6),
        "boot": boot if boot is not None else boot_time(),
        "pid": int(os.getpid() if pid is None else pid),
        "interval": float(interval),
        "watch": {str(k): v for k, v in (watches or {}).items()},
        "note": str(note),
    }
    return chain.append(path, record)


def subject_identity(pid: int) -> dict[str, Any] | None:
    """A process's identity, as the OS reports it *now*. ``None`` when it is gone.

    The identity is ``(name, pid, started)`` because a restart cannot reproduce it: a
    pid can be reused, but ``lstart`` is fixed for the life of a process and changes
    when a new process takes the pid. The recorder is expected to call this at every
    beat rather than cache a pid -- the recorder staying alive is not the same fact as
    the watched thing staying alive, and this is what lets the two be told apart.
    """
    try:
        done = subprocess.run(
            ["ps", "-o", "pid=,lstart=,comm=", "-p", str(int(pid))],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        return None
    line = done.stdout.strip().splitlines()[0].strip()
    head, _, rest = line.partition(" ")
    if not head.isdigit():
        return None
    fields = rest.split()
    started = " ".join(fields[:5])
    command = " ".join(fields[5:]) or "process"
    return {"name": command, "pid": int(head), "started": started}


def subject_token(subject: Mapping[str, Any] | None) -> tuple[str, ...] | None:
    """The part of a subject identity that must not change. ``None`` when unwatched."""
    if not subject:
        return None
    return tuple(str(subject.get(field, "")) for field in SUBJECT_FIELDS)


def _declared_token(subject: Mapping[str, Any] | None) -> str | None:
    """The token the *subject itself* declared, if any. ``None`` when it declared none."""
    if not subject:
        return None
    value = subject.get("token")
    return None if value in (None, "") else str(value)


def classify_subject(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Name what happened to the *watched subject*, from two independent witnesses.

    The subject is witnessed twice: the machine *observes* a process identity
    (``name``/``pid``/``started``), and the subject may *declare* a ``token`` (a run id it
    emits at start). Neither witness is authoritative, so the case that matters is where
    they disagree:

    * ``SUBJECT_VOUCH_CONFLICT`` -- a new process, the same declared token. The subject
      vouches for a continuity the machine's own observation contradicts (a supervisor
      restarting a crashed job while preserving its run id).
    * ``SUBJECT_TOKEN_DRIFT`` -- the same process, a new declared token. The logical run
      changed without the process stopping (a job re-initialising in place).

    Both are reported as breaks; naming them apart is the point, because the remedy
    differs and a single "restarted" would hide which witness to believe.
    """
    before = subject_token(previous.get("subject"))
    after = subject_token(current.get("subject"))
    before_tok = _declared_token(previous.get("subject"))
    after_tok = _declared_token(current.get("subject"))

    if before is None and after is None and before_tok is None and after_tok is None:
        return {"kind": "SUBJECT_UNWATCHED", "why": "no subject is being watched"}
    if before is None and before_tok is None:
        return {"kind": "SUBJECT_APPEARED", "after": list(after or ()),
                "why": "watching began at this beat"}
    if after is None and after_tok is None:
        return {"kind": "SUBJECT_MISSING", "before": list(before or ()),
                "why": "the watched subject was not present at this beat, so the recorder "
                       "kept beating while the subject did not"}

    identity_changed = before != after
    token_declared = before_tok is not None or after_tok is not None
    token_changed = before_tok != after_tok
    flags = {"identity_changed": identity_changed, "token_declared": token_declared,
             "token_changed": token_changed}

    if not identity_changed and not (token_declared and token_changed):
        return {"kind": "SUBJECT_OK", "why": "the same subject identity at both beats",
                **flags}
    if identity_changed and token_declared and not token_changed:
        return {"kind": SUBJECT_VOUCH_CONFLICT, "before": list(before or ()),
                "after": list(after or ()), "token": after_tok, **flags,
                "why": "the process was replaced but still declares the same token: the "
                       "subject vouches for a continuity the machine's own observation "
                       "contradicts"}
    if identity_changed:
        return {"kind": "SUBJECT_RESTARTED", "before": list(before or ()),
                "after": list(after or ()), **flags,
                "why": "the subject's identity changed between beats: the recorder survived "
                       "a restart of the thing it was watching"}
    return {"kind": SUBJECT_TOKEN_DRIFT, "token_before": before_tok, "token_after": after_tok,
            **flags,
            "why": "the process is the same but it declared a new token: the logical run "
                   "changed without the process stopping"}


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
    policy: str | None = None,
    stall_after: int = DEFAULT_STALL_AFTER,
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
        "subject_transitions": [],
        "subject_counts": {},
        "subject_breaks": [],
        "subject_witnesses": {},
        "policy": None,
        "progress_transitions": [],
        "progress_counts": {},
        "stalls": [],
        "regressions": [],
        "longest_flat": 0,
        "stall_after": None,
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

    # The policy is declared before the run (on a beat) or passed in by the reader; an
    # explicit argument wins, so a consumer can re-read a record under a rule it states
    # rather than the one the writer chose. Reading it from the record is the point: the
    # verdict should depend on a rule that existed before the data did.
    if policy is None:
        policy = next((str(b["policy"]) for b in beats if b.get("policy")), "report")
    if policy not in POLICIES:
        raise ValueError(f"unknown subject policy {policy!r}; choose from {POLICIES}")
    result["policy"] = policy
    transitions = [
        classify(a, b, sleeps=sleeps, slack=slack) for a, b in zip(beats, beats[1:])
    ]
    result["transitions"] = transitions
    counts: dict[str, int] = {}
    for row in transitions:
        counts[row["kind"]] = counts.get(row["kind"], 0) + 1
    result["counts"] = counts
    result["lost"] = [row for row in transitions if row["kind"] == "HEARTBEAT_LOST"]

    # The subject's continuity, which is a different question from the recorder's. A
    # subject that leaves the record and comes back is a restart even though the
    # recorder never missed a beat, so a later APPEARED is relabelled RESTARTED.
    subject_rows: list[dict[str, Any]] = []
    had_subject = False
    for previous, current in zip(beats, beats[1:]):
        row = classify_subject(previous, current)
        if row["kind"] == "SUBJECT_APPEARED" and had_subject:
            row["kind"] = "SUBJECT_RESTARTED"
            row["why"] = ("the subject left the record and came back: a restart the "
                          "recorder survived")
        if current.get("subject"):
            had_subject = True
        is_break, resolution = resolve_subject(row["kind"], policy)
        row["break"] = is_break
        row["resolution"] = resolution
        subject_rows.append(row)
    result["subject_transitions"] = subject_rows
    subject_counts: dict[str, int] = {}
    for row in subject_rows:
        subject_counts[row["kind"]] = subject_counts.get(row["kind"], 0) + 1
    result["subject_counts"] = subject_counts
    result["subject_breaks"] = [row for row in subject_rows if row["break"]]
    # The two witnesses, counted separately, so a reader can see which one moved -- and
    # how often they disagreed with each other rather than with the subject.
    witnesses = {"identity_changes": 0, "token_changes": 0, "disagreements": 0}
    for row in subject_rows:
        if row.get("identity_changed"):
            witnesses["identity_changes"] += 1
        if row.get("token_declared") and row.get("token_changed"):
            witnesses["token_changes"] += 1
        if row["kind"] in (SUBJECT_VOUCH_CONFLICT, SUBJECT_TOKEN_DRIFT):
            witnesses["disagreements"] += 1
    result["subject_witnesses"] = witnesses

    # Progress: liveness is not advance. A run of consecutive flat beats at or over
    # ``stall_after`` is a stall -- the subject is alive and making no progress, which no
    # identity or gap check can see. A regression is a hard discontinuity and is reported
    # separately, because a monotone signal going backwards is not the same as standing still.
    result["stall_after"] = stall_after
    progress_rows = [classify_progress(a, b) for a, b in zip(beats, beats[1:])]
    result["progress_transitions"] = progress_rows
    progress_counts: dict[str, int] = {}
    for row in progress_rows:
        progress_counts[row["kind"]] = progress_counts.get(row["kind"], 0) + 1
    result["progress_counts"] = progress_counts

    runs: list[int] = []
    run = 0
    for row in progress_rows:
        if row["kind"] == "PROGRESS_FLAT":
            run += 1
        else:
            if run:
                runs.append(run)
            run = 0
    if run:
        runs.append(run)
    result["longest_flat"] = max(runs, default=0)
    result["stalls"] = [
        {"flat_beats": n,
         "why": f"the subject stayed alive and its progress signal held flat for {n} "
                f"consecutive beats (threshold {stall_after}): liveness without advance"}
        for n in runs if n >= stall_after
    ]
    result["regressions"] = [row for row in progress_rows if row["kind"] == "PROGRESS_REGRESSED"]

    if not beats:
        result["verdict"] = "EMPTY"
    elif result["lost"]:
        result["verdict"] = "BROKEN"
    elif result["subject_breaks"]:
        result["verdict"] = "SUBJECT_BROKE"
    elif result["regressions"]:
        result["verdict"] = "SUBJECT_BROKE"
    elif result["stalls"]:
        result["verdict"] = "SUBJECT_STALLED"
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
