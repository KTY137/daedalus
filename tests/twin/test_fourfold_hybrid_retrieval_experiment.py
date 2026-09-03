from __future__ import annotations

import pytest

from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import fourfold_from_knowledge_forest
from experiments.fourfold_hybrid_retrieval import (
    ContractionPlan,
    HybridRequest,
    HybridRetriever,
    NodeDocument,
    PathExpression,
    PhysicalPlanner,
    ReferenceContractionExecutor,
    RelationSignature,
    RelationStep,
    compile_relation_blocks,
)

REVISION = "a" * 40
NOW = "2026-09-03T12:00:00Z"


def _forest() -> KnowledgeForest:
    nodes = (
        ForestNode("src/controller.py", "source_file"),
        ForestNode("src/sensor.py", "source_file"),
        ForestNode("src/bias_helpers.py", "source_file"),
        ForestNode("type:src/sensor.py#VoltageReading", "type"),
        ForestNode("type:src/sensor.py#TemperatureReading", "type"),
        ForestNode("docs/controller.md", "document"),
        ForestNode("docs/helpers.md", "document"),
        ForestNode("docs/controller-extra.md", "document"),
    )
    edges = (
        ForestEdge(
            "src/controller.py",
            "src/sensor.py",
            "imports",
            True,
            evidence=("python-ast",),
        ),
        ForestEdge(
            "src/bias_helpers.py",
            "src/sensor.py",
            "imports",
            True,
            evidence=("python-ast",),
        ),
        ForestEdge(
            "src/sensor.py",
            "type:src/sensor.py#VoltageReading",
            "declares",
            True,
            evidence=("python-ast",),
        ),
        ForestEdge(
            "src/controller.py",
            "docs/controller.md",
            "documents",
            True,
            evidence=("markdown-link",),
        ),
        ForestEdge(
            "src/controller.py",
            "docs/controller-extra.md",
            "documents",
            True,
            evidence=("markdown-link",),
        ),
        ForestEdge(
            "src/bias_helpers.py",
            "docs/helpers.md",
            "documents",
            True,
            evidence=("markdown-link",),
        ),
        ForestEdge(
            "docs/controller.md",
            "type:src/sensor.py#VoltageReading",
            "mentions_type",
            True,
            evidence=("markdown-symbol",),
        ),
        ForestEdge(
            "docs/helpers.md",
            "type:src/sensor.py#TemperatureReading",
            "mentions_type",
            True,
            evidence=("markdown-symbol",),
        ),
    )
    return KnowledgeForest(
        root=".",
        nodes=nodes,
        edges=edges,
        hyperedges=(),
        provenance={"origin": "test.fourfold-hybrid"},
    )


def _snapshot(forest: KnowledgeForest):
    return fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=NOW,
        trace_id="fourfold-hybrid-test",
    )


def _consistent_type_plan() -> ContractionPlan:
    return ContractionPlan(
        name="imported-type-document-consistency",
        combine="intersection",
        paths=(
            PathExpression(
                name="declared_type",
                steps=(
                    RelationStep(RelationSignature("code", "imports", "code")),
                    RelationStep(RelationSignature("code", "declares", "type")),
                ),
            ),
            PathExpression(
                name="documented_type",
                steps=(
                    RelationStep(RelationSignature("code", "documents", "knowledge")),
                    RelationStep(
                        RelationSignature("knowledge", "mentions_type", "type")
                    ),
                ),
            ),
        ),
    )


def test_compiler_preserves_many_to_many_edges_and_is_deterministic() -> None:
    forest = _forest()
    snapshot = _snapshot(forest)

    first = compile_relation_blocks(forest, snapshot)
    second = compile_relation_blocks(forest, snapshot)
    documents = first.require(
        RelationSignature("code", "documents", "knowledge")
    )

    assert first.digest == second.digest
    assert documents.entry_count == 3
    assert tuple(
        cell.target_node_id
        for cell in documents.neighbors("src/controller.py")
    ) == ("docs/controller-extra.md", "docs/controller.md")
    assert all(cell.evidence_sha256s for cell in documents.cells)
    assert documents.subject.source_revision == REVISION
    assert documents.subject.source_fourfold_sha256 == snapshot.digest


