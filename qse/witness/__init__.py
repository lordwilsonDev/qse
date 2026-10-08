"""The Witness: continuity a machine can attest about itself because it refuses to.

MOONSHOT-M. See ``docs/moonshot-m.md`` for the inversions this was built from, and
``moonshot_machine.py`` for the one-command run.
"""

from . import continuity, power
from .continuity import BEAT, DEFAULT_INTERVAL, SLACK, absences, beat, boot_time, classify, verify
from .power import Sleep, covering, load as load_power_log, parse as parse_power_log, read as read_power_log

__all__ = [
    "continuity", "power",
    "BEAT", "DEFAULT_INTERVAL", "SLACK",
    "absences", "beat", "boot_time", "classify", "verify",
    "Sleep", "covering", "load_power_log", "parse_power_log", "read_power_log",
]
