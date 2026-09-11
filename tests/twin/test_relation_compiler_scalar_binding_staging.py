from __future__ import annotations

import hashlib
import inspect

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import CrossPlaneBinding, FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring, NaturalSemiring

REVISION = "6" * 40
CREATED_AT = "2026-09-09T17:57:17+02:00"
SIGNATURE = RelationSignature("code", "declares", "type")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/worker.py", "source_file"),
            ForestNode("type:Event", "type"),
        ),
        edges=(
            ForestEdge(
                source="src/worker.py",
                target="type:Event",
                relation="declares",
                directed=True,
                evidence=(_digest("declares:worker:event"),),
            ),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-scalar-binding-staging",
            "source_revision": REVISION,
        },
    )
    projected = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-scalar-binding-staging",
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
            if plane.plane in {"code", "type"}
            else plane
        )
        for plane in projected.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-scalar-binding-staging.complete",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in projected.bindings),
        ),
        trace_id="relation-compiler-scalar-binding-staging-complete",
    )
    snapshot = FourfoldSnapshot(
        repository_id=projected.repository_id,
        source_revision=projected.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=projected.bindings,
        provenance=provenance,
    )
    assert len(snapshot.bindings) == 1
    return forest, snapshot


@pytest.mark.parametrize(
    ("semiring", "expected_value"),
    ((BooleanSemiring(), True), (NaturalSemiring(), 1)),
)
def test_scalar_binding_staging_keeps_no_cross_plane_binding_object(
    monkeypatch: pytest.MonkeyPatch,
    semiring: object,
    expected_value: object,
) -> None:
    forest, snapshot = _fixture()
    original_record_fact = relation_compiler._record_fact
    inspected = False

    def inspecting_record_fact(*args: object, **kwargs: object) -> None:
        nonlocal inspected
        if kwargs.get("signature") == SIGNATURE:
            frame = inspect.currentframe()
            assert frame is not None and frame.f_back is not None
            compiler_locals = frame.f_back.f_locals
            assert "included_binding_keys" not in compiler_locals
            binding_records_by_key = compiler_locals["binding_records_by_key"]
            binding_records = compiler_locals["binding_records"]
            assert isinstance(binding_records_by_key, dict)
            records = tuple(binding_records)
            assert records == tuple(binding_records_by_key.values())
            assert tuple(binding_records_by_key) == (
                ("code", "src/worker.py", "type", "type:Event", "declares"),
            )
            assert records
            assert all(
                not any(isinstance(value, CrossPlaneBinding) for value in record)
                for record in records
            )
            assert all(record[-1] is None for record in records)
            assert kwargs.get("evidence_atoms") is None
            inspected = True
        original_record_fact(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "_record_fact", inspecting_record_fact)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        semiring,  # type: ignore[arg-type]
        signatures=(SIGNATURE,),
    )

    assert inspected
    entries = tuple(compiled.block_map[relation_block_name(SIGNATURE)].iter_entries())
    assert entries == (("src/worker.py", "type:Event", expected_value),)
    assert compiled.semantic_fact_count == 1
    assert compiled.verified_binding_count == 1
