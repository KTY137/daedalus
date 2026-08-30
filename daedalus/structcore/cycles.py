# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Directed cycle structure of the import graph. Stdlib only.

FOUND BY AUDIT 2026-07-30 (Aristaeus), and it is the reason this file exists:
``structcore`` had **no cycle detection at all**. What it had was

* ``import_edges`` / ``import_edges_reverse`` -- the data, complete and correct,
  including the edges that live inside function bodies;
* ``topology.spectral_partition``, which builds ``nx.Graph()`` and labels itself
  "undirected projection of directed import edges". It discards DIRECTION, which
  is the only thing a cycle is made of;
* ``graph.py``'s ``seen = {rel}`` -- a cycle *guard*, so a walk terminates. Not a
  detector.

So the one structural question the repo actually had -- "these 13 modules form a
cycle, what do I cut?" -- could not be asked of the tool whose job is answering
"what should I distill?". It was answered by a 60-line throwaway script instead,
and every number in that audit came from code the product does not contain.

The wrong lens was also measurably the wrong lens. Undirected articulation points
strand at most 5 of 150 modules (the worst is ``atomic``). Directed reachability
loss puts ``core`` at 938 of 3,219 ordered pairs -- **29%**, nearly 2x the next
module. ``core`` is a HUB, not a BRIDGE, and an undirected projection cannot see
the difference.

Deliberately stdlib-only and iterative:

* **stdlib**, because ``topology.py`` returns ``_empty()`` when networkx is
  absent, and a structural fact as basic as "is there a cycle" must not depend on
  an optional extra being installed.
* **iterative**, because recursive Tarjan on a 456-node graph with long chains
  is a ``RecursionError`` waiting for the repo to grow -- and it would surface as
  a crash in whatever tool asked, not here.
* **deterministic**, because these outputs get committed to receipts and diffed
  between runs. Set iteration order is not a basis for a receipt.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "strongly_connected_components",
    "nontrivial_components",
    "self_loops",
    "cycle_report",
    "component_edges",
]


def strongly_connected_components(
    edges: Mapping[str, Iterable[str]],
) -> tuple[tuple[str, ...], ...]:
    """Every SCC of the directed graph, largest first, each sorted.

    Tarjan's algorithm, iterative. Nodes are every key plus every target, so a
    module that is only ever imported still appears -- a leaf is a component of
    one, and omitting it would make the component count depend on which side of
    an edge a module happens to sit.

    Ordering is total and content-derived: by descending size, then
    lexicographically by the component's own members. Two runs over the same
    graph produce byte-identical output.
    """
    nodes: list[str] = []
    seen_node: set[str] = set()
    for src in edges:
        if src not in seen_node:
            seen_node.add(src)
            nodes.append(src)
    for src in edges:
        for dst in edges[src] or ():
            if dst not in seen_node:
                seen_node.add(dst)
                nodes.append(dst)
    nodes.sort()

    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[tuple[str, ...]] = []
    counter = 0

    for root in nodes:
        if root in index:
            continue
        # (node, iterator over its sorted successors). The iterator is what makes
        # this iterative: the "recursive call" is pushing a frame, and the
        # "return" is resuming the parent's iterator where it left off.
        work: list[tuple[str, Any]] = [(root, iter(sorted(edges.get(root) or ())))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        on_stack.add(root)

        while work:
            node, successors = work[-1]
            advanced = False
            for nxt in successors:
                if nxt not in index:
                    index[nxt] = low[nxt] = counter
                    counter += 1
                    stack.append(nxt)
                    on_stack.add(nxt)
                    work.append((nxt, iter(sorted(edges.get(nxt) or ()))))
                    advanced = True
                    break
                if nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
            if advanced:
                continue
            # Successors exhausted: this node is done. If it is a root of its
            # component, peel the component off the stack.
            work.pop()
            if low[node] == index[node]:
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                result.append(tuple(sorted(component)))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])

    result.sort(key=lambda comp: (-len(comp), comp))
    return tuple(result)


def self_loops(edges: Mapping[str, Iterable[str]]) -> tuple[str, ...]:
    """Modules that import themselves.

    Reported separately because a self-loop is a one-node SCC and would
    otherwise be indistinguishable from an ordinary leaf -- and a module
    importing itself is a real finding, not a trivial component.
    """
    return tuple(sorted(src for src in edges if src in (edges[src] or ())))


def nontrivial_components(
    edges: Mapping[str, Iterable[str]],
) -> tuple[tuple[str, ...], ...]:
    """SCCs that are actually cycles: more than one member, or a self-loop."""
    loops = set(self_loops(edges))
    return tuple(c for c in strongly_connected_components(edges)
                 if len(c) > 1 or (len(c) == 1 and c[0] in loops))


def component_edges(
    edges: Mapping[str, Iterable[str]],
    component: Sequence[str],
) -> tuple[tuple[str, str], ...]:
    """The edges induced by ``component`` -- i.e. the ones a cut must consider.

    This is the input to any feedback-arc question. Sorted, so a proposed cut can
    be quoted in a review and re-derived later.
    """
    members = set(component)
    out: list[tuple[str, str]] = []
    for src in component:
        for dst in edges.get(src) or ():
            if dst in members:
                out.append((src, dst))
    return tuple(sorted(set(out)))


def cycle_report(index: Mapping[str, Any] | None = None,
                 repo_root: str = ".") -> dict[str, Any]:
    """The cycle structure of a built index, as a receipt-shaped dict.

    Reads ``index["import_edges"]``, which is the layer that ALREADY includes
    function-body imports -- ``parse._import_records`` walks every node with
    ``ast.walk`` and records no scope. That is why this is worth computing at all:
    a cycle detector fed only top-level imports would have reported this repo as
    acyclic, which is true at import time and false as a change-propagation
    question. 37% of internal edges live inside function bodies.

    Passing ``index`` avoids a rebuild; omitting it uses the process-wide cache.
    """
    if index is None:
        from .index import cached_index
        index = cached_index(repo_root)
    edges: Mapping[str, Iterable[str]] = index.get("import_edges") or {}
    components = nontrivial_components(edges)
    loops = self_loops(edges)
    return {
        "n_modules": len({*edges, *(d for s in edges for d in edges[s] or ())}),
        "n_edges": sum(len(list(edges[s] or ())) for s in edges),
        "n_cyclic_components": len(components),
        "self_loops": list(loops),
        "largest_component_size": len(components[0]) if components else 0,
        "components": [
            {
                "size": len(comp),
                "modules": list(comp),
                "induced_edges": [list(e) for e in component_edges(edges, comp)],
            }
            for comp in components
        ],
    }
