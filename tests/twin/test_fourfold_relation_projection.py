from __future__ import annotations

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot, fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring

REVISION = "a" * 40
NOW = "2026-09-03T15:57:12Z"


def _forest(
    *,
    with_hyperedge: bool = False,
    imports_directed: bool = True,
) -> KnowledgeForest:
    return KnowledgeForest(
        root="/repo",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
            ForestNode("docs/b.md", "document"),
        ),
        edges=(
            ForestEdge(
                "src/a.py",
                "src/b.py",
                "imports",
                imports_directed,
                evidence=("fixture.imports",),
            ),
            ForestEdge(
                "src/b.py",
                "docs/b.md",
                "documents",
                True,
                evidence=("fixture.documents",),
            ),
        ),
        hyperedges=(
            (
                ForestHyperedge(
                    id="clone_exact:fixture",
                    relation="clone_exact",
                    members=("src/a.py", "src/b.py"),
                    evidence=("fixture.clone",),
                ),
            )
            if with_hyperedge
            else ()
        ),
        provenance={"origin": "test.fourfold-relation-projection"},
    )


def _legacy_snapshot(forest: KnowledgeForest) -> FourfoldSnapshot:
    return fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=NOW,
        trace_id="fourfold-relation-projection",
    )


def _complete_snapshot(forest: KnowledgeForest) -> FourfoldSnapshot:
    legacy = _legacy_snapshot(forest)
    planes = tuple(
        (
            PlaneSnapshot(
                plane=plane.plane,
                source_revision=plane.source_revision,
                status="complete",
                node_ids=plane.node_ids,
                relation_sha256s=plane.relation_sha256s,
                evidence_sha256s=plane.evidence_sha256s,
            )
            if plane.plane in {"code", "knowledge"}
            else plane
        )
        for plane in legacy.planes
    )
    provenance = ContractProvenance(
        origin="test.fourfold-relation-projection.complete-fixture",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in legacy.bindings),
        ),
        trace_id="fourfold-relation-projection-complete",
    )
    return FourfoldSnapshot(
        repository_id=legacy.repository_id,
        source_revision=legacy.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=legacy.bindings,
        provenance=provenance,
    )


def test_projection_matches_direct_forest_relations_and_composes() -> None:
    forest = _forest()
    snapshot = _complete_snapshot(forest)
    semiring = BooleanSemiring()

    imports = boolean_relation_block_from_fourfold(
        forest,
        snapshot,
        RelationSignature("code", "imports", "code"),
    )
    documents = boolean_relation_block_from_fourfold(
        forest,
        snapshot,
        RelationSignature("code", "documents", "knowledge"),
    )

    direct_imports = tuple(
        sorted(
            (edge.source, edge.target, True)
            for edge in forest.edges
            if edge.relation == "imports"
        )
    )
    direct_documents = tuple(
        sorted(
            (edge.source, edge.target, True)
            for edge in forest.edges
            if edge.relation == "documents"
        )
    )
    assert tuple(imports.iter_entries()) == direct_imports
    assert tuple(documents.iter_entries()) == direct_documents
    assert imports.subject.source_fourfold_sha256 == snapshot.digest
    assert documents.subject == imports.subject
    assert imports.column_axis == documents.row_axis

    composed = imports.matmul(
        documents,
        semiring,
        relation="imports-then-documents",
    )
    assert tuple(composed.iter_entries()) == (("src/a.py", "docs/b.md", True),)


def test_same_plane_projection_reuses_the_exact_typed_axis() -> None:
    forest = _forest()
    snapshot = _complete_snapshot(forest)

    imports = boolean_relation_block_from_fourfold(
        forest,
        snapshot,
        RelationSignature("code", "imports", "code"),
    )
    documents = boolean_relation_block_from_fourfold(
        forest,
        snapshot,
        RelationSignature("code", "documents", "knowledge"),
    )

    assert imports.row_axis is imports.column_axis
    assert imports.row_axis.labels is snapshot.plane_map["code"].node_ids
    assert documents.row_axis is not documents.column_axis


def test_projection_refuses_legacy_partial_endpoint_planes() -> None:
    forest = _forest()
    snapshot = _legacy_snapshot(forest)

    with pytest.raises(ValueError, match="complete endpoint planes"):
        boolean_relation_block_from_fourfold(
            forest,
            snapshot,
            RelationSignature("code", "documents", "knowledge"),
        )


def test_projection_refuses_a_forest_not_bound_by_the_snapshot() -> None:
    forest = _forest()
    snapshot = _complete_snapshot(forest)
    other = KnowledgeForest(
        root="/other-root",
        nodes=forest.nodes,
        edges=forest.edges,
        hyperedges=forest.hyperedges,
        provenance=forest.provenance,
    )

    with pytest.raises(ValueError, match="exact Forest bound by Fourfold"):
        boolean_relation_block_from_fourfold(
            other,
            snapshot,
            RelationSignature("code", "imports", "code"),
        )


def test_projection_refuses_retained_hyperedges_instead_of_pairwise_flattening() -> None:
    forest = _forest(with_hyperedge=True)
    snapshot = _complete_snapshot(forest)

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        boolean_relation_block_from_fourfold(
            forest,
            snapshot,
            RelationSignature("code", "clone_exact", "code"),
        )


def test_projection_refuses_undirected_edges_instead_of_inventing_orientation() -> None:
    forest = _forest(imports_directed=False)
    snapshot = _complete_snapshot(forest)

    with pytest.raises(ValueError, match="explicitly directed ForestEdge"):
        boolean_relation_block_from_fourfold(
            forest,
            snapshot,
            RelationSignature("code", "imports", "code"),
        )


def test_projection_of_an_unretained_relation_is_an_empty_exact_block() -> None:
    forest = _forest()
    snapshot = _complete_snapshot(forest)

    block = boolean_relation_block_from_fourfold(
        forest,
        snapshot,
        RelationSignature("code", "calls", "code"),
    )

    assert tuple(block.iter_entries()) == ()
    assert block.get("src/a.py", "src/b.py", BooleanSemiring()) is False
