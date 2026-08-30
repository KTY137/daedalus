# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Optional, read-only spectral analysis of the structural import graph.

This module is an analysis/visualization aid.  A low graph cut does *not*
establish independent edit scopes, semantic ownership, or conflict-free Git
branches, so callers must never treat its partitions as a write-safety proof.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .graph import _graph_nodes
from .index import cached_index

logger = logging.getLogger(__name__)

try:
    import networkx as nx
    import numpy as np
    from scipy.sparse.linalg import eigsh

    HAVE_MATH = True
except ImportError:
    HAVE_MATH = False

DEFAULT_MAX_NODES = 10_000


def _empty(reason: str, *, node_count: int = 0, edge_count: int = 0) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "method": "unavailable",
        "graph_type": "undirected projection of directed import edges",
        "node_count": node_count,
        "edge_count": edge_count,
        "connected_components": 0,
        "partition_a": [],
        "partition_b": [],
        "fiedler_values": {},
        "partition_values": {},
        "eigenvalues": [],
        "algebraic_connectivity": None,
        "cut_edges": 0,
        "conductance": None,
    }


def _balanced_component_cut(components: list[set[str]]) -> tuple[list[str], list[str]]:
    """Assign whole disconnected components to two roughly balanced sides."""
    sides: tuple[list[str], list[str]] = ([], [])
    for component in sorted(components, key=lambda c: (-len(c), sorted(c))):
        target = 0 if len(sides[0]) <= len(sides[1]) else 1
        sides[target].extend(sorted(component))
    return sorted(sides[0]), sorted(sides[1])


