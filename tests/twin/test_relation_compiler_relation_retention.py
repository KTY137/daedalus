from __future__ import annotations

import hashlib

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature, TypedRelationBlock
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring, EvidenceDagSemiring

REVISION = "5" * 40
CREATED_AT = "2026-09-06T23:00:00+02:00"
IMPORTS = RelationSignature("code", "imports", "code")
DOCUMENTS = RelationSignature("code", "documents", "knowledge")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture(*, retain_code_relation: bool) -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("src/worker.py", "source_file"),
        ),
        edges=(
            ForestEdge(
                source="src/api.py",
                target="src/worker.py",
                relation="imports",
                directed=True,
                evidence=(_digest("imports:api:worker"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-relation-retention",
            "source_revision": REVISION,
        },
    )
    projected = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-relation-retention",
    )
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=("complete" if plane.plane == "code" else plane.status),
            node_ids=plane.node_ids,
            relation_sha256s=(
                plane.relation_sha256s
                if plane.plane != "code" or retain_code_relation
                else ()
            ),
            evidence_sha256s=plane.evidence_sha256s,
            reason=("" if plane.plane == "code" else plane.reason),
        )
        for plane in projected.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-relation-retention.snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in projected.bindings),
        ),
        trace_id="relation-compiler-relation-retention-snapshot",
    )
    snapshot = FourfoldSnapshot(
        repository_id=projected.repository_id,
        source_revision=projected.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=projected.bindings,
        provenance=provenance,
    )
    return forest, snapshot


def _cross_plane_fixture(
    *,
    include_binding: bool,
) -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("docs/api.md", "document"),
        ),
        edges=(
            ForestEdge(
                source="src/api.py",
                target="docs/api.md",
                relation="documents",
                directed=True,
                evidence=(_digest("documents:api:docs"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-cross-plane-retention",
            "source_revision": REVISION,
        },
    )
    projected = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-cross-plane-retention",
    )
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=(
                "complete"
                if plane.plane in {"code", "knowledge"}
                else plane.status
            ),
            node_ids=plane.node_ids,
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
            reason=(
                ""
                if plane.plane in {"code", "knowledge"}
                else plane.reason
            ),
        )
        for plane in projected.planes
    )
    bindings = projected.bindings if include_binding else ()
    provenance = ContractProvenance(
        origin="test.relation-compiler-cross-plane-retention.snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in bindings),
        ),
        trace_id="relation-compiler-cross-plane-retention-snapshot",
    )
    snapshot = FourfoldSnapshot(
        repository_id=projected.repository_id,
        source_revision=projected.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=bindings,
        provenance=provenance,
    )
    return forest, snapshot


def _cross_plane_hyperedge_fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("docs/api.md", "document"),
        ),
        edges=(),
        hyperedges=(
            ForestHyperedge(
                id="documents:api:docs",
                relation="documents",
                members=("src/api.py", "docs/api.md"),
                evidence=(_digest("documents-hyperedge:api:docs"),),
            ),
        ),
        provenance={
            "origin": "test.relation-compiler-cross-plane-hyperedge",
            "source_revision": REVISION,
        },
    )
    planes = (
        PlaneSnapshot(
            plane="code",
            source_revision=REVISION,
            status="complete",
            node_ids=("src/api.py",),
            evidence_sha256s=(forest.content_sha256,),
        ),
        PlaneSnapshot(
            plane="type",
            source_revision=REVISION,
            status="absent",
            reason="not represented by cross-plane hyperedge fixture",
        ),
        PlaneSnapshot(
            plane="data",
            source_revision=REVISION,
            status="absent",
            reason="not represented by cross-plane hyperedge fixture",
        ),
        PlaneSnapshot(
            plane="knowledge",
            source_revision=REVISION,
            status="complete",
            node_ids=("docs/api.md",),
            evidence_sha256s=(forest.content_sha256,),
        ),
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-cross-plane-hyperedge.snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(forest.content_sha256, *(plane.digest for plane in planes)),
        trace_id="relation-compiler-cross-plane-hyperedge-snapshot",
    )
    snapshot = FourfoldSnapshot(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=(),
        provenance=provenance,
    )
    return forest, snapshot


