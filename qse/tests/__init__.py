"""QSE's adversarial test suite.

Run from the repository root:

    python3 -B -W error::ResourceWarning -m unittest discover -s qse/tests -t .

``-t .`` matters: it puts the repository root on ``sys.path`` so ``import qse``
resolves. ``-B`` matters: bytecode caches left behind by a test run show up as
stray files in the tree.
"""
