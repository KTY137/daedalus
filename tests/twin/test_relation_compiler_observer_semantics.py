from __future__ import annotations

import hashlib

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import (
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
)

REVISION = "5" * 40
CREATED_AT = "2026-09-06T19:01:01+02:00"
SIGNATURE = RelationSignature("code", "imports", "code")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _edge(evidence_label: str) -> ForestEdge:
    return ForestEdge(
        source="src/a.py",
        target="src/b.py",
        relation="imports",
        directed=True,
        evidence=(_digest(evidence_label),),
    )


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
        ),
        edges=(_edge("witness-a"), _edge("witness-b")),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-observer-semantics",
            "source_revision": REVISION,
        },
    )
    projected = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-observer-semantics",
    )
    planes = tuple(
        (
            PlaneSnapshot(
                plane=plane.plane,
                source_revision=plane.source_revision,
                status="complete",
                node_ids=plane.node_ids,
                relation_sha256s=plane.relation_sha256s,
                evidence_sha256s=plane.evidence_sha256s,
                reason="",
            )
            if plane.plane == "code"
            else plane
        )
        for plane in projected.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-observer-semantics.complete-code",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in projected.bindings),
        ),
        trace_id="relation-compiler-observer-semantics-complete-code",
    )
    return forest, FourfoldSnapshot(
        repository_id=projected.repository_id,
        source_revision=projected.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=projected.bindings,
        provenance=provenance,
    )


def _single_value(compiled: object) -> object:
    block = compiled.block_map[relation_block_name(SIGNATURE)]  # type: ignore[attr-defined]
    entries = tuple(block.iter_entries())
    assert len(entries) == 1
    assert entries[0][:2] == ("src/a.py", "src/b.py")
    return entries[0][2]


def test_boolean_observer_collapses_duplicate_witnesses_to_existence() -> None:
    forest, snapshot = _fixture()

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(SIGNATURE,),
    )

    assert _single_value(compiled) is True
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


def test_natural_observer_counts_semantic_paths_not_ingest_witnesses() -> None:
    forest, snapshot = _fixture()

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        NaturalSemiring(),
        signatures=(SIGNATURE,),
    )

    assert _single_value(compiled) == 1
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


def test_evidence_observer_retains_alternative_witness_bundles() -> None:
    forest, snapshot = _fixture()

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(SIGNATURE,),
    )

    value = _single_value(compiled)
    assert isinstance(value, EvidenceValue)
    expected = {
        tuple(sorted({canonical_sha(edge.to_dict()), *edge.evidence}))
        for edge in forest.edges
    }
    assert set(value.alternatives) == expected
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


class AlternateNaturalBackend:
    name = "natural"
    zero = 0
    one = 1

    @staticmethod
    def add(left: int, right: int) -> int:
        return left + right

    @staticmethod
    def multiply(left: int, right: int) -> int:
        return left * right


def test_compiler_preserves_protocol_backend_substitution_by_semantic_name() -> None:
    forest, snapshot = _fixture()

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        AlternateNaturalBackend(),
        signatures=(SIGNATURE,),
    )

    assert compiled.semiring_name == "natural"
    assert _single_value(compiled) == 1
