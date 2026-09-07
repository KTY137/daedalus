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
from .contracts import FOURFOLD_PLANES, FourfoldSnapshot
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
    ``FourfoldSnapshot.bindings``.  Matching raw cross-plane ``ForestEdge``
    payloads are consistency inputs only and refuse if the exact verified
    binding is absent; they never become a second fact authority.  Cross-plane
    hyperedges also refuse whenever they intersect both selected endpoint
    planes because a binary block cannot represent their higher-arity meaning.
    Same-plane relations come only from binary, directed ``ForestEdge`` payloads
    whose exact canonical digest is retained by that plane's
    ``relation_sha256s``.  Retained hyperedges and undirected edges refuse
    rather than being flattened into a pairwise/directional meaning that the
    Fourfold subject did not assert.

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
    provenance_revision = forest.provenance.get("source_revision")
    if (
        provenance_revision is not None
        and provenance_revision != snapshot.source_revision
    ):
        raise ValueError("Forest provenance revision differs from the snapshot")

    snapshot_node_ids = {
        node_id
        for plane in snapshot.planes
        for node_id in plane.node_ids
    }
    forest_node_ids = tuple(node.id for node in forest.nodes)
    if len(set(forest_node_ids)) != len(forest_node_ids):
        raise ValueError("Forest contains duplicate node ids")
    missing_nodes = sorted(set(forest_node_ids) - snapshot_node_ids)
    if missing_nodes:
        raise ValueError(
            "Forest nodes are missing from the Fourfold plane partition: "
            + ", ".join(missing_nodes[:8])
        )

    # FourfoldSnapshot canonicalizes planes into FOURFOLD_PLANES order once.
    # Reuse that immutable tuple instead of rebuilding ``plane_map`` per block.
    source_plane = snapshot.planes[FOURFOLD_PLANES.index(signature.source_plane)]
    target_plane = (
        source_plane
        if signature.source_plane == signature.target_plane
        else snapshot.planes[FOURFOLD_PLANES.index(signature.target_plane)]
    )
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
    if signature.source_plane == signature.target_plane:
        column_axis = row_axis
    else:
        column_axis = TypedAxis(
            name=f"{signature.target_plane}-nodes",
            plane=signature.target_plane,
            labels=target_plane.node_ids,
        )

    subject = ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_fourfold_sha256=snapshot.digest,
    )
    semiring = BooleanSemiring()

    if signature.source_plane != signature.target_plane:
        # FourfoldSnapshot already validates revision identity and endpoint
        # membership for every retained cross-plane binding.  Convert those
        # verified labels to local indices once and delegate to the existing
        # canonical indexed block owner instead of readmitting each label
        # through ``from_coordinates``.  Raw Forest edges remain consistency
        # inputs only and cannot manufacture a fact when Fourfold omitted the
        # exact verified binding.  Cross-plane hyperedges are unrepresentable
        # in a binary block and therefore refuse when they span both selected
        # endpoint planes.
        row_positions: dict[str, int] = {}
        column_positions: dict[str, int] = {}
        entries: dict[tuple[int, int], bool] = {}
        verified_pairs: set[tuple[str, str]] = set()
        for binding in snapshot.bindings:
            if (
                binding.source_plane == signature.source_plane
                and binding.target_plane == signature.target_plane
                and binding.relation == signature.relation
            ):
                if len(entries) >= MAX_BLOCK_ENTRIES:
                    raise ValueError(
                        f"relation projection exceeds bounded limit {MAX_BLOCK_ENTRIES}"
                    )
                if not row_positions:
                    row_positions = {
                        label: position for position, label in enumerate(row_axis.labels)
                    }
                    column_positions = {
                        label: position
                        for position, label in enumerate(column_axis.labels)
                    }
                verified_pairs.add((binding.source_node_id, binding.target_node_id))
                entries[
                    (
                        row_positions[binding.source_node_id],
                        column_positions[binding.target_node_id],
                    )
                ] = True

        source_labels = frozenset(row_axis.labels)
        target_labels = frozenset(column_axis.labels)
        for hyperedge in forest.hyperedges:
            if hyperedge.relation != signature.relation:
                continue
            members = frozenset(hyperedge.members)
            if members.intersection(source_labels) and members.intersection(target_labels):
                raise ValueError(
                    "binary relation projection cannot flatten a cross-plane "
                    "ForestHyperedge without losing semantics"
                )

        for edge in forest.edges:
            if edge.relation != signature.relation:
                continue
            forward = edge.source in source_labels and edge.target in target_labels
            reverse = edge.source in target_labels and edge.target in source_labels
            if not edge.directed:
                if forward or reverse:
                    raise ValueError(
                        "binary relation projection requires an explicitly directed ForestEdge"
                    )
                continue
            if forward and (edge.source, edge.target) not in verified_pairs:
                raise ValueError(
                    "cross-plane ForestEdge requires an exact verified Fourfold "
                    "binding before relation projection"
                )

        return TypedRelationBlock._from_indexed(
            subject,
            signature,
            row_axis,
            column_axis,
            entries,
            semiring,
        )

    retained_digests = source_plane.relation_sha256s
    endpoints: list[tuple[str, str]] = []
    if retained_digests:
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
            if len(endpoints) >= MAX_BLOCK_ENTRIES:
                raise ValueError(
                    f"relation projection exceeds bounded limit {MAX_BLOCK_ENTRIES}"
                )
            endpoints.append((edge.source, edge.target))

    entries: dict[tuple[int, int], bool] = {}
    if endpoints:
        positions = {label: position for position, label in enumerate(row_axis.labels)}
        for source, target in endpoints:
            row_position = positions.get(source)
            if row_position is None:
                raise ValueError(f"unknown row label {source!r}")
            column_position = positions.get(target)
            if column_position is None:
                raise ValueError(f"unknown column label {target!r}")
            entries[(row_position, column_position)] = True

    return TypedRelationBlock._from_indexed(
        subject,
        signature,
        row_axis,
        column_axis,
        entries,
        semiring,
    )


__all__ = ["boolean_relation_block_from_fourfold"]
