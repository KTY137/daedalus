from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import (
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
    compile_reference_project,
    fourfold_from_knowledge_forest,
    require_forest_projection,
    verify_forest_projection,
)
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring

REVISION = "e" * 40
NOW = "2026-08-01T19:00:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _compile():
    return compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-projection-verifier",
    )


def _provenance(
    snapshot: FourfoldSnapshot,
    planes: tuple[PlaneSnapshot, ...],
    bindings: tuple[CrossPlaneBinding, ...],
) -> ContractProvenance:
    return ContractProvenance(
        origin="test.projection-verifier",
        source_revision=snapshot.source_revision,
        created_at=NOW,
        input_digests=(
            snapshot.source_forest_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in bindings),
        ),
    )


def _partition_fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/app.py", "source_file", {}),
            ForestNode("docs/App.md", "document", {}),
        ),
        edges=(),
        hyperedges=(),
        provenance={"source_revision": REVISION},
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="partition-fixture",
        source_revision=REVISION,
        created_at=NOW,
    )
    return forest, snapshot


def _with_planes(
    snapshot: FourfoldSnapshot,
    planes: tuple[PlaneSnapshot, ...],
) -> FourfoldSnapshot:
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=planes,
        bindings=snapshot.bindings,
        provenance=_provenance(snapshot, planes, snapshot.bindings),
    )


def test_reference_compiler_is_an_exact_forest_projection() -> None:
    result = _compile()
    report = require_forest_projection(result.forest, result.snapshot)
    assert report.valid
    assert not report.findings


def test_legacy_projection_evidence_wrapper_is_verified() -> None:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/app.py", "source_file", {}),
            ForestNode("docs/App.md", "document", {}),
        ),
        edges=(
            ForestEdge(
                "docs/App.md",
                "src/app.py",
                "documents",
                True,
                evidence=("docs/App.md",),
            ),
        ),
        hyperedges=(),
        provenance={"source_revision": REVISION},
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="legacy-fixture",
        source_revision=REVISION,
        created_at=NOW,
    )
    assert require_forest_projection(forest, snapshot).valid


def test_missing_binding_is_reported_without_becoming_authoritative() -> None:
    result = _compile()
    original = result.snapshot
    bindings: tuple[CrossPlaneBinding, ...] = ()
    snapshot = FourfoldSnapshot(
        repository_id=original.repository_id,
        source_revision=original.source_revision,
        source_forest_sha256=original.source_forest_sha256,
        planes=original.planes,
        bindings=bindings,
        provenance=_provenance(original, original.planes, bindings),
    )
    report = verify_forest_projection(result.forest, snapshot)
    assert not report.valid
    assert "snapshot-missing-binding" in {finding.code for finding in report.findings}


def test_repacked_binding_evidence_is_reported() -> None:
    result = _compile()
    original = result.snapshot
    first = original.bindings[0]
    repacked = CrossPlaneBinding(
        source_plane=first.source_plane,
        source_node_id=first.source_node_id,
        target_plane=first.target_plane,
        target_node_id=first.target_node_id,
        relation=first.relation,
        source_revision=first.source_revision,
        evidence_sha256s=("f" * 64,),
    )
    bindings = (repacked, *original.bindings[1:])
    snapshot = FourfoldSnapshot(
        repository_id=original.repository_id,
        source_revision=original.source_revision,
        source_forest_sha256=original.source_forest_sha256,
        planes=original.planes,
        bindings=bindings,
        provenance=_provenance(original, original.planes, bindings),
    )
    report = verify_forest_projection(result.forest, snapshot)
    assert "binding-evidence-mismatch" in {
        finding.code for finding in report.findings
    }


def test_omitted_forest_node_is_reported() -> None:
    result = _compile()
    original = result.snapshot
    code = original.plane_map["code"]
    removable = next(node for node in code.node_ids if node.startswith("code:symbol:"))
    changed_code = PlaneSnapshot(
        plane="code",
        source_revision=code.source_revision,
        status=code.status,
        node_ids=tuple(node for node in code.node_ids if node != removable),
        relation_sha256s=code.relation_sha256s,
        evidence_sha256s=code.evidence_sha256s,
        reason=code.reason,
    )
    planes = (changed_code, *original.planes[1:])
    snapshot = FourfoldSnapshot(
        repository_id=original.repository_id,
        source_revision=original.source_revision,
        source_forest_sha256=original.source_forest_sha256,
        planes=planes,
        bindings=original.bindings,
        provenance=_provenance(original, planes, original.bindings),
    )
    report = verify_forest_projection(result.forest, snapshot)
    assert "snapshot-missing-nodes" in {finding.code for finding in report.findings}


def test_extra_fourfold_node_refuses_verifier_compiler_and_boolean_adapter() -> None:
    forest, original = _partition_fixture()
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=plane.status,
            node_ids=(
                (*plane.node_ids, "src/ghost.py")
                if plane.plane == "code"
                else plane.node_ids
            ),
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
            reason=plane.reason,
        )
        for plane in original.planes
    )
    snapshot = _with_planes(original, planes)
    signature = RelationSignature("code", "references", "code")

    report = verify_forest_projection(forest, snapshot)
    assert "snapshot-extra-nodes" in {finding.code for finding in report.findings}

    with pytest.raises(ValueError, match="node partition is not exact"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(signature,),
        )
    with pytest.raises(ValueError, match="node partition is not exact"):
        boolean_relation_block_from_fourfold(forest, snapshot, signature)


def test_wrong_kind_plane_refuses_verifier_compiler_and_boolean_adapter() -> None:
    forest, original = _partition_fixture()
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=plane.status,
            node_ids=(
                tuple(node for node in plane.node_ids if node != "src/app.py")
                if plane.plane == "code"
                else (*plane.node_ids, "src/app.py")
                if plane.plane == "knowledge"
                else plane.node_ids
            ),
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
            reason=plane.reason,
        )
        for plane in original.planes
    )
    snapshot = _with_planes(original, planes)
    signature = RelationSignature("code", "references", "code")

    report = verify_forest_projection(forest, snapshot)
    codes = {finding.code for finding in report.findings}
    assert {"snapshot-missing-nodes", "snapshot-extra-nodes"}.issubset(codes)

    with pytest.raises(
        ValueError,
        match="Forest nodes are missing from the Fourfold plane partition",
    ):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(signature,),
        )
    with pytest.raises(
        ValueError,
        match="Forest nodes are missing from the Fourfold plane partition",
    ):
        boolean_relation_block_from_fourfold(forest, snapshot, signature)


def test_legacy_adapter_still_refuses_data_plane_node_kind() -> None:
    forest = KnowledgeForest(
        root=".",
        nodes=(ForestNode("data/users", "data_table", {}),),
        edges=(),
        hyperedges=(),
        provenance={"source_revision": REVISION},
    )

    with pytest.raises(ValueError, match="unmapped kind 'data_table'"):
        fourfold_from_knowledge_forest(
            forest,
            repository_id="legacy-data-refusal",
            source_revision=REVISION,
            created_at=NOW,
        )
