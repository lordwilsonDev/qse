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

import hashlib
import os
import re
import stat
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


#: The side-effect witness: the same two-witness pattern as identity -- the declared value
#: against the observed value -- now applied to *advance*. ``progress`` is what the subject
#: says it did; ``effect`` is what the recorder read from the world. This axis is deliberately
#: *not* routed through the identity policy: the two identity witnesses could each be wrong in
#: either direction, so their disagreement needed a declared rule, but here the directions are
#: asymmetric -- a claimed advance the world does not show is the inverse failure this whole
#: moonshot exists to catch, and an advance the world shows unclaimed is benign -- so the
#: asymmetry, not a policy, is the finding.
EFFECT_KINDS = ("EFFECT_AGREES", "EFFECT_UNSUBSTANTIATED", "EFFECT_UNREPORTED",
                "EFFECT_NO_SIGNAL")


def effect_of(record: Mapping[str, Any]) -> float | None:
    """The side effect the *recorder* observed (a size, a count, a depth), or ``None``.

    Kept in a field of its own, apart from ``progress``: the subject writes ``progress``,
    the recorder reads ``effect``. Only the separation lets the record say where the two
    disagree, which is the same discipline identity and its token follow.
    """
    value = record.get("effect")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def file_effect(path: str | os.PathLike[str]) -> float | None:
    """A ready-made side effect: a file's size in bytes, or ``None`` when unreadable.

    A file the subject is supposed to grow is an observation the recorder can make for
    itself, from the world rather than from any counter the subject reports. It is a
    convenience, not the only effect -- any number the caller reads from a source the
    subject does not control will do.
    """
    try:
        return float(os.path.getsize(path))
    except OSError:
        return None


