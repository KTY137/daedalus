from __future__ import annotations

import hashlib

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "6" * 40
CREATED_AT = "2026-09-09T07:57:55+02:00"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _complete_code_snapshot(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> FourfoldSnapshot:
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status="complete" if plane.plane == "code" else plane.status,
            node_ids=plane.node_ids,
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
            reason="" if plane.plane == "code" else plane.reason,
        )
        for plane in snapshot.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-selected-signature-reuse",
        source_revision=snapshot.source_revision,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in snapshot.bindings),
        ),
        trace_id="relation-compiler-selected-signature-reuse",
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=snapshot.bindings,
        provenance=provenance,
    )


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
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
                evidence=(_digest("imports"),),
            ),
            ForestEdge(
                source="src/b.py",
                target="src/a.py",
                relation="calls",
                directed=True,
                evidence=(_digest("calls"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-selected-signature-reuse",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-selected-signature-reuse",
    )
    return forest, _complete_code_snapshot(forest, snapshot)


def test_explicit_plan_reuses_validated_signature_without_per_edge_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "imports", "code")
    constructed: list[tuple[str, str, str]] = []
    original_init = RelationSignature.__init__

    def tracking_init(
        self: RelationSignature,
        source_plane: str,
        relation: str,
        target_plane: str,
    ) -> None:
        constructed.append((source_plane, relation, target_plane))
        original_init(self, source_plane, relation, target_plane)

    monkeypatch.setattr(RelationSignature, "__init__", tracking_init)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    block = compiled.block_map[relation_block_name(selected)]
    assert constructed == []
    assert block.signature is selected
    assert tuple(block.iter_entries()) == (("src/a.py", "src/b.py", True),)
    assert compiled.semantic_fact_count == 1
