from __future__ import annotations

import dataclasses

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import (
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
)
from daedalus.twin.delta import (
    GraphDelta,
    PlaneDelta,
    compute_graph_delta,
    parse_graph_delta,
    require_graph_delta,
)

BASE_REVISION = "a" * 40
CANDIDATE_REVISION = "b" * 40
CREATED_AT = "2026-08-03T13:00:00+00:00"


def digest(label: str) -> str:
    return canonical_sha({"label": label})


def plane(
    name: str,
    revision: str,
    *,
    nodes: tuple[str, ...],
    relations: tuple[str, ...] = (),
    evidence: tuple[str, ...],
    status: str = "complete",
    reason: str | None = None,
) -> PlaneSnapshot:
    return PlaneSnapshot(
        plane=name,
        source_revision=revision,
        status=status,
        node_ids=nodes,
        relation_sha256s=relations,
        evidence_sha256s=evidence,
        reason=reason,
    )


def binding(
    revision: str,
    *,
    source_plane: str,
    source_node: str,
    target_plane: str,
    target_node: str,
    relation: str,
    evidence: str,
) -> CrossPlaneBinding:
    return CrossPlaneBinding(
        source_plane=source_plane,
        source_node_id=source_node,
        target_plane=target_plane,
        target_node_id=target_node,
        relation=relation,
        source_revision=revision,
        evidence_sha256s=(evidence,),
    )


def snapshot(
    revision: str,
    *,
    repository_id: str = "delta-fixture",
    changed: bool = False,
) -> FourfoldSnapshot:
    code_nodes = ("code:a", "code:b") if not changed else ("code:b", "code:c")
    code_relation = digest("code-relation-old" if not changed else "code-relation-new")
    code_evidence = digest("code-evidence-old" if not changed else "code-evidence-new")
    knowledge_status = "complete" if not changed else "partial"
    knowledge_reason = None if not changed else "knowledge coverage remains partial"

    planes = (
        plane(
            "code",
            revision,
            nodes=code_nodes,
            relations=(code_relation,),
            evidence=(code_evidence,),
        ),
        plane(
            "type",
            revision,
            nodes=("type:a",),
            evidence=(digest("type-evidence"),),
        ),
        plane(
            "data",
            revision,
            nodes=("data:a",),
            evidence=(digest("data-evidence"),),
        ),
        plane(
            "knowledge",
            revision,
            nodes=("knowledge:a",),
            evidence=(digest("knowledge-evidence"),),
            status=knowledge_status,
            reason=knowledge_reason,
        ),
    )

    bindings = [
        binding(
            revision,
            source_plane="data",
            source_node="data:a",
            target_plane="knowledge",
            target_node="knowledge:a",
            relation="documents",
            evidence=digest(
                "data-doc-evidence-new" if changed else "data-doc-evidence-old"
            ),
        ),
        binding(
            revision,
            source_plane="code",
            source_node="code:b",
            target_plane="knowledge",
            target_node="knowledge:a",
            relation="documents",
            evidence=digest("stable-code-doc-evidence"),
        ),
    ]
    bindings.append(
        binding(
            revision,
            source_plane="code",
            source_node="code:c" if changed else "code:a",
            target_plane="type",
            target_node="type:a",
            relation="declares_type",
            evidence=digest("declares-type-new" if changed else "declares-type-old"),
        )
    )
    bindings_tuple = tuple(
        sorted(bindings, key=lambda item: item.semantic_key)
    )
    forest_sha = digest(f"forest-{revision}-{'changed' if changed else 'stable'}")
    provenance = ContractProvenance(
        origin="tests.graph-delta-snapshot",
        source_revision=revision,
        created_at=CREATED_AT,
        input_digests=(
            forest_sha,
            *(item.digest for item in planes),
            *(item.digest for item in bindings_tuple),
        ),
        trace_id="delta-fixture",
    )
    return FourfoldSnapshot(
        repository_id=repository_id,
        source_revision=revision,
        source_forest_sha256=forest_sha,
        planes=planes,
        bindings=bindings_tuple,
        provenance=provenance,
    )


