from __future__ import annotations

import hashlib

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "5" * 40
CREATED_AT = "2026-09-07T03:05:00+02:00"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture(*, retain_hyperedge: bool) -> tuple[KnowledgeForest, FourfoldSnapshot]:
    hyperedge = ForestHyperedge(
        id="clone_exact:pair",
        relation="clone_exact",
        members=("src/a.py", "src/b.py"),
        evidence=(_digest("clone_exact:pair"),),
    )
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
        ),
        edges=(
            ForestEdge(
                source="src/a.py",
                target="src/b.py",
                relation="imports",
                directed=True,
                evidence=(_digest("imports:a:b"),),
            ),
        ),
        hyperedges=(hyperedge,),
        provenance={
            "origin": "test.relation-compiler-hyperedge-retention",
            "source_revision": REVISION,
        },
    )
    legacy = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-hyperedge-retention-legacy",
    )
    hyperedge_digest = canonical_sha(hyperedge.to_dict())
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=("complete" if plane.plane == "code" else plane.status),
            node_ids=plane.node_ids,
            relation_sha256s=(
                plane.relation_sha256s
                if retain_hyperedge or plane.plane != "code"
                else tuple(
                    digest
                    for digest in plane.relation_sha256s
                    if digest != hyperedge_digest
                )
            ),
            evidence_sha256s=plane.evidence_sha256s,
            reason=("" if plane.plane == "code" else plane.reason),
        )
        for plane in legacy.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-hyperedge-retention",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in legacy.bindings),
        ),
        trace_id="relation-compiler-hyperedge-retention",
    )
    return forest, FourfoldSnapshot(
        repository_id=legacy.repository_id,
        source_revision=legacy.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=legacy.bindings,
        provenance=provenance,
    )


def test_discover_all_ignores_same_plane_hyperedge_not_retained_by_fourfold() -> None:
    forest, snapshot = _fixture(retain_hyperedge=False)

    compiled = compile_relation_blocks(forest, snapshot, BooleanSemiring())

    assert tuple(compiled.block_map) == ("code:imports:code",)
    assert tuple(compiled.block_map["code:imports:code"].iter_entries()) == (
        ("src/a.py", "src/b.py", True),
    )
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_hyperedge_count == 1


def test_predeclared_relation_treats_unretained_same_plane_hyperedge_as_absent() -> None:
    forest, snapshot = _fixture(retain_hyperedge=False)
    selected = RelationSignature("code", "clone_exact", "code")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    block = compiled.block_map[relation_block_name(selected)]
    assert tuple(block.iter_entries()) == ()
    assert compiled.semantic_fact_count == 0
    assert compiled.forest_hyperedge_count == 1


def test_retained_same_plane_hyperedge_still_refuses_pairwise_projection() -> None:
    forest, snapshot = _fixture(retain_hyperedge=True)

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        compile_relation_blocks(forest, snapshot, BooleanSemiring())
