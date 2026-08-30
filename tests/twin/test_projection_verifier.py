# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

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
