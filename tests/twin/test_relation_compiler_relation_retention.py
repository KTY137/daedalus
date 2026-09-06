from __future__ import annotations

import hashlib

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import EvidenceDagSemiring

REVISION = "5" * 40
CREATED_AT = "2026-09-06T23:00:00+02:00"


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


@pytest.mark.parametrize(
    "signatures",
    ((RelationSignature("code", "imports", "code"),), None),
)
def test_matching_or_discovered_same_plane_edge_requires_fourfold_relation_retention(
    signatures: tuple[RelationSignature, ...] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=False)

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected evidence materialization for {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="code plane does not retain ForestEdge 'imports' digest"):
        compile_relation_blocks(
            forest,
            snapshot,
            EvidenceDagSemiring(),
            signatures=signatures,
        )


def test_unrelated_explicit_relation_prunes_unretained_same_plane_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture(retain_code_relation=False)
    selected = RelationSignature("code", "references", "code")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unselected evidence was materialized for {edge.relation}")

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
    selected = RelationSignature("code", "imports", "code")
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
        signatures=(selected,),
    )

    block = compiled.block_map[relation_block_name(selected)]
    entries = tuple(block.iter_entries())
    assert observed == ["imports"]
    assert len(entries) == 1
    assert entries[0][:2] == ("src/api.py", "src/worker.py")
    assert compiled.semantic_fact_count == 1
