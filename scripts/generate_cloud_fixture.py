#!/usr/bin/env python3
"""Write the cloud cost fixture into ``examples/``.

Reproduces ``examples/cloud_fit.json`` and ``examples/cloud_holdout.json`` byte for
byte from the fixed seeds in ``qse/cloud/scenario.py``. The scenario itself -- what
the confounds are, why one column is excluded -- is documented there, because that
is where a reader will look for it. This file only writes it out.

    python3 scripts/generate_cloud_fixture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from qse.cloud import scenario  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    del argv
    out = Path(__file__).resolve().parents[1] / "examples"
    fit, hold = scenario.write(out)
    print(f"wrote {fit} ({len(scenario.fit_rows())} rows, seed {scenario.FIT_SEED})")
    print(f"wrote {hold} ({len(scenario.holdout_rows())} rows, seed {scenario.HOLDOUT_SEED})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