def _sweep_cut(
    graph: "nx.Graph",
    ordered_nodes: list[str],
    *,
    min_partition_fraction: float,
) -> tuple[list[str], list[str], int, float | None]:
    """Choose the best conductance cut along the Fiedler ordering.

    A sweep cut is more stable than splitting solely on the arbitrary sign of
    an eigenvector and avoids pathological one-node partitions when possible.
    """
    n = len(ordered_nodes)
    min_size = max(1, math.ceil(n * min_partition_fraction))
    max_size = n - min_size
    if max_size < min_size:
        min_size, max_size = 1, n - 1

    total_volume = sum(dict(graph.degree()).values())
    side_a: set[str] = set()
    volume_a = 0
    cut_edges = 0
    best: tuple[float, int, int] | None = None

    for position, node in enumerate(ordered_nodes[:-1], start=1):
        for neighbor in graph.neighbors(node):
            cut_edges += -1 if neighbor in side_a else 1
        side_a.add(node)
        volume_a += graph.degree(node)

        if position < min_size or position > max_size:
            continue
        volume_b = total_volume - volume_a
        denominator = min(volume_a, volume_b)
        conductance = (cut_edges / denominator) if denominator else float("inf")
        # Prefer lower conductance, then the more balanced cut.
        candidate = (conductance, abs(n - 2 * position), position)
        if best is None or candidate < best:
            best = candidate

    split = best[2] if best is not None else max(1, n // 2)
    partition_a = sorted(ordered_nodes[:split])
    partition_b = sorted(ordered_nodes[split:])
    cut = nx.cut_size(graph, partition_a, partition_b)
    conductance = None if best is None or not math.isfinite(best[0]) else float(best[0])
    return partition_a, partition_b, int(cut), conductance


def spectral_partition(
    repo_root: str,
    *,
    idx: dict[str, Any] | None = None,
    max_nodes: int = DEFAULT_MAX_NODES,
    min_partition_fraction: float = 0.10,
) -> dict[str, Any]:
    """Analyze the import graph and return an honest two-way visualization cut.

    ``idx`` lets API callers reuse the exact project-scoped structural index
    (including ``center`` and ``ignore`` rules).  The computation uses a sparse
    normalized Laplacian; it deliberately refuses oversized graphs instead of
    allocating the dense ``N x N`` matrix used by the prototype.
    """
    if not HAVE_MATH:
        return _empty("install the 'math' extra (numpy, scipy, networkx)")
    if max_nodes < 2:
        raise ValueError("max_nodes must be at least 2")
    if not 0 <= min_partition_fraction < 0.5:
        raise ValueError("min_partition_fraction must be in [0, 0.5)")

    index = idx if idx is not None else cached_index(repo_root)
    nodes = sorted(_graph_nodes(index))
    if not nodes:
        return _empty("the structural import graph is empty")
    if len(nodes) > max_nodes:
        return _empty(
            f"graph has {len(nodes)} nodes; synchronous spectral limit is {max_nodes}",
            node_count=len(nodes),
        )

    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    for source, targets in (index.get("import_edges") or {}).items():
        if source not in graph:
            continue
        for target in targets:
            if target in graph and target != source:
                graph.add_edge(source, target)

    edge_count = graph.number_of_edges()
    components = [set(component) for component in nx.connected_components(graph)]
    component_count = len(components)
    common = {
        "available": True,
        "graph_type": "undirected projection of directed import edges",
        "node_count": len(nodes),
        "edge_count": edge_count,
        "connected_components": component_count,
    }

    if len(nodes) == 1:
        node = nodes[0]
        return {
            **common,
            "method": "singleton",
            "reason": "a one-node graph has no Fiedler vector",
            "partition_a": [node],
            "partition_b": [],
            "fiedler_values": {node: None},
            "partition_values": {node: 1.0},
            "eigenvalues": [0.0],
            "algebraic_connectivity": None,
            "cut_edges": 0,
            "conductance": None,
        }

    if component_count > 1:
        partition_a, partition_b = _balanced_component_cut(components)
        side_a = set(partition_a)
        return {
            **common,
            "method": "connected_components",
            "reason": (
                "the graph is disconnected; no unique Fiedler vector exists, "
                "so whole components were balanced without cutting edges"
            ),
            "partition_a": partition_a,
            "partition_b": partition_b,
            "fiedler_values": {node: None for node in nodes},
            "partition_values": {
                node: (1.0 if node in side_a else -1.0) for node in nodes
            },
            # A disconnected graph has one zero eigenvalue per component.  Do
            # not fabricate the uncomputed remainder of the spectrum.
            "eigenvalues": [0.0] * min(component_count, 8),
            "algebraic_connectivity": 0.0,
            "cut_edges": 0,
            "conductance": 0.0,
        }

    laplacian = nx.normalized_laplacian_matrix(graph).astype(float)
    try:
        if len(nodes) <= 8:
            eigenvalues, eigenvectors = np.linalg.eigh(laplacian.toarray())
        else:
            count = min(6, len(nodes) - 1)
            eigenvalues, eigenvectors = eigsh(laplacian, k=count, which="SM")
            order = np.argsort(eigenvalues)
            eigenvalues = eigenvalues[order]
            eigenvectors = eigenvectors[:, order]
    except Exception as exc:
        logger.warning("Spectral analysis failed for %s: %s", repo_root, exc)
        return _empty(
            f"sparse eigensolver failed: {exc}",
            node_count=len(nodes),
            edge_count=edge_count,
        )

    fiedler = np.asarray(eigenvectors[:, 1]).reshape(-1)
    fiedler_values = {node: float(fiedler[i]) for i, node in enumerate(nodes)}
    ordered = sorted(nodes, key=lambda node: (fiedler_values[node], node))
    partition_a, partition_b, cut_edges, conductance = _sweep_cut(
        graph,
        ordered,
        min_partition_fraction=min_partition_fraction,
    )
    side_a = set(partition_a)

    return {
        **common,
        "method": "normalized_laplacian_sweep",
        "reason": (
            "analysis-only graph cut; it does not prove semantic independence "
            "or conflict-free edit scopes"
        ),
        "partition_a": partition_a,
        "partition_b": partition_b,
        "fiedler_values": fiedler_values,
        "partition_values": {
            node: (1.0 if node in side_a else -1.0) for node in nodes
        },
        "eigenvalues": [float(value) for value in eigenvalues],
        "algebraic_connectivity": float(eigenvalues[1]),
        "cut_edges": cut_edges,
        "conductance": conductance,
    }
