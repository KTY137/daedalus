from __future__ import annotations

from pathlib import Path

from daedalus.schemas import ContractProvenance
from daedalus.twin import CrossPlaneBinding, FourfoldSnapshot, compile_reference_project
from daedalus.twin.contractions import boolean_overlap_disagreements
from daedalus.twin.projection_verifier import verify_forest_projection
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

REVISION = "e" * 40
NOW = "2026-08-01T19:00:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _compile():
    return compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="g1-tensor-01aj-real-overlap-probe",
    )


def _subject(snapshot: FourfoldSnapshot) -> ProjectionSubject:
    return ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_fourfold_sha256=snapshot.digest,
    )


def _signature(binding: CrossPlaneBinding) -> RelationSignature:
    return RelationSignature(
        binding.source_plane,
        binding.relation,
        binding.target_plane,
    )


def _axes(snapshot: FourfoldSnapshot, signature: RelationSignature):
    return (
        TypedAxis(
            "source-nodes",
            signature.source_plane,
            snapshot.plane_map[signature.source_plane].node_ids,
        ),
        TypedAxis(
            "target-nodes",
            signature.target_plane,
            snapshot.plane_map[signature.target_plane].node_ids,
        ),
    )


def _forest_block(compiled, signature: RelationSignature) -> TypedRelationBlock[bool]:
    snapshot = compiled.snapshot
    node_plane = {
        node_id: plane.plane
        for plane in snapshot.planes
        for node_id in plane.node_ids
    }
    rows, columns = _axes(snapshot, signature)
    coordinates = tuple(
        (edge.source, edge.target, True)
        for edge in compiled.forest.edges
        if node_plane.get(edge.source) == signature.source_plane
        and node_plane.get(edge.target) == signature.target_plane
        and edge.relation == signature.relation
    )
    return TypedRelationBlock.from_coordinates(
        subject=_subject(snapshot),
        signature=signature,
        row_axis=rows,
        column_axis=columns,
        coordinates=coordinates,
        semiring=BooleanSemiring(),
    )


def _snapshot_block(
    snapshot: FourfoldSnapshot,
    signature: RelationSignature,
    *,
    subject: ProjectionSubject,
) -> TypedRelationBlock[bool]:
    rows, columns = _axes(snapshot, signature)
    coordinates = tuple(
        (binding.source_node_id, binding.target_node_id, True)
        for binding in snapshot.bindings
        if binding.source_plane == signature.source_plane
        and binding.target_plane == signature.target_plane
        and binding.relation == signature.relation
    )
    return TypedRelationBlock.from_coordinates(
        subject=subject,
        signature=signature,
        row_axis=rows,
        column_axis=columns,
        coordinates=coordinates,
        semiring=BooleanSemiring(),
    )


def _snapshot_with_bindings(
    original: FourfoldSnapshot,
    bindings: tuple[CrossPlaneBinding, ...],
) -> FourfoldSnapshot:
    provenance = ContractProvenance(
        origin="test.g1-tensor-01aj-real-overlap-probe",
        source_revision=original.source_revision,
        created_at=NOW,
        input_digests=(
            original.source_forest_sha256,
            *(plane.digest for plane in original.planes),
            *(binding.digest for binding in bindings),
        ),
        trace_id="g1-tensor-01aj-real-overlap-probe",
    )
    return FourfoldSnapshot(
        repository_id=original.repository_id,
        source_revision=original.source_revision,
        source_forest_sha256=original.source_forest_sha256,
        planes=original.planes,
        bindings=bindings,
        provenance=provenance,
    )


def test_real_reference_projection_has_no_overlap_disagreement() -> None:
    compiled = _compile()
    assert verify_forest_projection(compiled.forest, compiled.snapshot).valid
    selected = compiled.snapshot.bindings[0]
    signature = _signature(selected)
    subject = _subject(compiled.snapshot)

    forest_block = _forest_block(compiled, signature)
    snapshot_block = _snapshot_block(
        compiled.snapshot,
        signature,
        subject=subject,
    )

    assert boolean_overlap_disagreements(forest_block, snapshot_block) == ()


def test_existing_projection_verifier_is_stronger_on_evidence_drift() -> None:
    compiled = _compile()
    original = compiled.snapshot
    selected = original.bindings[0]
    repacked = CrossPlaneBinding(
        source_plane=selected.source_plane,
        source_node_id=selected.source_node_id,
        target_plane=selected.target_plane,
        target_node_id=selected.target_node_id,
        relation=selected.relation,
        source_revision=selected.source_revision,
        evidence_sha256s=("f" * 64,),
    )
    bindings = tuple(
        repacked if binding == selected else binding for binding in original.bindings
    )
    drifted = _snapshot_with_bindings(original, bindings)
    report = verify_forest_projection(compiled.forest, drifted)
    assert "binding-evidence-mismatch" in {finding.code for finding in report.findings}

    signature = _signature(selected)
    canonical_subject = _subject(original)
    forest_block = _forest_block(compiled, signature)
    drifted_block = _snapshot_block(
        drifted,
        signature,
        subject=canonical_subject,
    )

    # Boolean overlap retains only semantic coordinates, so it cannot see the
    # evidence defect already diagnosed by the authoritative projection verifier.
    assert boolean_overlap_disagreements(forest_block, drifted_block) == ()


def test_missing_binding_is_only_a_duplicate_semantic_finding() -> None:
    compiled = _compile()
    original = compiled.snapshot
    selected = original.bindings[0]
    bindings = tuple(binding for binding in original.bindings if binding != selected)
    drifted = _snapshot_with_bindings(original, bindings)
    report = verify_forest_projection(compiled.forest, drifted)
    assert "snapshot-missing-binding" in {finding.code for finding in report.findings}

    signature = _signature(selected)
    canonical_subject = _subject(original)
    forest_block = _forest_block(compiled, signature)
    drifted_block = _snapshot_block(
        drifted,
        signature,
        subject=canonical_subject,
    )

    assert boolean_overlap_disagreements(forest_block, drifted_block) == (
        (selected.source_node_id, selected.target_node_id),
    )
