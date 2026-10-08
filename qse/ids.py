"""Canonical identifiers, hashing and time.

Every id in QSE is derived from the content it names, so the same input always
produces the same id and a replay can recompute every id it reads. Nothing in
QSE uses ``random`` and nothing reads the wall clock except through ``utcnow``,
which tests can pin with ``freeze``.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta, timezone

VERSION = "qse-0.1"
UTC = timezone.utc

_SEP = "\x1f"
_WS = re.compile(r"\s+")
_EDGE = re.compile(r"^[^0-9a-z]+|[^0-9a-z]+$")

_CLOCK: datetime | None = None


def freeze(moment: datetime | None) -> None:
    """Pin the clock so a run is reproducible. ``None`` restores the real clock."""
    global _CLOCK
    _CLOCK = moment


def utcnow() -> datetime:
    return _CLOCK if _CLOCK is not None else datetime.now(UTC)


def iso(moment: datetime) -> str:
    """Second-resolution UTC, always with a trailing Z."""
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_ts(text: object) -> datetime | None:
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        got = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return got.replace(tzinfo=UTC) if got.tzinfo is None else got.astimezone(UTC)


def plus(moment: datetime, hours: float) -> datetime:
    return moment + timedelta(hours=hours)


def canon(text: object) -> str:
    """Fold case and accents, collapse whitespace, trim edge punctuation."""
    if text is None:
        return ""
    folded = unicodedata.normalize("NFKD", str(text))
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = _WS.sub(" ", folded).strip().lower()
    return _EDGE.sub("", folded)


def digest(*parts: object, n: int = 16) -> str:
    body = _SEP.join(canon(p) for p in parts)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:n]


def new_id(prefix: str, *parts: object, n: int = 12) -> str:
    return f"{prefix}-{digest(*parts, n=n)}"


def slug(text: object, width: int = 40) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", canon(text))
    return out.strip("-")[:width].strip("-")
