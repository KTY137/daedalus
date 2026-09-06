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
from daedalus.twin.semiring import BooleanSemiring, EvidenceDagSemiring

REVISION = "5" * 40
CREATED_AT = "2026-09-06T21:58:02+02:00"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _snapshot_with_complete_planes(
    forest: KnowledgeForest,
    complete_planes: set[str],
) -> FourfoldSnapshot:
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-undirected-refusal",
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
            )
            if plane.plane in complete_planes
            else plane
        )
        for plane in snapshot.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-undirected-refusal",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in snapshot.bindings),
        ),
        trace_id="relation-compiler-undirected-refusal-complete",
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=snapshot.bindings,
        provenance=provenance,
    )


def _same_plane_fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
            ForestNode("src/c.py", "source_file"),
        ),
        edges=(
            ForestEdge(
                source="src/a.py",
                target="src/b.py",
                relation="peer",
                directed=False,
                evidence=(_digest("peer:a:b"),),
            ),
            ForestEdge(
                source="src/b.py",
                target="src/c.py",
                relation="imports",
                directed=True,
                evidence=(_digest("imports:b:c"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-undirected-refusal",
            "source_revision": REVISION,
        },
    )
    return forest, _snapshot_with_complete_planes(forest, {"code"})


def _cross_plane_fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("type:A", "type"),
        ),
        edges=(
            ForestEdge(
                source="src/a.py",
                target="type:A",
                relation="associated",
                directed=False,
                evidence=(_digest("associated:a:A"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-undirected-refusal-cross-plane",
            "source_revision": REVISION,
        },
    )
    planes = (
        PlaneSnapshot(
            plane="code",
            source_revision=REVISION,
            status="complete",
            node_ids=("src/a.py",),
            evidence_sha256s=(forest.content_sha256,),
        ),
        PlaneSnapshot(
            plane="type",
            source_revision=REVISION,
            status="complete",
            node_ids=("type:A",),
            evidence_sha256s=(forest.content_sha256,),
        ),
        PlaneSnapshot(
            plane="data",
            source_revision=REVISION,
            status="absent",
            reason="test fixture has no data-plane nodes",
        ),
        PlaneSnapshot(
            plane="knowledge",
            source_revision=REVISION,
            status="absent",
            reason="test fixture has no knowledge-plane nodes",
        ),
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-undirected-refusal-cross-plane.snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
        ),
        trace_id="relation-compiler-undirected-refusal-cross-plane-manual",
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


def test_discover_all_refuses_undirected_forest_edge_before_evidence_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _same_plane_fixture()

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="cannot flatten undirected ForestEdge"):
        compile_relation_blocks(forest, snapshot, EvidenceDagSemiring())


def test_explicit_matching_relation_refuses_undirected_forest_edge() -> None:
    forest, snapshot = _same_plane_fixture()
    selected = RelationSignature("code", "peer", "code")

    with pytest.raises(ValueError, match="cannot flatten undirected ForestEdge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(selected,),
        )


def test_explicit_reverse_cross_plane_relation_refuses_undirected_forest_edge() -> None:
    forest, snapshot = _cross_plane_fixture()
    selected = RelationSignature("type", "associated", "code")

    with pytest.raises(ValueError, match="cannot flatten undirected ForestEdge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(selected,),
        )


def test_explicit_unrelated_relation_skips_undirected_forest_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _same_plane_fixture()
    selected = RelationSignature("code", "imports", "code")
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def guarded_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        if edge.relation != "imports":
            raise AssertionError("unselected undirected evidence was materialized")
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", guarded_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(selected,),
    )

    assert observed_relations == ["imports"]
    assert tuple(compiled.block_map) == (relation_block_name(selected),)
    entries = tuple(compiled.block_map[relation_block_name(selected)].iter_entries())
    assert len(entries) == 1
    assert entries[0][:2] == ("src/b.py", "src/c.py")
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2