def test_unretained_same_plane_edge_matches_strict_boolean_empty_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=False)

    def forbidden_hash(value: object) -> str:
        raise AssertionError(f"empty-retention Forest relation was hashed: {value!r}")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected evidence materialization for {edge.relation}")

    monkeypatch.setattr(relation_compiler, "canonical_sha", forbidden_hash)
    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    strict = boolean_relation_block_from_fourfold(forest, snapshot, IMPORTS)
    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(IMPORTS,),
    )
    multi = compiled.block_map[relation_block_name(IMPORTS)]

    assert tuple(strict.iter_entries()) == ()
    assert tuple(multi.iter_entries()) == ()
    assert multi.digest == strict.digest
    assert compiled.semantic_fact_count == 0


def test_missing_verified_cross_plane_binding_refuses_both_boolean_projection_paths() -> None:
    forest, snapshot = _cross_plane_fixture(include_binding=False)

    with pytest.raises(ValueError, match="requires an exact verified Fourfold binding"):
        boolean_relation_block_from_fourfold(forest, snapshot, DOCUMENTS)

    with pytest.raises(ValueError, match="requires an exact included verified Fourfold binding"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(DOCUMENTS,),
        )


def test_cross_plane_hyperedge_refuses_both_boolean_projection_paths() -> None:
    forest, snapshot = _cross_plane_hyperedge_fixture()

    with pytest.raises(ValueError, match="cross-plane ForestHyperedge"):
        boolean_relation_block_from_fourfold(forest, snapshot, DOCUMENTS)

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(DOCUMENTS,),
        )


def test_discover_all_does_not_discover_unretained_same_plane_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=False)

    def forbidden_hash(value: object) -> str:
        raise AssertionError(f"empty-retention Forest relation was hashed: {value!r}")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected evidence materialization for {edge.relation}")

    monkeypatch.setattr(relation_compiler, "canonical_sha", forbidden_hash)
    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    compiled = compile_relation_blocks(forest, snapshot, EvidenceDagSemiring())

    assert tuple(compiled.block_map) == ()
    assert compiled.semantic_fact_count == 0
    assert compiled.forest_edge_count == 1


def test_unrelated_explicit_relation_prunes_unretained_same_plane_edge_before_hashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=False)
    selected = RelationSignature("code", "references", "code")

    def forbidden_hash(value: object) -> str:
        raise AssertionError(f"unselected Forest relation was hashed: {value!r}")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unselected evidence was materialized for {edge.relation}")

    monkeypatch.setattr(relation_compiler, "canonical_sha", forbidden_hash)
    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(selected,),
    )

    block = compiled.block_map[relation_block_name(selected)]
    assert tuple(block.iter_entries()) == ()
    assert compiled.semantic_fact_count == 0
    assert compiled.forest_edge_count == 1


def test_retained_same_plane_edge_still_compiles_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=True)
    observed: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def recording_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed.append(edge.relation)
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", recording_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(IMPORTS,),
    )

    block = compiled.block_map[relation_block_name(IMPORTS)]
    entries = tuple(block.iter_entries())
    assert observed == ["imports"]
    assert len(entries) == 1
    assert entries[0][:2] == ("src/api.py", "src/worker.py")
    assert compiled.semantic_fact_count == 1


def test_retained_same_plane_boolean_row_matches_strict_projection() -> None:
    forest, snapshot = _fixture(retain_code_relation=True)

    strict = boolean_relation_block_from_fourfold(forest, snapshot, IMPORTS)
    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(IMPORTS,),
    )
    multi = compiled.block_map[relation_block_name(IMPORTS)]

    assert tuple(multi.iter_entries()) == (
        ("src/api.py", "src/worker.py", True),
    )
    assert multi.digest == strict.digest


def test_retained_same_plane_compiler_reuses_bound_indices_without_coordinate_readmission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=True)

    def unexpected_coordinate_admission(*_args: object, **_kwargs: object) -> object:
        raise AssertionError(
            "retained Fourfold endpoints must reuse the canonical indexed block owner"
        )

    monkeypatch.setattr(
        TypedRelationBlock,
        "from_coordinates",
        classmethod(unexpected_coordinate_admission),
    )

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(IMPORTS,),
    )

    block = compiled.block_map[relation_block_name(IMPORTS)]
    entries = tuple(block.iter_entries())
    assert len(entries) == 1
    assert entries[0][:2] == ("src/api.py", "src/worker.py")
    assert compiled.semantic_fact_count == 1
