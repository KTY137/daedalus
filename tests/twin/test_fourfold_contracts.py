from __future__ import annotations

import json

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.twin import (
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
    fourfold_from_knowledge_forest,
    parse_fourfold_snapshot,
)

REVISION = "a" * 40
NOW = "2026-08-01T10:00:00Z"


def sample_forest() -> KnowledgeForest:
    return KnowledgeForest(
        root="/repo",
        nodes=(
            ForestNode("src/app.py", "source_file", {"language": "python"}),
            ForestNode("type:src/app.py#Config", "type", {"name": "Config"}),
            ForestNode("field:src/app.py#Config.value", "field", {"name": "value"}),
            ForestNode("docs/design.md", "document", {"kind": "document"}),
        ),
        edges=(
            ForestEdge(
                "type:src/app.py#Config",
                "field:src/app.py#Config.value",
                "has_field",
                True,
                evidence=("structcore.type_edges",),
            ),
            ForestEdge(
                "src/app.py",
                "type:src/app.py#Config",
                "produces",
                True,
                evidence=("structcore.type_edges",),
            ),
            ForestEdge(
                "docs/design.md",
                "src/app.py",
                "documents",
                True,
                evidence=("structcore.document_links",),
            ),
        ),
        hyperedges=(
            ForestHyperedge(
                id="clone_exact:one",
                relation="clone_exact",
                members=("src/app.py",),
                evidence=("fixture",),
            ),
        ),
        provenance={"source_schema": "test"},
    )


def adapted() -> FourfoldSnapshot:
    return fourfold_from_knowledge_forest(
        sample_forest(),
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-fourfold-test",
    )


def test_legacy_adapter_is_deterministic_and_covers_exactly_four_planes():
    first = adapted()
    second = adapted()

    assert first.to_json() == second.to_json()
    assert first.digest == second.digest
    assert tuple(first.plane_map) == ("code", "type", "data", "knowledge")
    assert first.plane_map["data"].status == "absent"
    assert first.plane_map["data"].node_ids == ()
    assert "no canonical Data Plane" in first.plane_map["data"].reason
    assert all(
        first.plane_map[name].status == "partial"
        for name in ("code", "type", "knowledge")
    )


def test_adapter_maps_only_evidence_backed_cross_plane_relations():
    snapshot = adapted()
    relations = {
        (binding.source_plane, binding.target_plane, binding.relation)
        for binding in snapshot.bindings
    }

    assert relations == {
        ("code", "type", "produces"),
        ("knowledge", "code", "documents"),
    }
    assert all(binding.assurance == "verified" for binding in snapshot.bindings)
    assert all(binding.evidence_sha256s for binding in snapshot.bindings)
    assert snapshot.plane_map["type"].relation_sha256s


def test_snapshot_computes_each_binding_digest_once_during_canonicalization(monkeypatch):
    snapshot = adapted()
    original_digest = CrossPlaneBinding.digest.fget
    assert original_digest is not None
    calls = 0

    def counted_digest(binding: CrossPlaneBinding) -> str:
        nonlocal calls
        calls += 1
        return original_digest(binding)

    monkeypatch.setattr(CrossPlaneBinding, "digest", property(counted_digest))
    rebuilt = FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=snapshot.planes,
        bindings=snapshot.bindings,
        provenance=snapshot.provenance,
    )

    assert rebuilt == snapshot
    assert calls == len(snapshot.bindings)


