"""Mechanical verification that Fourfold is an exact KnowledgeForest projection."""
from __future__ import annotations

from dataclasses import dataclass

from ..spine.envelope import canonical_sha
from ..structcore.forest import ForestEdge, ForestHyperedge, KnowledgeForest
from .contracts import FOURFOLD_PLANES, CrossPlaneBinding, FourfoldSnapshot


_KIND_TO_PLANE = {
    "source_file": "code",
    "file": "code",
    "symbol": "code",
    "type": "type",
    "field": "type",
    "data_table": "data",
    "data_field": "data",
    "data_schema": "data",
    "data_schema_field": "data",
    "document": "knowledge",
}


@dataclass(frozen=True, order=True)
class ProjectionFinding:
    code: str
    message: str


@dataclass(frozen=True)
class ProjectionVerificationReport:
    forest_sha256: str
    snapshot_sha256: str
    findings: tuple[ProjectionFinding, ...]

    @property
    def valid(self) -> bool:
        return not self.findings


def _relation_digest(edge: ForestEdge | ForestHyperedge) -> str:
    return canonical_sha(edge.to_dict())


def _binding_projection_evidence(
    forest_sha256: str,
    edge: ForestEdge,
) -> tuple[tuple[str, ...], ...]:
    """Evidence forms produced by current reference and legacy adapters."""

    edge_digest = _relation_digest(edge)
    return (
        tuple(sorted(edge.evidence)),
        tuple(sorted((forest_sha256, edge_digest))),
    )


def verify_forest_projection(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> ProjectionVerificationReport:
    """Return deterministic findings for any Forest/Fourfold divergence."""

    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")

    findings: list[ProjectionFinding] = []
    forest_sha = forest.content_sha256
    if snapshot.source_forest_sha256 != forest_sha:
        findings.append(ProjectionFinding(
            "forest-digest-mismatch",
            "snapshot.source_forest_sha256 does not identify the supplied Forest",
        ))

    provenance_revision = forest.provenance.get("source_revision")
    if provenance_revision is not None and provenance_revision != snapshot.source_revision:
        findings.append(ProjectionFinding(
            "forest-revision-mismatch",
            "Forest provenance source_revision differs from the Fourfold revision",
        ))

    node_plane: dict[str, str] = {}
    forest_nodes_by_plane = {plane: set() for plane in FOURFOLD_PLANES}
    for node in forest.nodes:
        if node.id in node_plane:
            findings.append(ProjectionFinding(
                "duplicate-forest-node",
                f"Forest repeats node id {node.id!r}",
            ))
            continue
        plane = _KIND_TO_PLANE.get(node.kind)
        if plane is None:
            findings.append(ProjectionFinding(
                "unmapped-forest-node-kind",
                f"Forest node {node.id!r} has unmapped kind {node.kind!r}",
            ))
            continue
        node_plane[node.id] = plane
        forest_nodes_by_plane[plane].add(node.id)

    for plane in snapshot.planes:
        expected = forest_nodes_by_plane[plane.plane]
        actual = set(plane.node_ids)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            findings.append(ProjectionFinding(
                "snapshot-missing-nodes",
                f"{plane.plane} plane omits Forest nodes: {missing}",
            ))
        if extra:
            findings.append(ProjectionFinding(
                "snapshot-extra-nodes",
                f"{plane.plane} plane contains nodes absent from the Forest: {extra}",
            ))

    relation_digests = {plane: set() for plane in FOURFOLD_PLANES}
    forest_cross_plane: dict[
        tuple[str, str, str, str, str, str], ForestEdge
    ] = {}

    for edge in forest.edges:
        source_plane = node_plane.get(edge.source)
        target_plane = node_plane.get(edge.target)
        if source_plane is None or target_plane is None:
            findings.append(ProjectionFinding(
                "forest-edge-unknown-endpoint",
                f"Forest edge {edge.relation!r} references an unmapped endpoint",
            ))
            continue
        if source_plane == target_plane:
            relation_digests[source_plane].add(_relation_digest(edge))
            continue
        key = (
            source_plane,
            edge.source,
            target_plane,
            edge.target,
            edge.relation,
            snapshot.source_revision,
        )
        if key in forest_cross_plane:
            findings.append(ProjectionFinding(
                "ambiguous-cross-plane-edge",
                f"Forest repeats cross-plane semantic edge {key!r}",
            ))
            continue
        forest_cross_plane[key] = edge

    for hyperedge in forest.hyperedges:
        member_planes = {node_plane.get(member) for member in hyperedge.members}
        if None in member_planes:
            findings.append(ProjectionFinding(
                "forest-hyperedge-unknown-endpoint",
                f"Forest hyperedge {hyperedge.id!r} references an unmapped endpoint",
            ))
        elif len(member_planes) == 1:
            relation_digests[next(iter(member_planes))].add(
                _relation_digest(hyperedge)
            )
        else:
            findings.append(ProjectionFinding(
                "cross-plane-hyperedge-unrepresentable",
                f"Forest hyperedge {hyperedge.id!r} crosses planes and cannot be represented losslessly",
            ))

    for plane in snapshot.planes:
        expected = relation_digests[plane.plane]
        actual = set(plane.relation_sha256s)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            findings.append(ProjectionFinding(
                "snapshot-missing-relations",
                f"{plane.plane} plane omits Forest relation digests: {missing}",
            ))
        if extra:
            findings.append(ProjectionFinding(
                "snapshot-extra-relations",
                f"{plane.plane} plane contains relation digests absent from the Forest: {extra}",
            ))

    snapshot_bindings: dict[
        tuple[str, str, str, str, str, str], CrossPlaneBinding
    ] = {}
    for binding in snapshot.bindings:
        key = binding.semantic_key
        if key in snapshot_bindings:
            findings.append(ProjectionFinding(
                "duplicate-snapshot-binding",
                f"Fourfold repeats binding {key!r}",
            ))
            continue
        snapshot_bindings[key] = binding

    for key, edge in sorted(forest_cross_plane.items()):
        binding = snapshot_bindings.get(key)
        if binding is None:
            findings.append(ProjectionFinding(
                "snapshot-missing-binding",
                f"Fourfold omits Forest cross-plane edge {key!r}",
            ))
            continue
        accepted_evidence = _binding_projection_evidence(forest_sha, edge)
        if tuple(binding.evidence_sha256s) not in accepted_evidence:
            findings.append(ProjectionFinding(
                "binding-evidence-mismatch",
                f"Fourfold binding {key!r} does not retain an accepted Forest evidence projection",
            ))

    for key in sorted(set(snapshot_bindings) - set(forest_cross_plane)):
        findings.append(ProjectionFinding(
            "snapshot-extra-binding",
            f"Fourfold binding has no matching Forest cross-plane edge: {key!r}",
        ))

    return ProjectionVerificationReport(
        forest_sha256=forest_sha,
        snapshot_sha256=snapshot.digest,
        findings=tuple(sorted(set(findings))),
    )


def require_forest_projection(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> ProjectionVerificationReport:
    """Verify projection and raise one stable error when divergence exists."""

    report = verify_forest_projection(forest, snapshot)
    if not report.valid:
        details = "; ".join(
            f"{finding.code}: {finding.message}" for finding in report.findings
        )
        raise ValueError(f"Fourfold is not an exact Forest projection: {details}")
    return report


__all__ = [
    "ProjectionFinding",
    "ProjectionVerificationReport",
    "require_forest_projection",
    "verify_forest_projection",
]
