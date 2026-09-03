"""Strict Forest/Fourfold wiring into the Boolean sparse relation oracle.

This module is an adapter, not a graph authority.  It only projects relation
facts already retained by one exact :class:`KnowledgeForest` /
:class:`FourfoldSnapshot` subject into the existing ``TypedRelationBlock``
reference kernel.  The returned block is regenerable and grants no trust,
approval, execution authority, or promotion capability.

``TypedRelationBlock`` has no completeness/status field.  To avoid turning a
partial Fourfold observation into a false closed-world relation, this adapter
therefore requires both endpoint planes to be ``complete``.  Incomplete
snapshots must remain explicit at the Fourfold boundary instead of being
silently flattened into sparse zeroes.
"""
from __future__ import annotations

from bisect import bisect_left

from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from .contracts import FourfoldSnapshot
from .relation_blocks import (
    MAX_BLOCK_ENTRIES,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from .semiring import BooleanSemiring


def _retains_digest(digests: tuple[str, ...], digest: str) -> bool:
    position = bisect_left(digests, digest)
    return position < len(digests) and digests[position] == digest


def boolean_relation_block_from_fourfold(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    signature: RelationSignature,
) -> TypedRelationBlock[bool]:
    """Project one exact relation family into the Boolean reference block.

    Cross-plane relations come only from independently verified
    ``FourfoldSnapshot.bindings``.  Same-plane relations come only from binary,
    directed ``ForestEdge`` payloads whose exact canonical digest is retained by
    that plane's ``relation_sha256s``.  Retained hyperedges and undirected edges
    refuse rather than being flattened into a pairwise/directional meaning that
    the Fourfold subject did not assert.

    The adapter intentionally fixes Boolean existence semantics.  Forest
    weights, multiplicity, costs and evidence-bundle algebra need separate,
    explicit scalar contracts before another semiring can be projected without
    inventing meaning.
    """

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    if not isinstance(signature, RelationSignature):
        raise ValueError("signature must be a RelationSignature")
    if forest.content_sha256 != snapshot.source_forest_sha256:
        raise ValueError("relation projection requires the exact Forest bound by Fourfold")

    plane_map = snapshot.plane_map
    source_plane = plane_map[signature.source_plane]
    target_plane = plane_map[signature.target_plane]
    incomplete = sorted(
        {
            plane.plane
            for plane in (source_plane, target_plane)
            if plane.status != "complete"
        }
    )
    if incomplete:
        raise ValueError(
            "relation projection requires complete endpoint planes; "
            f"incomplete={incomplete}"
        )

    row_axis = TypedAxis(
        name=f"{signature.source_plane}-nodes",
        plane=signature.source_plane,
        labels=source_plane.node_ids,
    )
    column_axis = TypedAxis(
        name=f"{signature.target_plane}-nodes",
        plane=signature.target_plane,
        labels=target_plane.node_ids,
    )
    coordinates: list[tuple[str, str, bool]] = []

    def append(source: str, target: str) -> None:
        if len(coordinates) >= MAX_BLOCK_ENTRIES:
            raise ValueError(
                f"relation projection exceeds bounded limit {MAX_BLOCK_ENTRIES}"
            )
        coordinates.append((source, target, True))

    if signature.source_plane != signature.target_plane:
        for binding in snapshot.bindings:
            if (
                binding.source_plane == signature.source_plane
                and binding.target_plane == signature.target_plane
                and binding.relation == signature.relation
            ):
                append(binding.source_node_id, binding.target_node_id)
    else:
        retained_digests = source_plane.relation_sha256s
        for hyperedge in forest.hyperedges:
            if hyperedge.relation != signature.relation:
                continue
            digest = canonical_sha(hyperedge.to_dict())
            if _retains_digest(retained_digests, digest):
                raise ValueError(
                    "binary relation projection cannot flatten a retained ForestHyperedge"
                )

        for edge in forest.edges:
            if edge.relation != signature.relation:
                continue
            digest = canonical_sha(edge.to_dict())
            if not _retains_digest(retained_digests, digest):
                continue
            if not edge.directed:
                raise ValueError(
                    "binary relation projection requires an explicitly directed ForestEdge"
                )
            append(edge.source, edge.target)

    return TypedRelationBlock.from_coordinates(
        subject=ProjectionSubject(
            repository_id=snapshot.repository_id,
            source_revision=snapshot.source_revision,
            source_fourfold_sha256=snapshot.digest,
        ),
        signature=signature,
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=tuple(coordinates),
        semiring=BooleanSemiring(),
    )


__all__ = ["boolean_relation_block_from_fourfold"]
