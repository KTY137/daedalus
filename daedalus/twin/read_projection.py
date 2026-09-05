"""Read-only graph projection of one exact KnowledgeForest/Fourfold view.

This module does not create another graph authority.  ``KnowledgeForest`` is
the compiled IR, :func:`fourfold_from_knowledge_forest` supplies the canonical
four-plane membership and assurance status, and this file only shapes those
records for an interactive renderer.  Hyperedges stay hyperedges: the read
model counts them but never expands a clone group into invented pairwise
relations.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Mapping

from ..structcore.forest import ForestNode, build_knowledge_forest
from .contracts import FOURFOLD_PLANES
from .legacy_forest import fourfold_from_knowledge_forest


READ_SCHEMA = "daedalus-fourfold-read/1"


def _rank(node: ForestNode) -> tuple[float, int, str]:
    attributes = node.attributes
    try:
        heat = float(attributes.get("heat_score", 0.0) or 0.0)
    except (TypeError, ValueError):
        heat = 0.0
    try:
        fan_in = int(attributes.get("fan_in", 0) or 0)
    except (TypeError, ValueError):
        fan_in = 0
    return (-heat, -fan_in, node.id)


def _bounded_nodes(
    groups: Mapping[str, list[ForestNode]], max_nodes: int | None
) -> list[ForestNode]:
    """Select a deterministic, plane-balanced overview.

    A single global heat ranking would make the bounded "Fourfold" view a code
    graph again: type and knowledge nodes carry no comparable churn score.  A
    round-robin over independently ranked planes keeps every observed plane
    visible while preserving the strongest nodes within each plane.  ``None``
    is the explicit whole-graph path and performs no selection at all.
    """

    ordered = {
        plane: sorted(groups.get(plane, ()), key=_rank)
        for plane in FOURFOLD_PLANES
    }
    total = sum(len(nodes) for nodes in ordered.values())
    if max_nodes is None or max_nodes >= total:
        return [node for plane in FOURFOLD_PLANES for node in ordered[plane]]

    chosen: list[ForestNode] = []
    cursor = {plane: 0 for plane in FOURFOLD_PLANES}
    while len(chosen) < max_nodes:
        moved = False
        for plane in FOURFOLD_PLANES:
            index = cursor[plane]
            if index >= len(ordered[plane]):
                continue
            chosen.append(ordered[plane][index])
            cursor[plane] = index + 1
            moved = True
            if len(chosen) == max_nodes:
                break
        if not moved:
            break
    return chosen


def _number(value: Any, *, integer: bool = False) -> float | int:
    try:
        return int(value or 0) if integer else float(value or 0.0)
    except (TypeError, ValueError):
        return 0 if integer else 0.0


def fourfold_read_projection(
    index: Mapping[str, Any],
    *,
    repository_id: str,
    created_at: str,
    max_nodes: int | None = 800,
) -> dict[str, Any]:
    """Return a bounded or complete renderer projection of a Fourfold view.

    The legacy Forest has no authoritative source-tree artifact reference.  Its
    content digest is therefore used as the exact 64-character revision of
    this *compiled read*, and ``revision_basis`` says so explicitly.  The value
    must never be presented as a Git commit or candidate-tree identity.
    """

    if max_nodes is not None and max_nodes < 1:
        raise ValueError("max_nodes must be positive or None")

    forest = build_knowledge_forest(index)
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id=repository_id,
        source_revision=forest.content_sha256,
        created_at=created_at,
        trace_id=f"fourfold-read:{repository_id}",
    )

    plane_by_node = {
        node_id: plane.plane
        for plane in snapshot.planes
        for node_id in plane.node_ids
    }
    groups: dict[str, list[ForestNode]] = defaultdict(list)
    for node in forest.nodes:
        groups[plane_by_node[node.id]].append(node)

    selected = _bounded_nodes(groups, max_nodes)
    kept = {node.id for node in selected}
    graph_nodes = []
    for node in selected:
        attributes = node.attributes
        graph_nodes.append({
            "id": node.id,
            "plane": plane_by_node[node.id],
            "kind": node.kind,
            "language": str(attributes.get("language", "") or ""),
            "loc": _number(attributes.get("loc"), integer=True),
            "score": _number(attributes.get("heat_score")),
            "fan_in": _number(attributes.get("fan_in"), integer=True),
        })

    eligible_edges = [
        edge for edge in forest.edges
        if edge.source in kept and edge.target in kept
    ]
    graph_edges = []
    for edge in eligible_edges:
        source_plane = plane_by_node[edge.source]
        target_plane = plane_by_node[edge.target]
        graph_edges.append({
            "source": edge.source,
            "target": edge.target,
            "relation": edge.relation,
            "directed": edge.directed,
            "weight": edge.weight,
            "cross_plane": source_plane != target_plane,
            "assurance": "verified" if source_plane != target_plane else "observed",
        })

    shown_by_plane = defaultdict(int)
    for node in selected:
        shown_by_plane[plane_by_node[node.id]] += 1

    planes = []
    for plane in snapshot.planes:
        planes.append({
            "plane": plane.plane,
            "status": plane.status,
            "reason": plane.reason,
            "node_count": len(plane.node_ids),
            "shown_count": shown_by_plane[plane.plane],
            "relation_count": len(plane.relation_sha256s),
        })

    total_nodes = len(forest.nodes)
    total_edges = len(forest.edges)
    module_total = len(snapshot.plane_map["code"].node_ids)
    modules_shown = shown_by_plane["code"]
    return {
        "schema": READ_SCHEMA,
        "repository_id": snapshot.repository_id,
        "snapshot_sha256": snapshot.digest,
        "forest_sha256": snapshot.source_forest_sha256,
        "revision": snapshot.source_revision,
        "revision_basis": "forest-content",
        "assurance": "legacy-forest-projection",
        "planes": planes,
        "graph": {
            "nodes": graph_nodes,
            "edges": graph_edges,
            "n_nodes_total": total_nodes,
            "n_nodes_shown": len(graph_nodes),
            "n_modules_total": module_total,
            "n_modules_shown": modules_shown,
            "n_edges_total": total_edges,
            "n_edges_eligible": len(eligible_edges),
            "n_edges_offmap": total_edges - len(eligible_edges),
            "n_hyperedges_total": len(forest.hyperedges),
            "n_bindings_total": len(snapshot.bindings),
            "truncated": len(graph_nodes) < total_nodes,
            "scope": "all" if max_nodes is None else "bounded",
        },
    }


__all__ = ["READ_SCHEMA", "fourfold_read_projection"]