def test_logical_intersection_compiles_to_indices_and_keeps_evidence() -> None:
    forest = _forest()
    catalog = compile_relation_blocks(forest, _snapshot(forest))
    plan = _consistent_type_plan()
    physical = PhysicalPlanner().compile(plan, catalog)

    assert physical.strategies == (
        "adjacency_lookup",
        "sparse_hash_join",
        "set_intersection",
    )

    result = ReferenceContractionExecutor().execute(
        physical,
        catalog,
        seeds=("src/controller.py",),
    )

    assert [hit.node_id for hit in result.hits] == [
        "type:src/sensor.py#VoltageReading"
    ]
    assert result.hits[0].branch_names == ("declared_type", "documented_type")
    assert result.hits[0].branch_coverage == 1.0
    assert result.hits[0].derivation_count == 2
    assert result.hits[0].evidence_sha256s

    mismatch = ReferenceContractionExecutor().execute(
        physical,
        catalog,
        seeds=("src/bias_helpers.py",),
    )
    assert mismatch.hits == ()


def test_hybrid_uses_bm25_as_seed_index_then_graph_expands_and_reranks() -> None:
    forest = _forest()
    catalog = compile_relation_blocks(forest, _snapshot(forest))
    plan = ContractionPlan(
        name="documentation-owner",
        paths=(
            PathExpression(
                name="documented_by",
                steps=(
                    RelationStep(
                        RelationSignature("code", "documents", "knowledge"),
                        direction="reverse",
                    ),
                ),
            ),
        ),
    )
    documents = (
        NodeDocument(
            "docs/controller.md",
            "knowledge",
            "detector bias migration voltage schema rename",
            locator="docs/controller.md",
        ),
        NodeDocument(
            "docs/helpers.md",
            "knowledge",
            "temperature helper notes",
            locator="docs/helpers.md",
        ),
        NodeDocument(
            "docs/controller-extra.md",
            "knowledge",
            "architecture overview",
            locator="docs/controller-extra.md",
        ),
        NodeDocument(
            "src/controller.py",
            "code",
            "event pipeline controller",
            locator="src/controller.py",
        ),
        NodeDocument(
            "src/bias_helpers.py",
            "code",
            "detector bias migration voltage schema rename placeholder helper",
            locator="src/bias_helpers.py",
        ),
        NodeDocument(
            "src/sensor.py",
            "code",
            "sensor reading declarations",
            locator="src/sensor.py",
        ),
    )
    retriever = HybridRetriever(catalog, documents)
    receipt = retriever.search(
        HybridRequest(
            query="detector bias migration voltage schema rename",
            plan=plan,
            seed_top_k=1,
            result_limit=3,
        )
    )

    assert receipt.lexical_seeds[0].node_id == "docs/controller.md"
    assert receipt.direct_candidates[0].node_id == "src/bias_helpers.py"
    assert receipt.hits[0].node_id == "src/controller.py"
    assert receipt.hits[0].supporting_seed_ids == ("docs/controller.md",)
    assert receipt.hits[0].branch_names == ("documented_by",)
    assert receipt.hits[0].graph_rrf > 0.0
    assert receipt.hits[0].evidence_sha256s
    assert receipt.proposal_only is True
    assert receipt.authority == "unverified-retrieval-proposal"
    assert len(receipt.digest) == 64


def test_compiler_refuses_snapshot_from_another_forest() -> None:
    forest = _forest()
    snapshot = _snapshot(forest)
    changed = KnowledgeForest(
        root=forest.root,
        nodes=forest.nodes,
        edges=tuple(reversed(forest.edges)),
        hyperedges=forest.hyperedges,
        provenance=forest.provenance,
    )

    assert changed.content_sha256 != forest.content_sha256
    with pytest.raises(ValueError, match="does not match"):
        compile_relation_blocks(changed, snapshot)


def test_executor_rejects_seed_from_the_wrong_plane() -> None:
    forest = _forest()
    catalog = compile_relation_blocks(forest, _snapshot(forest))
    physical = PhysicalPlanner().compile(_consistent_type_plan(), catalog)

    with pytest.raises(ValueError, match="start plane"):
        ReferenceContractionExecutor().execute(
            physical,
            catalog,
            seeds=("docs/controller.md",),
        )
