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
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring, EvidenceDagSemiring

REVISION = "5" * 40
CREATED_AT = "2026-09-07T05:00:00+02:00"
SIGNATURE = RelationSignature("code", "imports", "code")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _edge(*, directed: bool = True) -> ForestEdge:
    return ForestEdge(
        source="src/a.py",
        target="src/b.py",
        relation="imports",
        directed=directed,
        evidence=(_digest("imports:a:b"),),
    )


def _forest(
    *,
    edge: ForestEdge | None = None,
    hyperedge: ForestHyperedge | None = None,
) -> KnowledgeForest:
    return KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
        ),
        edges=(() if edge is None else (edge,)),
        hyperedges=(() if hyperedge is None else (hyperedge,)),
        provenance={
            "origin": "test.relation-compiler-retention-authority",
            "source_revision": REVISION,
        },
    )


def _snapshot(
    forest: KnowledgeForest,
    *,
    retain_code_relations: bool,
) -> FourfoldSnapshot:
    base = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-retention-authority",
    )
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=("complete" if plane.plane == "code" else plane.status),
            node_ids=plane.node_ids,
            relation_sha256s=(
                plane.relation_sha256s
                if plane.plane != "code" or retain_code_relations
                else ()
            ),
            evidence_sha256s=plane.evidence_sha256s,
            reason=("" if plane.plane == "code" else plane.reason),
        )
        for plane in base.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-retention-authority.snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in base.bindings),
        ),
        trace_id="relation-compiler-retention-authority-snapshot",
    )
    return FourfoldSnapshot(
        repository_id=base.repository_id,
        source_revision=base.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=base.bindings,
        provenance=provenance,
    )


def test_unretained_same_plane_edge_matches_strict_boolean_empty_block() -> None:
    forest = _forest(edge=_edge())
    snapshot = _snapshot(forest, retain_code_relations=False)

    strict = boolean_relation_block_from_fourfold(forest, snapshot, SIGNATURE)
    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(SIGNATURE,),
    )
    multi = compiled.block_map[relation_block_name(SIGNATURE)]

    assert tuple(strict.iter_entries()) == ()
    assert tuple(multi.iter_entries()) == ()
    assert multi.digest == strict.digest
    assert compiled.semantic_fact_count == 0


def test_discover_all_does_not_discover_unretained_same_plane_edge() -> None:
    forest = _forest(edge=_edge())
    snapshot = _snapshot(forest, retain_code_relations=False)

    compiled = compile_relation_blocks(forest, snapshot, BooleanSemiring())

    assert tuple(compiled.block_map) == ()
    assert compiled.semantic_fact_count == 0


def test_retained_directed_same_plane_edge_remains_strictly_equivalent() -> None:
    forest = _forest(edge=_edge())
    snapshot = _snapshot(forest, retain_code_relations=True)

    strict = boolean_relation_block_from_fourfold(forest, snapshot, SIGNATURE)
    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(SIGNATURE,),
    )
    multi = compiled.block_map[relation_block_name(SIGNATURE)]

    assert tuple(multi.iter_entries()) == (("src/a.py", "src/b.py", True),)
    assert multi.digest == strict.digest
    assert compiled.semantic_fact_count == 1


def test_retained_undirected_same_plane_edge_still_refuses_projection() -> None:
    forest = _forest(edge=_edge(directed=False))
    snapshot = _snapshot(forest, retain_code_relations=True)

    with pytest.raises(ValueError, match="explicitly directed ForestEdge"):
        boolean_relation_block_from_fourfold(forest, snapshot, SIGNATURE)
    with pytest.raises(ValueError, match="cannot flatten undirected ForestEdge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(SIGNATURE,),
        )


def test_retained_same_plane_hyperedge_still_refuses_projection() -> None:
    hyperedge = ForestHyperedge(
        id="imports:pair",
        relation="imports",
        members=("src/a.py", "src/b.py"),
        evidence=(_digest("imports:pair"),),
    )
    forest = _forest(hyperedge=hyperedge)
    snapshot = _snapshot(forest, retain_code_relations=True)

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(SIGNATURE,),
        )
    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        boolean_relation_block_from_fourfold(forest, snapshot, SIGNATURE)


def test_unrelated_selection_prunes_unretained_edge_before_hash_or_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest = _forest(edge=_edge())
    snapshot = _snapshot(forest, retain_code_relations=False)
    unrelated = RelationSignature("code", "calls", "code")

    def forbidden_hash(value: object) -> str:
        raise AssertionError(f"unrelated Forest relation was hashed: {value!r}")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unrelated Forest evidence was materialized: {edge!r}")

    monkeypatch.setattr(relation_compiler, "canonical_sha", forbidden_hash)
    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(unrelated,),
    )

    block = compiled.block_map[relation_block_name(unrelated)]
    assert tuple(block.iter_entries()) == ()
    assert compiled.semantic_fact_count == 0
