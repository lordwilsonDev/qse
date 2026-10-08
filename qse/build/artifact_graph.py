"""The artifact dependency graph.

An artifact may declare what it ``requires``. This module answers the two
questions that matters for: what order can they be built in, and which
requirements are not actually built yet. The second is the one that gets
ignored, and it is the one that produces a "verified" artifact resting on
nothing.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..core.artifact import Artifact

__all__ = ["Graph", "build", "roots", "leaves", "order", "cycles", "unbuilt_dependencies"]


@dataclass
class Graph:
    nodes: list[str] = field(default_factory=list)
    #: (required, requiring) -- the requirement comes first.
    edges: list[tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "nodes": list(self.nodes),
            "edges": [list(edge) for edge in self.edges],
            "roots": roots(self),
            "leaves": leaves(self),
            "n": len(self.nodes),
        }

    def outgoing(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {node: [] for node in self.nodes}
        for required, requiring in self.edges:
            out.setdefault(required, []).append(requiring)
        return out

    def incoming(self) -> dict[str, list[str]]:
        incoming: dict[str, list[str]] = {node: [] for node in self.nodes}
        for required, requiring in self.edges:
            incoming.setdefault(requiring, []).append(required)
        return incoming


def build(artifacts: Iterable[Artifact]) -> Graph:
    """Edges from each artifact's ``requires``, ignoring ids that are not here."""
    items = list(artifacts)
    known = {item.aid for item in items}
    nodes = sorted(known)
    edges: list[tuple[str, str]] = []
    for item in items:
        for required in item.requires:
            edge = (str(required), item.aid)
            if required in known and edge not in edges:
                edges.append(edge)
    return Graph(nodes=nodes, edges=sorted(edges))


def roots(graph: Graph) -> list[str]:
    """Artifacts nothing else is required for: safe to build first."""
    has_incoming = {requiring for _, requiring in graph.edges}
    return sorted(node for node in graph.nodes if node not in has_incoming)


def leaves(graph: Graph) -> list[str]:
    """Artifacts that require nothing: safe to build last."""
    has_outgoing = {required for required, _ in graph.edges}
    return sorted(node for node in graph.nodes if node not in has_outgoing)


def order(graph: Graph) -> list[str]:
    """Topological build order. Raises ``ValueError`` naming the cycle."""
    incoming = graph.incoming()
    remaining = {node: set(deps) for node, deps in incoming.items()}
    ready = sorted(node for node, deps in remaining.items() if not deps)
    built: list[str] = []
    while ready:
        node = ready.pop(0)
        built.append(node)
        for dependent in sorted(graph.outgoing().get(node, [])):
            remaining[dependent].discard(node)
            if not remaining[dependent] and dependent not in built and dependent not in ready:
                ready.append(dependent)
                ready.sort()
    if len(built) != len(graph.nodes):
        stuck = sorted(set(graph.nodes) - set(built))
        found = cycles(graph)
        raise ValueError(f"artifact graph has a cycle among {stuck}: {found[0] if found else stuck}")
    return built


def cycles(graph: Graph) -> list[list[str]]:
    """Every cycle reachable from the roots, each as a list of node ids."""
    found: list[list[str]] = []
    outgoing = graph.outgoing()
    colour: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> None:
        colour[node] = 1
        stack.append(node)
        for nxt in sorted(outgoing.get(node, [])):
            if colour.get(nxt, 0) == 1:
                start = stack.index(nxt)
                cycle = stack[start:] + [nxt]
                if cycle not in found:
                    found.append(cycle)
            elif colour.get(nxt, 0) == 0:
                visit(nxt)
        stack.pop()
        colour[node] = 2

    for node in sorted(graph.nodes):
        if colour.get(node, 0) == 0:
            visit(node)
    return found


def unbuilt_dependencies(artifacts: Iterable[Artifact]) -> list[tuple[str, str]]:
    """``(artifact, missing requirement)`` for requirements not built here.

    "Built" means a constructed artifact with that id exists in the same set.
    """
    items = list(artifacts)
    constructed = {item.aid for item in items if item.constructed()}
    missing: list[tuple[str, str]] = []
    for item in items:
        for required in item.requires:
            if str(required) not in constructed:
                missing.append((item.aid, str(required)))
    return sorted(missing)
