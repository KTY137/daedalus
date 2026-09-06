from __future__ import annotations

import hashlib

import pytest

from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import relation_compiler
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "4" * 40
CREATED_AT = "2026-09-06T11:00:00+02:00"


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
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("src/worker.py", "source_file"),
            ForestNode("type:Event", "type"),
        ),
        edges=(
            _edge("src/api.py", "src/worker.py", "imports"),
            _edge("src/worker.py", "type:Event", "declares"),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-selected-pruning",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-selected-pruning",
    )
    return forest, snapshot


def test_explicit_signature_prunes_unselected_evidence_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "declares", "type")
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def guarded_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        if edge.relation != "declares":
            raise AssertionError("unselected Forest evidence was materialized")
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", guarded_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert observed_relations == ["declares"]
    assert tuple(compiled.block_map) == (relation_block_name(selected),)
    assert tuple(compiled.block_map[relation_block_name(selected)].iter_entries()) == (
        ("src/worker.py", "type:Event", True),
    )
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.verified_binding_count == len(snapshot.bindings)


def test_explicit_signature_contract_is_validated_before_edge_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="RelationSignature records"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(object(),),  # type: ignore[arg-type]
        )


def test_discover_all_keeps_existing_forest_materialization_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def recording_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", recording_atoms)

    compiled = compile_relation_blocks(forest, snapshot, BooleanSemiring())

    assert observed_relations == ["imports", "declares"]
    assert set(compiled.block_map) == {
        "code:imports:code",
        "code:declares:type",
    }
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.verified_binding_count == len(snapshot.bindings)
