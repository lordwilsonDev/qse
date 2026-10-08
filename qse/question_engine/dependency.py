"""Slot dependencies, and what an unanswered slot actually blocks.

The seven slots are not independent. A scope cannot be judged without a referent;
authority is authority *over a claim*, so it depends on the proposition; who
consumes a result depends on how far the result ranges. Knowing this lets QSE say
which question to answer *first* rather than listing every gap flatly.

The table below is acyclic by construction, which is why ``cycles`` exists: it
proves the acyclicity instead of asserting it, and it will catch a future edit
that introduces a circular definition.
"""

from __future__ import annotations

from ..core.question import SLOTS, Question

SLOT_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "referential": (),
    "proposition": ("referential",),
    "scope": ("referential",),
    "authority": ("proposition",),
    "obligation": ("proposition", "scope"),
    "temporal": ("scope",),
    "consumption": ("scope", "authority"),
}


def find_cycles(table: dict[str, tuple[str, ...]]) -> list[list[str]]:
    """Every dependency cycle in a slot table, each reported once.

    Iterative depth-first search with an explicit stack, so a future table with a
    long chain cannot exhaust the recursion limit.
    """
    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    state: dict[str, int] = {}  # 0 unvisited, 1 on stack, 2 done

    for start in table:
        if state.get(start, 0) != 0:
            continue
        path: list[str] = []
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            node, index = stack.pop()
            if index == 0:
                state[node] = 1
                path.append(node)
            deps = table.get(node, ())
            if index < len(deps):
                stack.append((node, index + 1))
                nxt = deps[index]
                if nxt not in table:
                    continue
                if state.get(nxt, 0) == 1:
                    found = path[path.index(nxt):] + [nxt]
                    key = tuple(sorted(set(found)))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        cycles.append(found)
                elif state.get(nxt, 0) == 0:
                    stack.append((nxt, 0))
            else:
                state[node] = 2
                path.pop()
    return cycles


def dependencies(question: Question) -> dict[str, list[str]]:
    """For each slot, the slots it is defined in terms of."""
    return {name: [d for d in SLOT_DEPENDENCIES.get(name, ()) if d in SLOTS] for name in SLOTS}


def blocked_by(question: Question) -> dict[str, list[str]]:
    """For each unanswered slot, the unanswered slots it waits on.

    Answers the practical question: *which gap do I close first?* A slot absent
    from this mapping is unanswered but not waiting on anything else.
    """
    out: dict[str, list[str]] = {}
    for name in SLOTS:
        if question.slots[name].filled:
            continue
        waiting = [d for d in SLOT_DEPENDENCIES.get(name, ()) if not question.slots[d].filled]
        out[name] = waiting
    return out


def roots(question: Question) -> list[str]:
    """Unanswered slots nothing else is waiting behind -- answer these first."""
    waiting = blocked_by(question)
    return sorted(name for name, deps in waiting.items() if not deps)


def cycles(question: Question) -> list[list[str]]:
    return find_cycles(SLOT_DEPENDENCIES)


def circular(question: Question) -> list[str]:
    """Slots involved in any dependency cycle. Empty for a well-formed table."""
    involved: list[str] = []
    for cycle in cycles(question):
        for name in cycle:
            if name not in involved:
                involved.append(name)
    return involved
