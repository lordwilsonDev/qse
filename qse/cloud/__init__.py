"""MOONSHOT-C: the same engine, pointed at a cloud bill.

The orders scenario was built around one plant's order-fulfilment workflow. This
subpackage builds the second domain, so that "question-to-validated-artifact
transformation" is a claim about an engine rather than about one dataset.

It exists because pointing QSE at cloud data found two real defects -- a planner
that guessed *orders* column names, and a comparison that would happily score a
detector built on the bill itself as an explanation for the bill. Both are now
declarations the caller makes instead of guesses the engine makes. See
``docs/D1-failure-to-leverage.md``, entry ``qse-d1-0004``.
"""

from __future__ import annotations
