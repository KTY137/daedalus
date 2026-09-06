from __future__ import annotations

import hashlib

import daedalus.twin.relation_compiler as relation_compiler
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.semiring import BooleanSemiring

REVISION = "a" * 40
CREATED_AT = "2026-09-06T09:58:57+02:00"


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


def test_requested_signature_prunes_unrelated_edge_evidence_materialization(
    monkeypatch,
) -> None:
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
            "origin": "test.relation-compiler-signature-pruning-probe",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-signature-pruning-probe",
    )
    selected = RelationSignature("code", "declares", "type")
    original = relation_compiler._forest_edge_atoms

    def guarded(edge: ForestEdge) -> tuple[str, ...]:
        if edge.relation != selected.relation:
            raise AssertionError(
                "requested signatures materialized unrelated Forest evidence"
            )
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", guarded)

    compiled = relation_compiler.compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert tuple(compiled.block_map) == ("code:declares:type",)
    assert tuple(compiled.block_map["code:declares:type"].iter_entries()) == (
        ("src/worker.py", "type:Event", True),
    )
