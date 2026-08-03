from __future__ import annotations

import ast
from pathlib import Path

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import CrossPlaneBinding, FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.delta import compute_graph_delta

BASE_REVISION = "c" * 40
CANDIDATE_REVISION = "d" * 40
CREATED_AT = "2026-08-03T13:30:00+00:00"


def digest(label: str) -> str:
    return canonical_sha({"label": label})


def snapshot(
    revision: str,
    *,
    code_relation: str = "stable-code-relation",
    knowledge_reason: str = "bounded knowledge coverage",
    binding_relation: str = "documents",
    binding_evidence: str = "stable-binding-evidence",
) -> FourfoldSnapshot:
    planes = (
        PlaneSnapshot(
            plane="code",
            source_revision=revision,
            status="complete",
            node_ids=("code:event",),
            relation_sha256s=(digest(code_relation),),
            evidence_sha256s=(digest("code-evidence"),),
        ),
        PlaneSnapshot(
            plane="type",
            source_revision=revision,
            status="complete",
            node_ids=("type:event",),
            evidence_sha256s=(digest("type-evidence"),),
        ),
        PlaneSnapshot(
            plane="data",
            source_revision=revision,
            status="complete",
            node_ids=("data:event",),
            evidence_sha256s=(digest("data-evidence"),),
        ),
        PlaneSnapshot(
            plane="knowledge",
            source_revision=revision,
            status="partial",
            node_ids=("knowledge:event",),
            evidence_sha256s=(digest("knowledge-evidence"),),
            reason=knowledge_reason,
        ),
    )
    binding = CrossPlaneBinding(
        source_plane="code",
        source_node_id="code:event",
        target_plane="knowledge",
        target_node_id="knowledge:event",
        relation=binding_relation,
        source_revision=revision,
        evidence_sha256s=(digest(binding_evidence),),
    )
    forest_sha = digest(f"forest-{revision}")
    provenance = ContractProvenance(
        origin="tests.graph-delta-review",
        source_revision=revision,
        created_at=CREATED_AT,
        input_digests=(
            forest_sha,
            *(item.digest for item in planes),
            binding.digest,
        ),
    )
    return FourfoldSnapshot(
        repository_id="delta-review-fixture",
        source_revision=revision,
        source_forest_sha256=forest_sha,
        planes=planes,
        bindings=(binding,),
        provenance=provenance,
    )


def test_relation_only_change_is_semantic_not_evidence_change() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(CANDIDATE_REVISION, code_relation="new-code-relation")

    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)

    assert delta.semantic_changed is True
    assert delta.evidence_changed is False
    code = delta.plane_deltas[0]
    assert len(code.added_relation_sha256s) == 1
    assert len(code.removed_relation_sha256s) == 1
    assert not code.added_node_ids
    assert not code.removed_node_ids


def test_reason_only_change_is_evidence_change_not_semantic_change() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(
        CANDIDATE_REVISION,
        knowledge_reason="different bounded coverage explanation",
    )

    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)

    assert delta.semantic_changed is False
    assert delta.evidence_changed is True
    knowledge = delta.plane_deltas[3]
    assert knowledge.base_status == knowledge.candidate_status == "partial"
    assert knowledge.base_reason != knowledge.candidate_reason
    assert knowledge.evidence_changed is True


def test_binding_evidence_change_does_not_become_remove_plus_add() -> None:
    base = snapshot(BASE_REVISION)
    candidate = snapshot(
        CANDIDATE_REVISION,
        binding_evidence="new-binding-evidence",
    )

    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)

    assert delta.semantic_changed is False
    assert delta.evidence_changed is True
    assert len(delta.binding_deltas) == 1
    assert delta.binding_deltas[0].change_kind == "evidence_changed"


def test_relation_replacement_is_one_removed_and_one_added_binding() -> None:
    base = snapshot(BASE_REVISION, binding_relation="documents")
    candidate = snapshot(CANDIDATE_REVISION, binding_relation="constrained_by")

    delta = compute_graph_delta(base, candidate, created_at=CREATED_AT)

    assert delta.semantic_changed is True
    assert [item.change_kind for item in delta.binding_deltas] == [
        "added",
        "removed",
    ] or [item.change_kind for item in delta.binding_deltas] == [
        "removed",
        "added",
    ]


def test_counter_review_comparison_has_no_application_authority() -> None:
    source = Path("daedalus/twin/delta.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "compute_graph_delta"
    )
    forbidden = {
        "apply",
        "publish",
        "promote",
        "write_text",
        "replace",
        "setattr",
        "update",
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not forbidden.intersection(calls)
