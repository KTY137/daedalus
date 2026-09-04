from __future__ import annotations

import hashlib

import pytest

from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.contractions import (
    BlockRef,
    Compose,
    ContractionPlan,
    Hadamard,
)
from daedalus.twin.hybrid_retrieval import (
    FourfoldHybridRetriever,
    HybridDocument,
    document_from_node_card,
)
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import (
    compile_relation_blocks,
    relation_block_name,
)
from daedalus.twin.semiring import (
    BooleanSemiring,
    EvidenceDagSemiring,
    NaturalSemiring,
    TropicalSemiring,
)

REVISION = "a" * 40
CREATED_AT = "2026-09-03T12:00:00+02:00"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _edge(source: str, target: str, relation: str) -> ForestEdge:
    return ForestEdge(
        source=source,
        target=target,
        relation=relation,
        directed=True,
        evidence=(_digest(f"{relation}:{source}:{target}"),),
    )


def _fixture() -> tuple[KnowledgeForest, object]:
    nodes = (
        ForestNode("src/api.py", "source_file"),
        ForestNode("src/service.py", "source_file"),
        ForestNode("src/worker.py", "source_file"),
        ForestNode("src/broken.py", "source_file"),
        ForestNode("src/broken_dep.py", "source_file"),
        ForestNode("type:Event", "type"),
        ForestNode("type:Other", "type"),
        ForestNode("docs/api.md", "document"),
        ForestNode("docs/broken.md", "document"),
    )
    edges = (
        _edge("src/api.py", "src/worker.py", "imports"),
        _edge("src/service.py", "src/worker.py", "imports"),
        _edge("src/worker.py", "type:Event", "declares"),
        _edge("src/api.py", "docs/api.md", "documents"),
        _edge("src/service.py", "docs/api.md", "documents"),
        _edge("docs/api.md", "type:Event", "mentions_type"),
        _edge("src/broken.py", "src/broken_dep.py", "imports"),
        _edge("src/broken_dep.py", "type:Other", "declares"),
        _edge("src/broken.py", "docs/broken.md", "documents"),
        _edge("docs/broken.md", "type:Event", "mentions_type"),
    )
    forest = KnowledgeForest(
        root=".",
        nodes=nodes,
        edges=edges,
        hyperedges=(),
        provenance={
            "origin": "test.fourfold-hybrid-retrieval",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="fourfold-hybrid-retrieval",
    )
    return forest, snapshot


def _signature(source: str, relation: str, target: str) -> RelationSignature:
    return RelationSignature(source, relation, target)


def _plan() -> ContractionPlan:
    return ContractionPlan(
        output_name="consistent-documented-import-type",
        expression=Hadamard(
            Compose(
                BlockRef(relation_block_name(_signature("code", "imports", "code"))),
                BlockRef(relation_block_name(_signature("code", "declares", "type"))),
                "imported-declared-type",
            ),
            Compose(
                BlockRef(relation_block_name(_signature("code", "documents", "knowledge"))),
                BlockRef(
                    relation_block_name(
                        _signature("knowledge", "mentions_type", "type")
                    )
                ),
                "documented-mentioned-type",
            ),
            "consistent-documented-import-type",
        ),
    )


def _documents() -> tuple[HybridDocument, ...]:
    rows = {
        "src/api.py": ("code", "API voltage event reader"),
        "src/service.py": ("code", "Service voltage event facade"),
        "src/worker.py": ("code", "Worker implementation"),
        "src/broken.py": ("code", "Broken voltage handler"),
        "src/broken_dep.py": ("code", "Broken dependency implementation"),
        "type:Event": ("type", "Event voltage measurement type"),
        "type:Other": ("type", "Other unrelated type"),
        "docs/api.md": ("knowledge", "API documents the Event voltage contract"),
        "docs/broken.md": ("knowledge", "Broken docs mention Event"),
    }
    return tuple(
        HybridDocument(
            node_id=node_id,
            plane=plane,
            revision=REVISION,
            text=text,
            source_locator=node_id if "." in node_id else "",
        )
        for node_id, (plane, text) in rows.items()
    )


def test_compiler_uses_complete_plane_axes_and_deduplicates_bindings() -> None:
    forest, snapshot = _fixture()
    compiled = compile_relation_blocks(forest, snapshot, BooleanSemiring())

    imports = compiled.block_map[
        relation_block_name(_signature("code", "imports", "code"))
    ]
    declares = compiled.block_map[
        relation_block_name(_signature("code", "declares", "type"))
    ]

    assert imports.row_axis.labels == snapshot.plane_map["code"].node_ids
    assert imports.column_axis.labels == snapshot.plane_map["code"].node_ids
    assert tuple(declares.iter_entries()) == (
        ("src/broken_dep.py", "type:Other", True),
        ("src/worker.py", "type:Event", True),
    )
    assert compiled.semantic_fact_count == len(forest.edges)
    assert compiled.verified_binding_count == len(snapshot.bindings)


def test_compiler_emits_equivalent_boolean_natural_and_evidence_support() -> None:
    forest, snapshot = _fixture()
    signatures = (
        _signature("code", "declares", "type"),
        _signature("code", "calls", "code"),
    )
    boolean = compile_relation_blocks(
        forest, snapshot, BooleanSemiring(), signatures=signatures
    )
    natural = compile_relation_blocks(
        forest, snapshot, NaturalSemiring(), signatures=signatures
    )
    evidence = compile_relation_blocks(
        forest, snapshot, EvidenceDagSemiring(), signatures=signatures
    )

    declares_name = relation_block_name(signatures[0])
    empty_name = relation_block_name(signatures[1])
    boolean_keys = {
        (source, target)
        for source, target, _ in boolean.block_map[declares_name].iter_entries()
    }
    natural_values = {
        (source, target): value
        for source, target, value in natural.block_map[declares_name].iter_entries()
    }
    evidence_values = {
        (source, target): value
        for source, target, value in evidence.block_map[declares_name].iter_entries()
    }

    assert boolean_keys == set(natural_values) == set(evidence_values)
    assert set(natural_values.values()) == {1}
    assert all(value.alternatives for value in evidence_values.values())
    assert boolean.block_map[empty_name].entry_count == 0


def test_compiler_refuses_wrong_subject_and_undeclared_cost_semantics() -> None:
    forest, snapshot = _fixture()
    other = KnowledgeForest(
        root=forest.root,
        nodes=forest.nodes,
        edges=forest.edges[:-1],
        hyperedges=forest.hyperedges,
        provenance=forest.provenance,
    )

    with pytest.raises(ValueError, match="does not bind"):
        compile_relation_blocks(other, snapshot, BooleanSemiring())
    with pytest.raises(ValueError, match="explicit cost projection"):
        compile_relation_blocks(forest, snapshot, TropicalSemiring())


def test_hybrid_retrieval_fuses_lexical_seeds_with_typed_multihop_evidence() -> None:
    forest, snapshot = _fixture()
    retriever = FourfoldHybridRetriever(forest, snapshot, _documents())

    result = retriever.search(
        "api service voltage",
        _plan(),
        source_plane="code",
        target_plane="type",
        seed_limit=2,
        result_limit=5,
    )

    assert [seed.node_id for seed in result.source_seeds] == [
        "src/api.py",
        "src/service.py",
    ]
    assert [hit.node_id for hit in result.hits] == ["type:Event"]
    hit = result.hits[0]
    assert hit.supporting_seed_ids == ("src/api.py", "src/service.py")
    assert hit.path_count == 2
    assert hit.source_seed_rrf > 0.0
    assert hit.target_lexical_rrf > 0.0
    assert hit.graph_rrf > 0.0
    assert hit.evidence.alternatives
    assert result.authority == "unverified-retrieval-proposal"
    assert result.automatic_promotions == 0
    assert len(result.digest) == 64


def test_hybrid_retrieval_filters_semantically_inconsistent_lexical_hit() -> None:
    forest, snapshot = _fixture()
    retriever = FourfoldHybridRetriever(forest, snapshot, _documents())

    result = retriever.search(
        "broken voltage",
        _plan(),
        source_plane="code",
        target_plane="type",
        seed_limit=1,
    )

    assert result.source_seeds[0].node_id == "src/broken.py"
    assert result.hits == ()


def test_normal_lexical_fallback_remains_available_without_graph_execution() -> None:
    forest, snapshot = _fixture()
    retriever = FourfoldHybridRetriever(forest, snapshot, _documents())

    hits = retriever.lexical_search(
        "broken_dep",
        plane="code",
        limit=3,
    )

    assert hits[0].node_id == "src/broken_dep.py"


def test_hybrid_documents_must_bind_snapshot_identity() -> None:
    forest, snapshot = _fixture()
    invalid = HybridDocument(
        node_id="src/api.py",
        plane="knowledge",
        revision=REVISION,
        text="api",
    )
    with pytest.raises(ValueError, match="outside its declared plane"):
        FourfoldHybridRetriever(forest, snapshot, (invalid,))


def test_existing_node_card_shape_adapts_without_becoming_authority() -> None:
    card = {
        "schema": "forest-v2-node-card/2",
        "node_id": "code://src/api.py#function:read_event",
        "revision": REVISION,
        "plane": "code",
        "locator": {"path": "src/api.py"},
        "content": {
            "name": "read_event",
            "qualname": "api.read_event",
            "signature": "read_event() -> Event",
            "doc": "Read one voltage event.",
            "text": "def read_event(): ...",
        },
    }

    document = document_from_node_card(card)

    assert document.node_id == card["node_id"]
    assert document.source_locator == "src/api.py"
    assert "voltage" in document.text
