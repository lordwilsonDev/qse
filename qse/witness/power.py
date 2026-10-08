"""The independent witness: what the operating system recorded about sleep and wake.

A machine's own heartbeat cannot say whether a gap in it was a *sleep* or a *death* --
from inside the process both look like "no beats for a while". So the recorder does
not trust itself: it asks the OS power log, which the kernel's power manager writes
and the witnessed process does not. That is the whole idea, and this module is the
part that reads the second witness.

macOS only, and it degrades rather than raising. On a machine with no power log (or
not a Mac) ``load()`` returns an empty list, which the verifier reports as "the OS
recorded no sleep in this window" -- never as "there was no gap". An empty witness is
a fact about the witness, not about continuity.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

#: ``<timestamp>  <event>  <details>`` -- the event column is the system power
#: manager's own word, one of Sleep / Wake / DarkWake.
_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} [+-]\d{4})\s+"
    r"(?P<event>Sleep|Wake|DarkWake)\b"
)


@dataclass(frozen=True)
class Sleep:
    """One sleep interval as the OS recorded it. ``woke`` is None if still asleep."""

    entered: float
    woke: float | None
    reason: str = ""

    def overlaps(self, start: float, end: float) -> bool:
        """True when any part of this interval falls inside ``[start, end]``."""
        woke = self.woke if self.woke is not None else float("inf")
        return self.entered <= end and woke >= start

    def to_dict(self) -> dict:
        return {"entered": self.entered, "woke": self.woke, "reason": self.reason}


def _epoch(stamp: str) -> float | None:
    try:
        return datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S %z").timestamp()
    except ValueError:
        return None


def parse(text: str) -> list[Sleep]:
    """Sleep intervals from a ``pmset -g log`` dump.

    A ``Sleep`` opens an interval; the next ``Wake`` or ``DarkWake`` closes it. A
    sleep with no recorded wake is left open (``woke`` None) rather than guessed at,
    because that is exactly the ambiguous case the recorder exists to surface.
    """
    opened: float | None = None
    out: list[Sleep] = []
    for raw in text.splitlines():
        match = _LINE.match(raw.strip())
        if not match:
            continue
        when = _epoch(match.group("ts"))
        if when is None:
            continue
        if match.group("event") == "Sleep":
            if opened is None:
                opened = when
        elif opened is not None:  # Wake or DarkWake closes an open sleep
            out.append(Sleep(entered=opened, woke=when, reason="from the OS power log"))
            opened = None
    if opened is not None:
        out.append(Sleep(entered=opened, woke=None, reason="still asleep at the end of the log"))
    return out


def read() -> str:
    """The raw OS power log, or ``""`` when it cannot be read. Never raises."""
    try:
        done = subprocess.run(
            ["pmset", "-g", "log"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


#: Seconds a parsed power log is reused before it is read again. ``pmset -g log`` is
#: a six-figure-line dump and a witness that re-shells it on every beat would spend
#: more time reading about the machine than watching it. The TTL keeps a daemon fresh
#: without paying that cost per call; pass ``refresh=True`` to bypass it.
CACHE_TTL = 30.0
_CACHE: tuple[float, list[Sleep]] | None = None


def load(*, refresh: bool = False) -> list[Sleep]:
    """The sleep intervals the OS currently records. Empty is a valid answer.

    Cached for ``CACHE_TTL`` seconds (see above). The cache holds *this witness's*
    reading, never the answer to a continuity question, so a stale cache can only
    delay noticing a sleep -- it can never turn an unexplained gap into a sleep.
    """
    global _CACHE
    now = time.monotonic()
    if not refresh and _CACHE is not None and now - _CACHE[0] < CACHE_TTL:
        return list(_CACHE[1])
    sleeps = parse(read())
    _CACHE = (now, sleeps)
    return list(sleeps)


def covering(sleeps: Sequence[Sleep], start: float, end: float) -> list[Sleep]:
    return [s for s in sleeps if s.overlaps(start, end)]
