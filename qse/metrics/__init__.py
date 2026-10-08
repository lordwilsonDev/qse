"""QSE metrics: QBY, BSR, EC, BC, VI, OC and the profile behind them.

Every metric takes a replayable ``State`` and returns the same shape --
``value``, ``numerator``, ``denominator``, ``definition`` -- so six numbers can
be read side by side without six dialects. When a denominator is zero the value
is ``None``: an empty sample is UNKNOWN, never 0.0 and never 1.0.
"""

from .blindspots import blindspots
from .build_quality import EXECUTABLE_KINDS, build_quality
from .north_star import LIMITS, bc, bsr, ec, oc, qby, scorecard, vi
from .question_quality import measure, question_quality, ratio
from .verification import is_usable, verification

__all__ = [
    "blindspots",
    "build_quality", "EXECUTABLE_KINDS",
    "measure", "question_quality", "ratio",
    "verification", "is_usable",
    "scorecard", "qby", "bsr", "ec", "bc", "vi", "oc", "LIMITS",
]
