from __future__ import annotations

import hashlib

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "6" * 40
CREATED_AT = "2026-09-09T00:00:00+02:00"
IMPORTS = RelationSignature("code", "imports", "code")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    edges = (
        ForestEdge(
            source="src/a.py",
            target="src/b.py",
            relation="imports",
            directed=True,
            evidence=(_digest("a-imports-b"),),
        ),
        ForestEdge(
            source="src/c.py",
            target="src/a.py",
            relation="imports",
            directed=True,
            evidence=(_digest("c-imports-a"),),
        ),
    )
    forest_edges = tuple(
        sorted(edges, key=lambda edge: canonical_sha(edge.to_dict()), reverse=True)
    )
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
            ForestNode("src/c.py", "source_file"),
        ),
        edges=forest_edges,
        hyperedges=(),
        provenance={
            "origin": "test.relation-digest-authority-seam",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-digest-authority-seam",
    )
    return forest, snapshot


def _complete_code_snapshot(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> FourfoldSnapshot:
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status=("complete" if plane.plane == "code" else plane.status),
            node_ids=plane.node_ids,
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
            reason=("" if plane.plane == "code" else plane.reason),
        )
        for plane in snapshot.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-digest-authority-seam.complete",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in snapshot.bindings),
        ),
        trace_id="relation-digest-authority-seam-complete",
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=snapshot.bindings,
        provenance=provenance,
    )


def test_plane_relation_digests_are_a_canonical_set_not_a_forest_order_map() -> None:
    forest, snapshot = _fixture()
    code_plane = snapshot.plane_map["code"]
    forest_order = tuple(canonical_sha(edge.to_dict()) for edge in forest.edges)

    assert forest_order == tuple(sorted(forest_order, reverse=True))
    assert code_plane.relation_sha256s == tuple(sorted(forest_order))
    assert code_plane.relation_sha256s != forest_order


def test_compiler_remains_correct_when_digest_order_cannot_identify_edge_position() -> None:
    forest, snapshot = _fixture()
    complete = _complete_code_snapshot(forest, snapshot)

    compiled = compile_relation_blocks(
        forest,
        complete,
        BooleanSemiring(),
        signatures=(IMPORTS,),
    )
    block = compiled.block_map[relation_block_name(IMPORTS)]

    assert tuple(block.iter_entries()) == (
        ("src/a.py", "src/b.py", True),
        ("src/c.py", "src/a.py", True),
    )
    assert compiled.semantic_fact_count == 2
