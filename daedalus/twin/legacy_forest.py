"""Conservative adapter from the existing KnowledgeForest to FourfoldSnapshot.

The adapter projects evidence; it does not upgrade its assurance.  Current
KnowledgeForest snapshots have code, document, and optional type/field layers,
but no canonical Data Plane and no proof of full plane completeness.  Those
facts remain visible as ``partial`` and ``absent`` statuses.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..kernel.contracts.base import ContractProvenance
from ..spine.envelope import canonical_sha
from ..structcore.forest import ForestEdge, ForestHyperedge, KnowledgeForest
from .contracts import CrossPlaneBinding, FourfoldSnapshot, PlaneSnapshot

_KIND_TO_PLANE = {
    "source_file": "code",
    "file": "code",
    "type": "type",
    "field": "type",
    "document": "knowledge",
}


def _edge_digest(edge: ForestEdge | ForestHyperedge) -> str:
    return canonical_sha(edge.to_dict())


def _plane_status(plane: str, node_ids: Iterable[str]) -> tuple[str, str]:
    nodes = tuple(node_ids)
    if plane == "data":
        return (
            "absent",
            "legacy KnowledgeForest publishes no canonical Data Plane evidence",
        )
    if not nodes:
        return (
            "absent",
            f"legacy KnowledgeForest contains no {plane}-plane nodes for this revision",
        )
    return (
        "partial",
        "legacy KnowledgeForest projection; full Fourfold plane completeness is not proven",
    )


def fourfold_from_knowledge_forest(
    forest: KnowledgeForest,
    *,
    repository_id: str,
    source_revision: str,
    created_at: str,
    trace_id: str | None = None,
) -> FourfoldSnapshot:
    """Project one immutable Forest into an atomic, explicitly incomplete Twin.

    ``source_revision`` is mandatory because the legacy Forest schema does not
    guarantee that a revision is present in provenance.  The caller must bind
    the exact tree from which the supplied Forest was compiled.
    """

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")

    forest_digest = forest.content_sha256
    node_plane: dict[str, str] = {}
    nodes_by_plane: dict[str, list[str]] = defaultdict(list)
    for node in forest.nodes:
        try:
            plane = _KIND_TO_PLANE[node.kind]
        except KeyError as exc:
            raise ValueError(
                f"legacy Forest node {node.id!r} has unmapped kind {node.kind!r}; "
                "refusing rather than assigning it to a plane by guess"
            ) from exc
        if node.id in node_plane:
            raise ValueError(f"legacy Forest contains duplicate node id {node.id!r}")
        node_plane[node.id] = plane
        nodes_by_plane[plane].append(node.id)

    relation_digests: dict[str, list[str]] = defaultdict(list)
    bindings: list[CrossPlaneBinding] = []

    for edge in forest.edges:
        source_plane = node_plane.get(edge.source)
        target_plane = node_plane.get(edge.target)
        if source_plane is None or target_plane is None:
            raise ValueError(
                f"legacy Forest edge {edge.relation!r} references an unknown endpoint"
            )
        digest = _edge_digest(edge)
        if source_plane == target_plane:
            relation_digests[source_plane].append(digest)
        else:
            if not edge.evidence:
                raise ValueError(
                    f"legacy cross-plane edge {edge.relation!r} has no retained "
                    "evidence; refusing to upgrade it to a verified binding"
                )
            bindings.append(
                CrossPlaneBinding(
                    source_plane=source_plane,
                    source_node_id=edge.source,
                    target_plane=target_plane,
                    target_node_id=edge.target,
                    relation=edge.relation,
                    source_revision=source_revision,
                    evidence_sha256s=(forest_digest, digest),
                )
            )

    for hyperedge in forest.hyperedges:
        member_planes = {node_plane.get(member) for member in hyperedge.members}
        if None in member_planes:
            raise ValueError(
                f"legacy Forest hyperedge {hyperedge.id!r} references an unknown endpoint"
            )
        if len(member_planes) != 1:
            raise ValueError(
                f"cross-plane hyperedge {hyperedge.id!r} cannot be represented as "
                "pairwise verified bindings without losing semantics"
            )
        relation_digests[next(iter(member_planes))].append(_edge_digest(hyperedge))

    planes: list[PlaneSnapshot] = []
    for plane in ("code", "type", "data", "knowledge"):
        status, reason = _plane_status(plane, nodes_by_plane.get(plane, ()))
        planes.append(
            PlaneSnapshot(
                plane=plane,
                source_revision=source_revision,
                status=status,
                node_ids=tuple(nodes_by_plane.get(plane, ())),
                relation_sha256s=tuple(relation_digests.get(plane, ())),
                evidence_sha256s=(forest_digest,),
                reason=reason,
            )
        )

    inputs = {
        forest_digest,
        *(plane.digest for plane in planes),
        *(binding.digest for binding in bindings),
    }
    provenance = ContractProvenance(
        origin="daedalus.twin.legacy-forest",
        source_revision=source_revision,
        created_at=created_at,
        input_digests=tuple(inputs),
        trace_id=trace_id,
    )
    return FourfoldSnapshot(
        repository_id=repository_id,
        source_revision=source_revision,
        source_forest_sha256=forest_digest,
        planes=tuple(planes),
        bindings=tuple(bindings),
        provenance=provenance,
    )