def test_snapshot_round_trips_strictly_and_rejects_unknown_fields():
    snapshot = adapted()
    parsed = parse_fourfold_snapshot(json.loads(snapshot.to_json()))

    assert parsed == snapshot
    assert parsed.digest == snapshot.digest

    malformed = snapshot.to_dict()
    malformed["pretend_field"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_fourfold_snapshot(malformed)


def test_snapshot_refuses_mixed_revisions_and_missing_planes():
    snapshot = adapted()
    planes = list(snapshot.planes)
    planes[0] = PlaneSnapshot(
        plane="code",
        source_revision="b" * 40,
        status="partial",
        node_ids=planes[0].node_ids,
        relation_sha256s=planes[0].relation_sha256s,
        evidence_sha256s=planes[0].evidence_sha256s,
        reason="fixture mismatch",
    )
    with pytest.raises(ValueError, match="every plane must bind"):
        FourfoldSnapshot(
            repository_id=snapshot.repository_id,
            source_revision=snapshot.source_revision,
            source_forest_sha256=snapshot.source_forest_sha256,
            planes=tuple(planes),
            bindings=snapshot.bindings,
            provenance=snapshot.provenance,
        )

    with pytest.raises(ValueError, match="exactly cover"):
        FourfoldSnapshot(
            repository_id=snapshot.repository_id,
            source_revision=snapshot.source_revision,
            source_forest_sha256=snapshot.source_forest_sha256,
            planes=snapshot.planes[:-1],
            bindings=(),
            provenance=snapshot.provenance,
        )


def test_absent_and_partial_planes_must_explain_their_state():
    with pytest.raises(ValueError, match="absent plane must retain a reason"):
        PlaneSnapshot(
            plane="data",
            source_revision=REVISION,
            status="absent",
        )
    with pytest.raises(ValueError, match="absent plane cannot contain"):
        PlaneSnapshot(
            plane="data",
            source_revision=REVISION,
            status="absent",
            node_ids=("schema:fake",),
            reason="not extracted",
        )
    with pytest.raises(ValueError, match="partial plane must explain"):
        PlaneSnapshot(
            plane="type",
            source_revision=REVISION,
            status="partial",
            node_ids=("type:x#Y",),
        )


def test_snapshot_refuses_unverified_or_dangling_cross_plane_bindings():
    with pytest.raises(ValueError, match="only verified bindings"):
        CrossPlaneBinding(
            source_plane="code",
            source_node_id="src/app.py",
            target_plane="type",
            target_node_id="type:src/app.py#Config",
            relation="produces",
            source_revision=REVISION,
            evidence_sha256s=("1" * 64,),
            assurance="proposed",
        )

    snapshot = adapted()
    binding = CrossPlaneBinding(
        source_plane="code",
        source_node_id="src/missing.py",
        target_plane="type",
        target_node_id="type:src/app.py#Config",
        relation="produces",
        source_revision=REVISION,
        evidence_sha256s=("1" * 64,),
    )
    plane_digests = tuple(plane.digest for plane in snapshot.planes)
    provenance = ContractProvenance(
        origin="test.fourfold",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(snapshot.source_forest_sha256, *plane_digests, binding.digest),
    )
    with pytest.raises(ValueError, match="source endpoint"):
        FourfoldSnapshot(
            repository_id=snapshot.repository_id,
            source_revision=REVISION,
            source_forest_sha256=snapshot.source_forest_sha256,
            planes=snapshot.planes,
            bindings=(binding,),
            provenance=provenance,
        )


def test_input_order_and_mutation_do_not_change_retained_snapshot():
    node_ids = ["z.py", "a.py"]
    plane = PlaneSnapshot(
        plane="code",
        source_revision=REVISION,
        status="partial",
        node_ids=node_ids,
        evidence_sha256s=("2" * 64,),
        reason="fixture",
    )
    before = plane.digest
    node_ids.append("later.py")

    assert plane.node_ids == ("a.py", "z.py")
    assert plane.digest == before


def test_adapter_refuses_unknown_node_kinds_instead_of_guessing_a_plane():
    forest = KnowledgeForest(
        root="/repo",
        nodes=(ForestNode("runtime:trace", "runtime_span", {}),),
        edges=(),
        hyperedges=(),
        provenance={},
    )
    with pytest.raises(ValueError, match="unmapped kind"):
        fourfold_from_knowledge_forest(
            forest,
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            created_at=NOW,
        )