def test_revision_only_rebuild_has_no_semantic_or_evidence_delta() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(CANDIDATE_REVISION)

    delta = compute_graph_delta(
        base,
        candidate,
        created_at=CREATED_AT,
        trace_id="revision-only",
    )

    assert delta.base_snapshot_sha256 != delta.candidate_snapshot_sha256
    assert delta.semantic_changed is False
    assert delta.evidence_changed is False
    assert delta.changed is False
    assert all(not item.changed for item in delta.plane_deltas)
    assert {item.change_kind for item in delta.binding_deltas} == {"unchanged"}
    require_graph_delta(delta, base, candidate)


def test_semantic_relation_reason_and_evidence_changes_are_retained() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(CANDIDATE_REVISION, changed=True)

    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)

    assert delta.semantic_changed is True
    assert delta.evidence_changed is True
    assert delta.changed is True

    by_plane = {item.plane: item for item in delta.plane_deltas}
    code = by_plane["code"]
    assert code.added_node_ids == ("code:c",)
    assert code.removed_node_ids == ("code:a",)
    assert len(code.added_relation_sha256s) == 1
    assert len(code.removed_relation_sha256s) == 1
    assert code.evidence_changed is True

    knowledge = by_plane["knowledge"]
    assert knowledge.base_status == "complete"
    assert knowledge.candidate_status == "partial"
    assert knowledge.candidate_reason == "knowledge coverage remains partial"
    assert knowledge.semantic_changed is True
    assert knowledge.evidence_changed is True

    kinds = [item.change_kind for item in delta.binding_deltas]
    assert kinds.count("added") == 1
    assert kinds.count("removed") == 1
    assert kinds.count("evidence_changed") == 1
    assert kinds.count("unchanged") == 1


def test_delta_is_deterministic_canonical_and_recomputed_before_use() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(CANDIDATE_REVISION, changed=True)

    first = compute_graph_delta(base, candidate, created_at=CREATED_AT)
    second = compute_graph_delta(base, candidate, created_at=CREATED_AT)
    assert first == second
    assert parse_graph_delta(first.to_dict()) == first

    wire = first.to_dict()
    wire["provenance"]["input_digests"].reverse()
    with pytest.raises(ValueError, match="wire is not canonical"):
        parse_graph_delta(wire)

    other_candidate = snapshot(CANDIDATE_REVISION)
    with pytest.raises(ValueError, match="does not match recomputed"):
        require_graph_delta(first, base, other_candidate)


def test_repository_mismatch_and_derived_flags_fail_closed() -> None:
    base = snapshot(BASE_REVISION)
    foreign = snapshot(CANDIDATE_REVISION, repository_id="other-repository")
    with pytest.raises(ValueError, match="same repository"):
        compute_graph_delta(base, foreign, created_at=CREATED_AT)

    candidate = snapshot(CANDIDATE_REVISION, changed=True)
    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)
    with pytest.raises(ValueError, match="changed must be derived"):
        dataclasses.replace(delta, changed=False)


def test_plane_partitions_and_absent_content_are_fail_closed() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(CANDIDATE_REVISION, changed=True)
    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)
    code = delta.plane_deltas[0]

    with pytest.raises(ValueError, match="pairwise disjoint"):
        dataclasses.replace(
            code,
            added_node_ids=("code:c",),
            retained_node_ids=("code:b", "code:c"),
        )

    with pytest.raises(ValueError, match="absent base plane"):
        PlaneDelta(
            plane="data",
            base_plane_sha256=digest("base-plane"),
            candidate_plane_sha256=digest("candidate-plane"),
            base_status="absent",
            candidate_status="complete",
            removed_evidence_sha256s=(digest("impossible-evidence"),),
        )


def test_delta_contract_round_trip_rejects_unknown_fields() -> None:
    delta = compute_graph_delta(
        snapshot(BASE_REVISION),
        snapshot(CANDIDATE_REVISION, changed=True),
        created_at=CREATED_AT,
    )
    assert GraphDelta.from_dict(delta.to_dict()) == delta
    payload = delta.to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        parse_graph_delta(payload)
