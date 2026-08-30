# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The labeled-property-graph projection of a Knowledge Forest.

WHAT THIS IS, AND WHAT IT IS NOT.  The Forest is the identity: an immutable,
content-addressed, byte-deterministic snapshot (invariant 6 -- atomic
revisions).  This module is a LENS over it -- the explicit mapping from the
Forest's multiplex-graph contract onto the labeled-property-graph (LPG) data
model that Neo4j, ISO GQL, SQL/PGQ, CPG tooling and most graph libraries
speak.  The projection is DISPOSABLE and REGENERATED per revision; it is
never a store, never candidate identity, and never a second source of truth.
That is why there is no graph-database dependency here and must not be one:
a mutable engine would reintroduce exactly the partial-graph-state problem
the Forest's snapshot semantics exist to close, and its storage is not
byte-deterministic, which would break receipt hashing.

Three mapping decisions carry the honesty of the projection:

* **Hyperedges are reified, never expanded.**  A clone group of N files is
  one ``hyperedge``-labeled node plus N ``hyperedge_member`` relationships
  -- NOT N*(N-1)/2 pairwise clone edges.  Expanding it would manufacture
  pairwise facts the index never asserted; ``forest.py`` refuses the fake
  clique and this projection preserves the refusal.  The group's relation
  (``clone_exact`` etc.) rides as a PROPERTY of the member relationships, so
  a consumer can filter memberships by clone type but can never mistake a
  membership for a pairwise clone claim.
* **An undirected edge is ONE relationship carrying ``directed: false``.**
  LPG relationships are structurally directed, and emitting a mirrored pair
  for ``co_change`` would double every degree count and state one fact
  twice.  Consumers that need symmetry apply it; the evidence stays single.
* **Labels are node KINDS; the plane is a derived property.**  ``kind`` is
  what the Forest asserts; the four-plane reading is the master plan's
  PRIOR.  So ``source_file``/``document``/``type``/``field`` become labels
  verbatim, and ``plane`` (code / knowledge / type) is attached as a
  property via an explicit map below.  A kind this module does not know gets
  NO plane key -- under-report rather than guess.

Every list is sorted and every id is deterministic, so projecting the same
Forest twice -- or the same Forest built from differently-ordered inputs --
yields byte-identical JSON, and ``lpg_sha256`` is a stable digest of it.
``forest_sha256`` binds the projection to the exact snapshot it was derived
from; a consumer holding both can prove which revision it is looking at.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from .forest import KnowledgeForest, _json_value

SCHEMA_VERSION = "daedalus-lpg/1"

# The kind->plane reading of the master plan's four-plane prior.  The data
# plane is absent because no Forest node kind asserts data-at-rest structure
# yet; when a ``schema``/``table``/``field_of_record`` kind lands, it gets a
# row here and nowhere else.  Unknown kinds get no plane key at all.
_PLANE_BY_KIND = {
    "source_file": "code",
    "document": "knowledge",
    "type": "type",
    "field": "type",
}


def _canonical(value: Any) -> str:
    return json.dumps(
        _json_value(value), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def _rel_id(rel_type: str, start: str, end: str, properties: dict[str, Any]) -> str:
    """Stable relationship identity: the full fact, hashed.

    Hashing the whole row (not just the endpoint pair) keeps two edges between
    the same endpoints distinct when their attributes differ -- the same rule
    ``forest.py`` uses for type-edge dedup, for the same reason: collapsing
    them would delete the attribute evidence that makes the second edge worth
    publishing.
    """
    body = _canonical([rel_type, start, end, properties]).encode("utf-8")
    return f"{rel_type}:{hashlib.sha256(body).hexdigest()[:16]}"


def to_lpg(forest: KnowledgeForest) -> dict[str, Any]:
    """Project a Forest snapshot onto the LPG data model. Read-only, pure."""
    nodes: list[dict[str, Any]] = []
    for node in forest.nodes:
        properties = dict(_json_value(node.attributes))
        properties["kind"] = node.kind
        plane = _PLANE_BY_KIND.get(node.kind)
        if plane is not None:
            properties["plane"] = plane
        nodes.append({"id": node.id, "labels": [node.kind], "properties": properties})

    relationships: list[dict[str, Any]] = []
    for edge in forest.edges:
        properties = dict(_json_value(edge.attributes))
        properties.update({
            "directed": edge.directed,
            "weight": edge.weight,
            "evidence": list(edge.evidence),
        })
        relationships.append({
            "id": _rel_id(edge.relation, edge.source, edge.target, properties),
            "start": edge.source,
            "end": edge.target,
            "type": edge.relation,
            "properties": properties,
        })

    for hyper in forest.hyperedges:
        properties = dict(_json_value(hyper.attributes))
        properties.update({
            "reified": True,
            "relation": hyper.relation,
            "weight": hyper.weight,
            "evidence": list(hyper.evidence),
            "n_members": len(hyper.members),
        })
        nodes.append({
            "id": hyper.id,
            "labels": ["hyperedge", hyper.relation],
            "properties": properties,
        })
        for member in hyper.members:
            member_props = {"relation": hyper.relation}
            relationships.append({
                "id": _rel_id("hyperedge_member", hyper.id, member, member_props),
                "start": hyper.id,
                "end": member,
                "type": "hyperedge_member",
                "properties": member_props,
            })

    nodes.sort(key=lambda row: row["id"])
    relationships.sort(key=lambda row: (row["type"], row["start"], row["end"], row["id"]))
    return {
        "schema": SCHEMA_VERSION,
        "source_schema": forest.schema,
        "forest_sha256": forest.content_sha256,
        "root": forest.root,
        "nodes": nodes,
        "relationships": relationships,
        "provenance": _json_value(forest.provenance),
    }


def lpg_sha256(lpg: dict[str, Any]) -> str:
    """Digest of the canonical projection bytes -- what ``write_lpg`` writes."""
    return hashlib.sha256(_canonical(lpg).encode("utf-8")).hexdigest()


def write_lpg(lpg: dict[str, Any], path: Any) -> str:
    """Write the canonical bytes and return their digest.

    One serialization, used by the digest and the file alike, so the digest a
    consumer recomputes from the file always matches ``lpg_sha256``.
    """
    from pathlib import Path

    body = _canonical(lpg)
    Path(path).write_text(body, encoding="utf-8")
    return lpg_sha256(lpg)