def classify_effect(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the *claimed* progress against the *observed* side effect across two beats.

    * ``EFFECT_UNSUBSTANTIATED`` -- the subject reports an advance and the observed effect
      does not move: progress the world does not show. A single beat may be lag, so this is
      treated as a finding only when it is sustained (see ``verify``).
    * ``EFFECT_UNREPORTED`` -- the observed effect advances while the subject reports none:
      work in the world the subject did not claim, which is under-reporting, not a break.
    * ``EFFECT_AGREES`` -- the two did not diverge (both advanced, or both held).
    * ``EFFECT_NO_SIGNAL`` -- a ``progress`` or ``effect`` value was missing on one beat.
    """
    declared_before, declared_after = progress_of(previous), progress_of(current)
    observed_before, observed_after = effect_of(previous), effect_of(current)
    if None in (declared_before, declared_after, observed_before, observed_after):
        return {"kind": "EFFECT_NO_SIGNAL",
                "why": "a progress or effect value was missing on one of the two beats"}
    declared = round(declared_after - declared_before, 6)
    observed = round(observed_after - observed_before, 6)
    if declared > 0 and observed <= 0:
        return {"kind": "EFFECT_UNSUBSTANTIATED", "declared": declared, "observed": observed,
                "why": f"the subject reports advancing by {declared:g} while the observed "
                       "side effect did not move: a claimed advance the world does not show"}
    if declared <= 0 and observed > 0:
        return {"kind": "EFFECT_UNREPORTED", "declared": declared, "observed": observed,
                "why": f"the observed side effect advanced by {observed:g} while the subject "
                       "did not report it: an advance in the world, unclaimed"}
    return {"kind": "EFFECT_AGREES", "declared": declared, "observed": observed,
            "why": "the claimed progress and the observed side effect did not diverge"}


#: Corroboration: a claimed advance is only as strong as how many *named* sources agree
#: about it. One source can be moved by whoever controls it; two sources that would have to
#: advance together for a forgery to pass cost more to fake. The record does not *assert*
#: that the sources are independent -- it counts how many advance together and names where
#: they contradict, so the reader sees the strength of the evidence rather than a boolean
#: the caller swore to.
CORROBORATION_KINDS = ("CORROBORATION_CORROBORATED", "CORROBORATION_SINGLE_SOURCE",
                       "CORROBORATION_SPLIT", "CORROBORATION_NONE")


def effects_of(record: Mapping[str, Any]) -> dict[str, float]:
    """The *named* side-effect sources the recorder read, as ``{name: value}``."""
    raw = record.get("effects") or {}
    out: dict[str, float] = {}
    for name, value in raw.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            out[str(name)] = float(value)
    return out


def corroborate(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Compare the *named* effect sources across two beats and say how they agree.

    * ``CORROBORATION_CORROBORATED`` -- two or more sources advanced and none regressed:
      the advance is witnessed more than once, so a forgery would have to move them together.
    * ``CORROBORATION_SINGLE_SOURCE`` -- exactly one source advanced: a real witness, but
      its independence is unestablished.
    * ``CORROBORATION_SPLIT`` -- some sources advanced while others went backwards: the
      witnesses contradict each other about the world.
    * ``CORROBORATION_NONE`` -- no source advanced (or none was read on both beats).
    """
    before, after = effects_of(previous), effects_of(current)
    common = sorted(set(before) & set(after))
    deltas = {name: round(after[name] - before[name], 6) for name in common}
    advancing = [name for name in common if deltas[name] > 0]
    regressed = [name for name in common if deltas[name] < 0]
    if advancing and regressed:
        kind = "CORROBORATION_SPLIT"
    elif len(advancing) >= 2:
        kind = "CORROBORATION_CORROBORATED"
    elif advancing:
        kind = "CORROBORATION_SINGLE_SOURCE"
    else:
        kind = "CORROBORATION_NONE"
    return {"kind": kind, "sources": common, "deltas": deltas,
            "advancing": advancing, "regressed": regressed}


#: Independence: a claimed advance is only as strong as *why* a witness is beyond the
#: subject's reach. ``corroborate`` counts how many named sources agree about an advance;
#: it cannot tell two sources the subject writes from two it merely reads. So each source
#: may *declare* a provenance -- the reason it is outside the subject's control -- and the
#: record counts only those that carry one, separate from the count of agreeing voices. The
#: declaration is the caller's, and the ledger never promotes it to proof: an advance whose
#: agreeing sources are all within reach is reported as independence *unproven*, not as
#: attested. The next inversion of MOONSHOT-M, one level deeper than corroboration.
#:
#: * ``read_only`` -- the recorder read the source and has no write path to it (a file it
#:   only stats, a socket it only reads).
#: * ``causal`` -- the value bears a causal trail back to the work (a downstream consumer's
#:   count, a checksum the subject cannot author).
#: * ``external`` -- the value lives outside the subject's machine (a third party's record).
#: * ``within`` -- the subject's own counter, in its reach; declared rather than hidden.
PROVENANCE_KINDS = ("read_only", "causal", "external", "within")

#: The declared provenances that mean a source is *beyond the subject's reach*. Kept as a
#: tuple of reasons rather than a boolean so a reader sees *why*, not just *that*.
BEYOND_REACH = ("read_only", "causal", "external")

#: The next inversion, one level past a declaration: a declaration is a claim, and a claim
#: can be *checked*. When the caller names a source's path, the recorder stat()s it itself
#: and records what it can see -- the mode bits and its own write access -- rather than
#: taking the caller's word. A source the recorder cannot write is beyond the reach of any
#: process sharing its uid; a source it *can* write cannot be beyond reach however it was
#: declared, so marking a writable source ``read_only`` no longer buys independence.
#:
#: * ``REACH_READ_ONLY`` -- checked: the file exists and the recorder has no write path to
#:   it (owner write bit clear, or ``os.access(W_OK)`` false).
#: * ``REACH_WRITABLE`` -- checked: the recorder could write it, so it is within reach.
#: * ``REACH_UNKNOWN`` -- the path could not be stat()ed; nothing was observed.
REACH_KINDS = ("REACH_READ_ONLY", "REACH_WRITABLE", "REACH_UNKNOWN")


def observe_reach(path: str | os.PathLike[str]) -> str:
    """What the recorder can *check* about a path's reach, not what a caller claims.

    The observation is deliberately narrow and local: it stats ``path`` and asks whether
    the recorder itself could write it. A path whose owner write bit is clear, or which
    ``os.access`` refuses, is ``REACH_READ_ONLY``; one the recorder can write is
    ``REACH_WRITABLE``; one that cannot be stat()ed is ``REACH_UNKNOWN``. The check is a
    fact the recorder read from the filesystem, so it defeats a caller that merely
    *declares* a writable source read-only -- but it is the recorder's own access, so a
    subject running as a *different* user is not covered, and as root nothing is.
    """
    try:
        info = os.stat(path)
    except OSError:
        return "REACH_UNKNOWN"
    owner_write = bool(stat.S_IMODE(info.st_mode) & stat.S_IWUSR)
    if owner_write and os.access(path, os.W_OK):
        return "REACH_WRITABLE"
    return "REACH_READ_ONLY"


#: Whether a claimed advance is backed by witnesses beyond the subject's reach. Distinct
#: from ``CORROBORATION_KINDS``: agreement is not independence, and this vocabulary is
#: deliberately weaker -- it can report INDEPENDENT, but the strongest verdict a ledger
#: reaches when independence is *not* declared is UNPROVEN, never a silent pass.
#:
#: ``INDEPENDENCE_ATTESTED`` is the one kind a *check* can reach and a declaration cannot:
#: two advancing sources the recorder itself observed to be read-only. ``INDEPENDENCE_
#: CONTRADICTED`` is the inverse -- a source declared beyond reach that the recorder's own
#: stat() showed it could write, so the declaration is defeated and reported, not believed.
#:
#: ``INDEPENDENCE_MEASURED`` is the one kind a *measurement* reaches and a permission check
#: alone cannot: two advancing sources the recorder both observed read-only *and* read
#: itself, so the value is a function of bytes it opened rather than a number the caller
#: typed. It sits above ATTESTED because it is the same reach plus one more observation --
#: the value's provenance, not only the file's permissions.
INDEPENDENCE_KINDS = ("INDEPENDENCE_MEASURED", "INDEPENDENCE_ATTESTED",
                      "INDEPENDENCE_INDEPENDENT", "INDEPENDENCE_CONTRADICTED",
                      "INDEPENDENCE_DECLARED_ONLY", "INDEPENDENCE_UNPROVEN",
                      "INDEPENDENCE_NONE")


def provenance_of(record: Mapping[str, Any]) -> dict[str, str]:
    """The provenance each named source *declared*, as ``{name: kind}``.

    Only declared kinds drawn from ``PROVENANCE_KINDS`` are kept, so a malformed or
    unrecognised declaration is ignored rather than believed -- the same rule the rest of
    the record applies to anything it cannot check.
    """
    raw = record.get("provenance") or {}
    out: dict[str, str] = {}
    for name, kind in raw.items():
        if isinstance(kind, str) and kind in PROVENANCE_KINDS:
            out[str(name)] = kind
    return out


def _source_provenance(previous: Mapping[str, Any], current: Mapping[str, Any],
                       name: str) -> str | None:
    """A source's declared provenance, taken from the later beat that declared one."""
    return provenance_of(current).get(name) or provenance_of(previous).get(name)


def reach_of(record: Mapping[str, Any]) -> dict[str, str]:
    """The reach the recorder *observed* for each named source, as ``{name: REACH_KIND}``.

    ``provenance_of`` reads what a caller declared; this reads what the recorder checked.
    Only kinds drawn from ``REACH_KINDS`` are kept, so a malformed observation is ignored
    rather than believed -- the same rule the record applies to every declaration.
    """
    raw = record.get("reach") or {}
    out: dict[str, str] = {}
    for name, kind in raw.items():
        if isinstance(kind, str) and kind in REACH_KINDS:
            out[str(name)] = kind
    return out


def _source_reach(previous: Mapping[str, Any], current: Mapping[str, Any],
                  name: str) -> str | None:
    """A source's observed reach, taken from the later beat that observed one."""
    return reach_of(current).get(name) or reach_of(previous).get(name)


#: Reach is a fact about a source's *permissions*; this is a fact about its *value* -- what
#: the recorder read, not what the caller typed. The whole of MOONSHOT-M has been moving a
#: claim from given to checkable, and the last claim still merely given was the number
#: itself: ``progress`` is the subject's word and ``effects`` were the caller's. Name a
#: source's path and the recorder reads the bytes for itself (``measure``), so the advancing
#: value is a function of the file and a checksum pins which bytes it read -- something a
#: caller holding only a number cannot produce. When a caller *reports* a value and also
#: names its path, the report is checked against the read: agreement makes it measured, and
#: a number the bytes refute is ``VALUE_CONTRADICTED``. So the record measures the value
#: *and* verifies the claim, rather than measuring while believing.
#:
#: * ``VALUE_MEASURED`` -- the recorder read the bytes itself (or confirmed a reported value
#:   against them), so the value is an observation, not a report.
#: * ``VALUE_REPORTED`` -- the value is the caller's number, with nothing for the recorder to
#:   check it against. Recorded, never promoted.
#: * ``VALUE_CONTRADICTED`` -- the caller reported a number and the bytes the recorder read
#:   disagreed: the report is defeated by the measurement and named, not believed.
#: * ``VALUE_UNKNOWN`` -- a path was named but could not be read; nothing was observed.
VALUE_KINDS = ("VALUE_MEASURED", "VALUE_REPORTED", "VALUE_CONTRADICTED", "VALUE_UNKNOWN")


def _read_bytes(path: str | os.PathLike[str]) -> bytes | None:
    """The bytes of a source the recorder opens and reads itself, or ``None``."""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def content_digest(path: str | os.PathLike[str]) -> str | None:
    """A checksum over the bytes the recorder read itself, or ``None`` when unreadable.

    This is "a checksum over bytes it did not author": the value is a function of the
    file's contents, computed by the recorder's own read, so it cannot be produced by a
    caller who holds only a number -- and two files of the same *size* with different bytes
    hash differently, which a size alone can never tell apart.
    """
    data = _read_bytes(path)
    return None if data is None else hashlib.sha256(data).hexdigest()


def measure(path: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Read a source for itself: the byte count read and the checksum of those bytes.

    The value-level counterpart of ``observe_reach``. Reach asks whether the recorder
    *could* write a source; this reads it, so the number a witness advances is a function
    of bytes the recorder opened rather than a number the caller supplied. ``None`` when
    the path cannot be read -- nothing is observed, so nothing is claimed.
    """
    data = _read_bytes(path)
    if data is None:
        return None
    return {"bytes": float(len(data)), "digest": hashlib.sha256(data).hexdigest()}


def _value_kind(reported: float | None, observed: Mapping[str, Any] | None) -> str:
    """Classify a source's value from the report (if any) and the measurement (if any).

    A reported number the recorder did not read is ``VALUE_REPORTED``; a value it read (or
    a report the read confirmed) is ``VALUE_MEASURED``; a report the bytes refute is
    ``VALUE_CONTRADICTED``; a path it could not read is ``VALUE_UNKNOWN``.
    """
    if observed is None:
        return "VALUE_UNKNOWN"
    if reported is None:
        return "VALUE_MEASURED"
    measured_bytes = observed.get("bytes")
    if isinstance(measured_bytes, (int, float)) and round(reported - float(measured_bytes), 6) == 0:
        return "VALUE_MEASURED"
    return "VALUE_CONTRADICTED"


def value_of(record: Mapping[str, Any]) -> dict[str, str]:
    """The provenance of each named source's *value*, as ``{name: VALUE_KIND}``.

    ``reach_of`` reads whether the recorder could write a source; this reads whether the
    value it holds was one the recorder measured. Only kinds drawn from ``VALUE_KINDS``
    are kept, so a malformed observation is ignored rather than believed -- the same rule
    the record applies to every declaration.
    """
    raw = record.get("values") or {}
    out: dict[str, str] = {}
    for name, kind in raw.items():
        if isinstance(kind, str) and kind in VALUE_KINDS:
            out[str(name)] = kind
    return out


def measurements_of(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """The measurements the recorder took, as ``{name: {bytes, digest}}`` (values may be None)."""
    raw = record.get("measured") or {}
    out: dict[str, dict[str, Any]] = {}
    for name, observed in raw.items():
        if not isinstance(observed, Mapping):
            continue
        size = observed.get("bytes")
        digest = observed.get("digest")
        out[str(name)] = {
            "bytes": float(size) if isinstance(size, (int, float)) and not isinstance(size, bool) else None,
            "digest": digest if isinstance(digest, str) else None,
        }
    return out


def _source_value(previous: Mapping[str, Any], current: Mapping[str, Any],
                  name: str) -> str | None:
    """A source's value provenance, taken from the later beat that recorded one."""
    return value_of(current).get(name) or value_of(previous).get(name)


def independence(previous: Mapping[str, Any], current: Mapping[str, Any]) -> dict[str, Any]:
    """Count how many *advancing* sources are declared beyond the subject's reach.

    The counterpart to ``corroborate``: that function counts agreement, this one counts the
    reasons the agreeing sources could not all have been moved by the subject. A source with
    no declaration is credited to none of the reach classes -- the record reports
    independence as unproven rather than silently letting agreement stand in for it.

    * ``INDEPENDENCE_MEASURED`` -- two or more advancing sources the recorder both *checked*
      read-only and *measured* itself: the value is a function of bytes it read, so it is
      observed rather than reported, one level past the reach check.
    * ``INDEPENDENCE_ATTESTED`` -- two or more advancing sources the recorder itself
      *checked* read-only: independence observed, not merely sworn.
    * ``INDEPENDENCE_INDEPENDENT`` -- two or more beyond-reach sources advanced (by
      declaration only, with no observation to check it).
    * ``INDEPENDENCE_CONTRADICTED`` -- a source declared beyond reach that the recorder's
      own stat() showed it could write: the declaration is defeated and reported.
    * ``INDEPENDENCE_UNPROVEN`` -- two or more sources advanced, but fewer than two are
      beyond reach: agreement counted, independence not established.
    * ``INDEPENDENCE_DECLARED_ONLY`` -- exactly one source advanced and it is beyond
      reach: a real reason, but only one such witness.
    * ``INDEPENDENCE_NONE`` -- nothing advanced, or the sources contradicted each other.
    """
    before, after = effects_of(previous), effects_of(current)
    common = sorted(set(before) & set(after))
    deltas = {name: round(after[name] - before[name], 6) for name in common}
    advancing = [name for name in common if deltas[name] > 0]
    regressed = [name for name in common if deltas[name] < 0]
    declared = {name: _source_provenance(previous, current, name) for name in common}
    checked = {name: _source_reach(previous, current, name) for name in common}
    values = {name: _source_value(previous, current, name) for name in common}
    # A declaration beyond reach that the recorder's own stat() contradicts -- it can write
    # the source -- is defeated here: the source is not credited as beyond reach and the
    # contradiction is reported, because a check outranks a declaration.
    contradicted = [
        name for name in advancing
        if declared.get(name) in BEYOND_REACH and checked.get(name) == "REACH_WRITABLE"
    ]
    checked_beyond = [name for name in advancing if checked.get(name) == "REACH_READ_ONLY"]
    # The value-level counterpart: a source whose reach is checked read-only *and* whose
    # value the recorder measured, so both the permission and the number are observations.
    measured_beyond = [name for name in advancing
                       if checked.get(name) == "REACH_READ_ONLY"
                       and values.get(name) == "VALUE_MEASURED"]
    beyond = [name for name in advancing
              if declared.get(name) in BEYOND_REACH and name not in contradicted]
    within = [name for name in advancing if declared.get(name) == "within"]
    undeclared = [name for name in advancing if declared.get(name) is None]
    if advancing and regressed:
        kind = "INDEPENDENCE_NONE"
    elif contradicted:
        kind = "INDEPENDENCE_CONTRADICTED"
    elif len(measured_beyond) >= 2:
        kind = "INDEPENDENCE_MEASURED"
    elif len(checked_beyond) >= 2:
        kind = "INDEPENDENCE_ATTESTED"
    elif len(beyond) >= 2:
        kind = "INDEPENDENCE_INDEPENDENT"
    elif len(advancing) >= 2:
        kind = "INDEPENDENCE_UNPROVEN"
    elif beyond or checked_beyond:
        kind = "INDEPENDENCE_DECLARED_ONLY"
    else:
        kind = "INDEPENDENCE_NONE"
    return {"kind": kind, "sources": common, "deltas": deltas, "declared": declared,
            "checked": checked, "values": values, "advancing": advancing,
            "regressed": regressed, "beyond": beyond, "checked_beyond": checked_beyond,
            "measured_beyond": measured_beyond, "contradicted": contradicted,
            "within": within, "undeclared": undeclared}

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
    effect: float | None = None,
    effects: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
    sources: Mapping[str, str | os.PathLike[str]] | None = None,
    measured: Mapping[str, str | os.PathLike[str]] | None = None,
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

    ``provenance`` declares, per named effect source, *why* that source is beyond the
    subject's reach (``PROVENANCE_KINDS``). It is recorded, never proven: ``independence``
    counts the declarations so a reader can tell agreement from independence, and a source
    left undeclared is reported as such rather than quietly credited.

    ``sources`` goes a step further and makes the declaration *checkable*: it maps each
    named effect source to a path the recorder stats itself, so a ``read_only`` claim can be
    observed (``REACH_KINDS``, via ``observe_reach``) instead of sworn. A caller that names
    a writable path and declares it ``read_only`` is caught, not believed.

    ``measured`` makes the *value* itself something the recorder reads rather than believes:
    it maps each named effect source to a path the recorder opens, records the byte count it
    read (as the source's ``effect``) and a checksum over those bytes, and -- because it read
    the file -- the reach of that path too (``VALUE_KINDS``). A source named here with no
    reported value takes its value from the read; a source that also carries a reported
    value is *checked* against the read, so a number the bytes refute is ``VALUE_CONTRADICTED``
    rather than recorded. A source named in neither place is reported, and one named but
    unreadable is ``VALUE_UNKNOWN`` -- nothing is filled in.
    """
    if policy is not None and policy not in POLICIES:
        raise ValueError(f"unknown subject policy {policy!r}; choose from {POLICIES}")
    if progress is not None and not isinstance(progress, (int, float)):
        raise ValueError(f"progress must be a number or None, got {type(progress).__name__}")
    if effect is not None and not isinstance(effect, (int, float)):
        raise ValueError(f"effect must be a number or None, got {type(effect).__name__}")
    named: dict[str, float | None] = {}
    for name, value in (effects or {}).items():
        if value is not None and not isinstance(value, (int, float)):
            raise ValueError(f"effect source {name!r} must be a number or None, got "
                             f"{type(value).__name__}")
        named[str(name)] = None if value is None else float(value)
    declared: dict[str, str] = {}
    for name, kind in (provenance or {}).items():
        if not isinstance(kind, str) or kind not in PROVENANCE_KINDS:
            raise ValueError(f"unknown provenance for effect source {name!r}: {kind!r}; "
                             f"choose from {PROVENANCE_KINDS}")
        declared[str(name)] = kind
    reached: dict[str, str] = {}
    for name, source in (sources or {}).items():
        if not isinstance(source, (str, os.PathLike)):
            raise ValueError(f"source {name!r} must be a path, got {type(source).__name__}")
        reached[str(name)] = observe_reach(source)
    # Values the recorder reads for itself. Naming a path makes the value measured (or, when
    # a report is also given, checked against the read); the read also settles the source's
    # reach, so one path buys both observations. A source with no path keeps its reported
    # value, recorded but never promoted.
    observed_values: dict[str, dict[str, Any] | None] = {}
    value_kinds: dict[str, str] = {}
    for name, source in (measured or {}).items():
        if not isinstance(source, (str, os.PathLike)):
            raise ValueError(f"measured source {name!r} must be a path, got "
                             f"{type(source).__name__}")
        observed = measure(source)
        key = str(name)
        kind = _value_kind(named.get(key), observed)
        observed_values[key] = observed
        value_kinds[key] = kind
        reached[key] = observe_reach(source)
        if kind == "VALUE_MEASURED" and named.get(key) is None and observed is not None:
            named[key] = observed["bytes"]
    # Every other effect value is the caller's number, named as such: a source with no path
    # to read is reported, and the record says so rather than leaving the value unclassified.
    for key in named:
        value_kinds.setdefault(key, "VALUE_REPORTED")
    record = {
        "ev": BEAT,
        "subject": dict(subject) if subject else None,
        "progress": (None if progress is None else float(progress)),
        "effect": (None if effect is None else float(effect)),
        "effects": named,
        "provenance": declared,
        "reach": reached,
        "values": value_kinds,
        "measured": observed_values,
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
        "effect_transitions": [],
        "effect_counts": {},
        "unsubstantiated": [],
        "longest_unsubstantiated": 0,
        "effect_witnesses": {},
        "effect_sources": 0,
        "corroboration_transitions": [],
        "corroboration_counts": {},
        "splits": [],
        "uncorroborated": [],
        "independence_transitions": [],
        "independence_counts": {},
        "effect_provenance": {},
        "effect_reach": {},
        "independent_sources": [],
        "attested_sources": [],
        "contradicted_sources": [],
        "unproven_independence": [],
        "contradicted_independence": [],
        "value_provenance": {},
        "measured_values": {},
        "measured_sources": [],
        "reported_sources": [],
        "contradicted_values": [],
        "value_contradictions": [],
        "value_reported": [],
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

    # The side-effect witness: the claimed advance checked against what the recorder read
    # from the world. A sustained run of claimed advances the world does not show is the
    # inverse failure this moonshot exists to catch -- a subject reporting progress it did
    # not make. A single divergence may be lag, so the finding is the run, not the beat.
    effect_rows = [classify_effect(a, b) for a, b in zip(beats, beats[1:])]
    result["effect_transitions"] = effect_rows
    effect_counts: dict[str, int] = {}
    for row in effect_rows:
        effect_counts[row["kind"]] = effect_counts.get(row["kind"], 0) + 1
    result["effect_counts"] = effect_counts

    # Corroboration first: how many *named* sources agree about the advance. The record does
    # not claim the sources are independent -- it counts the agreement and names the split,
    # so a reader can tell an advance witnessed once from one witnessed many times. Only a
    # ledger that reads two or more sources engages the corroboration verdicts, so a
    # single-source record keeps its existing reading; independence is never silently
    # awarded to one voice.
    result["effect_sources"] = max((len(effects_of(b)) for b in beats), default=0)
    multi = result["effect_sources"] >= 2
    corr_rows = [corroborate(a, b) for a, b in zip(beats, beats[1:])]
    result["corroboration_transitions"] = corr_rows
    corr_counts: dict[str, int] = {}
    for row in corr_rows:
        corr_counts[row["kind"]] = corr_counts.get(row["kind"], 0) + 1
    result["corroboration_counts"] = corr_counts

    # Independence one level deeper than corroboration: of the sources that agree, how many
    # are declared *beyond the subject's reach*? Agreement is not independence, so this is
    # counted separately and only engaged when provenance was declared at all -- a record
    # that never claimed to know why its sources are out of reach keeps its prior reading
    # rather than being credited or penalised for a declaration it never made.
    prov_map: dict[str, str] = {}
    reach_map: dict[str, str] = {}
    for b in beats:
        prov_map.update(provenance_of(b))
        reach_map.update(reach_of(b))
    result["effect_provenance"] = prov_map
    result["effect_reach"] = reach_map
    # The check outranks the declaration: a source the recorder observed to be writable is
    # removed from the beyond-reach set however it was declared, and named as contradicted.
    contradicted = sorted(
        name for name, kind in reach_map.items()
        if kind == "REACH_WRITABLE" and prov_map.get(name) in BEYOND_REACH
    )
    attested = sorted(name for name, kind in reach_map.items() if kind == "REACH_READ_ONLY")
    result["attested_sources"] = attested
    result["contradicted_sources"] = contradicted
    result["independent_sources"] = sorted(
        name for name in set(prov_map) | set(reach_map)
        if name not in contradicted
        and (reach_map.get(name) == "REACH_READ_ONLY" or prov_map.get(name) in BEYOND_REACH)
    )
    # The value's provenance, one level past the reach check: did the recorder read the
    # bytes, or is the number the caller's? A source it read is measured; a reported value
    # with nothing to check against is reported; a report the bytes refute is contradicted.
    value_map: dict[str, str] = {}
    measured_map: dict[str, dict[str, Any]] = {}
    for b in beats:
        value_map.update(value_of(b))
        measured_map.update(measurements_of(b))
    result["value_provenance"] = value_map
    result["measured_values"] = measured_map
    result["measured_sources"] = sorted(n for n, k in value_map.items()
                                         if k == "VALUE_MEASURED")
    result["reported_sources"] = sorted(n for n, k in value_map.items()
                                         if k == "VALUE_REPORTED")
    result["contradicted_values"] = sorted(n for n, k in value_map.items()
                                            if k == "VALUE_CONTRADICTED")
    indep_rows = [independence(a, b) for a, b in zip(beats, beats[1:])]
    result["independence_transitions"] = indep_rows
    indep_counts: dict[str, int] = {}
    for row in indep_rows:
        indep_counts[row["kind"]] = indep_counts.get(row["kind"], 0) + 1
    result["independence_counts"] = indep_counts
    prov_engaged = multi and (bool(prov_map) or bool(reach_map))
    # The value axis engages only where a measurement was actually attempted: a ledger that
    # names no path has nothing the recorded value could have been checked against, so its
    # prior reading stands -- the same rule that keeps a provenance-less ledger unpenalised.
    value_engaged = multi and bool(measured_map)

    # Per interval: did the subject *claim* an advance, was any *observed* source present, and
    # did any of them actually advance? The single effect and the named sources are counted
    # together, so a stall or a false claim is refuted by whichever witness saw the work.
    declared_advances = [row.get("delta", 0.0) > 0 for row in progress_rows]
    observed_advances = [
        bool(corr_rows[i]["advancing"]) or effect_rows[i].get("observed", 0.0) > 0
        for i in range(len(effect_rows))
    ]
    observed_present = [
        bool(corr_rows[i]["sources"])
        or effect_of(beats[i]) is not None or effect_of(beats[i + 1]) is not None
        for i in range(len(effect_rows))
    ]

    # A stall is a claim the other witnesses can refute: a flat counter counts only while no
    # observed source advanced. When the world shows work the subject did not report, the
    # subject is silent, not stalled -- the two-witness rule catching a false stall.
    runs: list[int] = []
    run = 0
    for progress_row, advancing in zip(progress_rows, observed_advances):
        if progress_row["kind"] == "PROGRESS_FLAT" and not advancing:
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

    # A claimed advance no observed source supports. Counted only where a source exists and
    # was read: with no side effect declared at all, the record says nothing rather than
    # inventing a witness to contradict.
    unsubstantiated_runs: list[int] = []
    run = 0
    unsubstantiated = 0
    for declared, present, advancing in zip(declared_advances, observed_present, observed_advances):
        if declared and present and not advancing:
            run += 1
            unsubstantiated += 1
        else:
            if run:
                unsubstantiated_runs.append(run)
            run = 0
    if run:
        unsubstantiated_runs.append(run)
    result["longest_unsubstantiated"] = max(unsubstantiated_runs, default=0)
    result["unsubstantiated"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) no observed source showed"}
        for n in unsubstantiated_runs if n >= stall_after
    ]
    result["effect_witnesses"] = {
        "unsubstantiated": unsubstantiated,
        "unreported": effect_counts.get("EFFECT_UNREPORTED", 0),
    }

    # A split or a lone witness is reported only for a ledger that reads two or more sources.
    split_runs: list[int] = []
    uncorr_runs: list[int] = []
    run_s = run_u = 0
    for i, row in enumerate(corr_rows):
        if multi and row["kind"] == "CORROBORATION_SPLIT":
            run_s += 1
        else:
            if run_s:
                split_runs.append(run_s)
            run_s = 0
        if multi and row["kind"] == "CORROBORATION_SINGLE_SOURCE" and declared_advances[i]:
            run_u += 1
        else:
            if run_u:
                uncorr_runs.append(run_u)
            run_u = 0
    if run_s:
        split_runs.append(run_s)
    if run_u:
        uncorr_runs.append(run_u)
    result["splits"] = [
        {"beats": n,
         "why": f"the named effect sources contradicted each other for {n} consecutive "
                f"beats (threshold {stall_after}): some advanced while others went backwards"}
        for n in split_runs if n >= stall_after
    ]
    result["uncorroborated"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) that only one of {result['effect_sources']} named sources "
                f"witnessed: a real advance, but its independence is unestablished"}
        for n in uncorr_runs if n >= stall_after
    ]

    # Agreement that is not independence. A sustained run of corroborated advances whose
    # sources are not declared beyond the subject's reach is reported apart from a split or
    # a lone witness: the sources agree, but nothing says the subject could not have moved
    # them together. The record says "unproven", not "independent" -- and a ledger that
    # declared no provenance keeps its prior reading rather than being penalised for it.
    unproven_runs: list[int] = []
    run_p = 0
    for i, row in enumerate(indep_rows):
        if prov_engaged and row["kind"] == "INDEPENDENCE_UNPROVEN" and declared_advances[i]:
            run_p += 1
        else:
            if run_p:
                unproven_runs.append(run_p)
            run_p = 0
    if run_p:
        unproven_runs.append(run_p)
    result["unproven_independence"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) that {result['effect_sources']} named sources corroborated "
                f"but no two were shown beyond the subject's reach the same way "
                f"({len(result['attested_sources'])} checked, "
                f"{len(result['independent_sources']) - len(result['attested_sources'])} "
                f"declared only): agreement is not independence"}
        for n in unproven_runs if n >= stall_after
    ]

    # The inverse finding a *check* makes possible: a source declared beyond reach that the
    # recorder's own stat() showed it could write. A declaration defeated by an observation
    # is reported as such rather than quietly discounted -- the whole point of checking.
    contradicted_runs: list[int] = []
    run_c = 0
    for i, row in enumerate(indep_rows):
        if row["kind"] == "INDEPENDENCE_CONTRADICTED" and declared_advances[i]:
            run_c += 1
        else:
            if run_c:
                contradicted_runs.append(run_c)
            run_c = 0
    if run_c:
        contradicted_runs.append(run_c)
    result["contradicted_independence"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) and a source declared beyond its reach was read by the "
                f"recorder as writable ({', '.join(result['contradicted_sources'])}): the "
                f"declaration is defeated by the check"}
        for n in contradicted_runs if n >= stall_after
    ]

    # A reported value the bytes refute. The counterpart of a defeated declaration, one
    # level down: the reach was checked and passed, but the number the report *held* was
    # not what the recorder read. Reported as such rather than believed -- measuring is
    # only half the move; checking the claim against the measurement is the other half.
    value_contradicted_runs: list[int] = []
    run_v = 0
    for i, row in enumerate(indep_rows):
        if declared_advances[i] and any(
            row["values"].get(name) == "VALUE_CONTRADICTED" for name in row["advancing"]
        ):
            run_v += 1
        else:
            if run_v:
                value_contradicted_runs.append(run_v)
            run_v = 0
    if run_v:
        value_contradicted_runs.append(run_v)
    result["value_contradictions"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) and the recorder read bytes that refute a reported value "
                f"({', '.join(result['contradicted_values'])}): the report is defeated by "
                f"the measurement"}
        for n in value_contradicted_runs if n >= stall_after
    ]

    # An advance whose agreeing sources were all *reported*: the reach may be checked, but
    # the numbers the claim rests on are still the caller's, with no recording to check them
    # against. Engaged only where a measurement was attempted at all, so a ledger that names
    # no path keeps its prior reading rather than being penalised for a check it never made.
    value_reported_runs: list[int] = []
    run_r = 0
    for i, row in enumerate(indep_rows):
        measured_advancing = [name for name in row["advancing"]
                              if row["values"].get(name) == "VALUE_MEASURED"]
        if (value_engaged and row["advancing"] and not measured_advancing
                and declared_advances[i]):
            run_r += 1
        else:
            if run_r:
                value_reported_runs.append(run_r)
            run_r = 0
    if run_r:
        value_reported_runs.append(run_r)
    result["value_reported"] = [
        {"beats": n,
         "why": f"the subject claimed an advance on {n} consecutive beats (threshold "
                f"{stall_after}) that {len(result['reported_sources'])} reported source(s) "
                f"witnessed and none the recorder measured: reach may be checked, but the "
                f"value the claim rests on is still the caller's"}
        for n in value_reported_runs if n >= stall_after
    ]

    if not beats:
        result["verdict"] = "EMPTY"
    elif result["lost"]:
        result["verdict"] = "BROKEN"
    elif result["subject_breaks"]:
        result["verdict"] = "SUBJECT_BROKE"
    elif result["regressions"]:
        result["verdict"] = "SUBJECT_BROKE"
    elif result["splits"]:
        result["verdict"] = "SUBJECT_WITNESSES_SPLIT"
    elif result["unsubstantiated"]:
        result["verdict"] = "SUBJECT_UNSUBSTANTIATED"
    elif result["uncorroborated"]:
        result["verdict"] = "SUBJECT_UNCORROBORATED"
    elif result["contradicted_independence"]:
        result["verdict"] = "SUBJECT_INDEPENDENCE_CONTRADICTED"
    elif result["value_contradictions"]:
        result["verdict"] = "SUBJECT_VALUES_CONTRADICTED"
    elif result["unproven_independence"]:
        result["verdict"] = "SUBJECT_INDEPENDENCE_UNPROVEN"
    elif result["value_reported"]:
        result["verdict"] = "SUBJECT_VALUES_REPORTED"
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
