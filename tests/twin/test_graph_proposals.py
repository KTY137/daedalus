from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin import (
    CrossPlaneBinding,
    FourfoldSnapshot,
    GraphOperation,
    GraphProposal,
    GraphWritableScope,
    PlaneSnapshot,
    ProposalVerificationReport,
    parse_graph_proposal,
    parse_proposal_verification_report,
    require_graph_proposal_verification,
    verify_graph_proposal,
)
from daedalus.spine.envelope import canonical_sha

REVISION = "a" * 40
FOREST_SHA = "f" * 64
MODEL_SHA = "1" * 64
RUNTIME_SHA = "2" * 64
CONTEXT_SHA = "3" * 64
POLICY_SHA = "4" * 64
CREATED_AT = "2026-08-03T12:00:00+00:00"
EVIDENCE = tuple(f"{value:064x}" for value in range(10, 20))


def snapshot(*, revision: str = REVISION) -> FourfoldSnapshot:
    plane_nodes = {
        "code": ("code:a", "code:b", "code:c"),
        "type": ("type:a",),
        "data": ("data:a",),
        "knowledge": ("knowledge:a", "knowledge:b"),
    }
    planes = tuple(
        PlaneSnapshot(
            plane=plane,
            source_revision=revision,
            status="complete",
            node_ids=nodes,
            evidence_sha256s=(canonical_sha({"plane": plane, "revision": revision}),),
        )
        for plane, nodes in plane_nodes.items()
    )
    bindings = (
        CrossPlaneBinding(
            source_plane="code",
            source_node_id="code:a",
            target_plane="type",
            target_node_id="type:a",
            relation="declares_type",
            source_revision=revision,
            evidence_sha256s=(EVIDENCE[0],),
        ),
        CrossPlaneBinding(
            source_plane="data",
            source_node_id="data:a",
            target_plane="knowledge",
            target_node_id="knowledge:a",
            relation="documents",
            source_revision=revision,
            evidence_sha256s=(EVIDENCE[1],),
        ),
    )
    provenance = ContractProvenance(
        origin="tests.graph-proposal-snapshot",
        source_revision=revision,
        created_at=CREATED_AT,
        input_digests=(
            FOREST_SHA,
            *(item.digest for item in planes),
            *(item.digest for item in bindings),
        ),
    )
    return FourfoldSnapshot(
        repository_id="proposal-fixture",
        source_revision=revision,
        source_forest_sha256=FOREST_SHA,
        planes=planes,
        bindings=bindings,
        provenance=provenance,
    )


def operations(base: FourfoldSnapshot) -> tuple[GraphOperation, ...]:
    return (
        GraphOperation(
            operation_id="op-01-add",
            kind="add_binding",
            source_plane="code",
            source_node_id="code:b",
            target_plane="knowledge",
            target_node_id="knowledge:b",
            relation="documents",
            evidence_sha256s=(EVIDENCE[2],),
        ),
        GraphOperation(
            operation_id="op-02-remove",
            kind="remove_binding",
            source_plane="code",
            source_node_id="code:a",
            target_plane="type",
            target_node_id="type:a",
            relation="declares_type",
            binding_sha256=base.bindings[0].digest,
            evidence_sha256s=(EVIDENCE[3],),
        ),
        GraphOperation(
            operation_id="op-03-rename",
            kind="rename_concept",
            source_plane="code",
            source_node_id="code:c",
            replacement="bias_voltage",
            evidence_sha256s=(EVIDENCE[4],),
        ),
        GraphOperation(
            operation_id="op-04-replace",
            kind="replace_relation",
            source_plane="data",
            source_node_id="data:a",
            target_plane="knowledge",
            target_node_id="knowledge:a",
            relation="documents",
            replacement="describes",
            binding_sha256=base.bindings[1].digest,
            evidence_sha256s=(EVIDENCE[5],),
        ),
    )


def scope() -> GraphWritableScope:
    return GraphWritableScope(
        planes=("code", "data", "knowledge", "type"),
        node_ids=(
            "code:a",
            "code:b",
            "code:c",
            "data:a",
            "knowledge:a",
            "knowledge:b",
            "type:a",
        ),
        relations=("declares_type", "describes", "documents"),
        allow_new_bindings=True,
        allow_removals=True,
        allow_renames=True,
        allow_relation_replacement=True,
    )


def proposal(base: FourfoldSnapshot, *, ops=None, writable_scope=None) -> GraphProposal:
    chosen_ops = operations(base) if ops is None else tuple(ops)
    chosen_scope = scope() if writable_scope is None else writable_scope
    provenance = ContractProvenance(
        origin="tests.graph-proposal",
        source_revision=base.source_revision,
        created_at=CREATED_AT,
        input_digests=(
            base.digest,
            MODEL_SHA,
            RUNTIME_SHA,
            CONTEXT_SHA,
            chosen_scope.digest,
            *(item.digest for item in chosen_ops),
        ),
        trace_id="proposal-fixture",
    )
    return GraphProposal(
        proposal_id="proposal-1",
        base_snapshot_sha256=base.digest,
        source_revision=base.source_revision,
        objective="Rename one concept and update verified semantic bindings.",
        model_manifest_sha256=MODEL_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        context_capsule_sha256=CONTEXT_SHA,
        budget_microusd=5000,
        scope=chosen_scope,
        operations=chosen_ops,
        provenance=provenance,
    )


def verify(value: GraphProposal, base: FourfoldSnapshot, *, evidence=None, relations=None):
    return verify_graph_proposal(
        value,
        base,
        verified_evidence_sha256s=(
            tuple(item for op in value.operations for item in op.evidence_sha256s)
            if evidence is None
            else evidence
        ),
        allowed_relations=(
            ("declares_type", "describes", "documents")
            if relations is None
            else relations
        ),
        verifier_id="deterministic-graph-policy-v1",
        verifier_policy_sha256=POLICY_SHA,
        created_at=CREATED_AT,
        trace_id="proposal-fixture",
    )


def test_all_operation_families_verify_without_mutating_snapshot() -> None:
    base = snapshot()
    before = base.digest
    value = proposal(base)

    report = verify(value, base)

    assert report.all_accepted is True
    assert [item.verdict for item in report.decisions] == ["accepted"] * 4
    assert base.digest == before
    assert FourfoldSnapshot.from_dict(base.to_dict()) == base
    require_graph_proposal_verification(
        report,
        value,
        base,
        verified_evidence_sha256s=tuple(
            item for op in value.operations for item in op.evidence_sha256s
        ),
        allowed_relations=("declares_type", "describes", "documents"),
        expected_verifier_id="deterministic-graph-policy-v1",
        expected_verifier_policy_sha256=POLICY_SHA,
    )


def test_contracts_round_trip_and_refuse_noncanonical_operation_order() -> None:
    base = snapshot()
    value = proposal(base)
    report = verify(value, base)

    assert parse_graph_proposal(value.to_dict()) == value
    assert parse_proposal_verification_report(report.to_dict()) == report

    payload = value.to_dict()
    payload["operations"] = list(reversed(payload["operations"]))
    with pytest.raises(ValueError, match="sorted"):
        parse_graph_proposal(payload)

    payload = value.to_dict()
    payload["unknown"] = True
    with pytest.raises(ValueError, match="unknown"):
        parse_graph_proposal(payload)

    payload = value.to_dict()
    payload["provenance"]["input_digests"].reverse()
    with pytest.raises(ValueError, match="not canonical"):
        parse_graph_proposal(payload)

    payload = report.to_dict()
    payload["decisions"][0]["reasons"] = list(
        reversed(payload["decisions"][0]["reasons"])
    )
    # A single accepted reason cannot demonstrate reordering; reorder the
    # provenance inputs instead and require exact-wire refusal.
    payload["provenance"]["input_digests"].reverse()
    with pytest.raises(ValueError, match="not canonical"):
        parse_proposal_verification_report(payload)


def test_stale_snapshot_unverified_evidence_and_relation_policy_fail_closed() -> None:
    base = snapshot()
    value = proposal(base)
    stale = snapshot(revision="b" * 40)

    stale_report = verify(value, stale)
    assert stale_report.all_accepted is False
    assert all(
        {"stale-base-snapshot", "stale-source-revision"} <= set(item.reasons)
        for item in stale_report.decisions
    )

    no_evidence = verify(value, base, evidence=())
    assert all("unverified-evidence" in item.reasons for item in no_evidence.decisions)

    narrow_policy = verify(value, base, relations=("declares_type",))
    by_id = {item.operation_id: item for item in narrow_policy.decisions}
    assert "relation-not-allowed" in by_id["op-01-add"].reasons
    assert "replacement-relation-not-allowed" in by_id["op-04-replace"].reasons


def test_scope_and_binding_substitution_are_rejected() -> None:
    base = snapshot()
    add = operations(base)[0]
    narrow = GraphWritableScope(
        planes=("code", "knowledge"),
        node_ids=("code:a", "knowledge:a"),
        relations=("documents",),
        allow_new_bindings=True,
    )
    report = verify(proposal(base, ops=(add,), writable_scope=narrow), base)
    assert {
        "source-node-outside-scope",
        "target-node-outside-scope",
    } <= set(report.decisions[0].reasons)

    remove = dataclasses.replace(
        operations(base)[1],
        binding_sha256=base.bindings[1].digest,
    )
    report = verify(proposal(base, ops=(remove,)), base)
    assert "binding-identity-mismatch" in report.decisions[0].reasons


def test_conflicting_operations_are_rejected_together() -> None:
    base = snapshot()
    remove = operations(base)[1]
    replace_same = GraphOperation(
        operation_id="op-05-replace-same",
        kind="replace_relation",
        source_plane=remove.source_plane,
        source_node_id=remove.source_node_id,
        target_plane=remove.target_plane,
        target_node_id=remove.target_node_id,
        relation=remove.relation,
        replacement="describes",
        binding_sha256=remove.binding_sha256,
        evidence_sha256s=(EVIDENCE[6],),
    )
    value = proposal(base, ops=(remove, replace_same))
    report = verify(value, base)
    assert all("conflicting-operation" in item.reasons for item in report.decisions)


def test_report_must_be_recomputed_before_consumption() -> None:
    base = snapshot()
    value = proposal(base)
    report = verify(value, base)
    forged_decisions = (
        dataclasses.replace(
            report.decisions[0],
            verdict="rejected",
            reasons=("policy-denied",),
        ),
        *report.decisions[1:],
    )
    forged_provenance = ContractProvenance(
        origin="daedalus.twin.graph-proposal-verifier",
        source_revision=base.source_revision,
        created_at=CREATED_AT,
        input_digests=(
            value.digest,
            base.digest,
            POLICY_SHA,
            canonical_sha({"verifier_id": report.verifier_id}),
            *(item.digest for item in forged_decisions),
        ),
        trace_id="proposal-fixture",
    )
    forged = ProposalVerificationReport(
        proposal_sha256=value.digest,
        base_snapshot_sha256=base.digest,
        source_revision=base.source_revision,
        verifier_id=report.verifier_id,
        verifier_policy_sha256=POLICY_SHA,
        decisions=tuple(forged_decisions),
        all_accepted=False,
        provenance=forged_provenance,
    )

    with pytest.raises(ValueError, match="does not match recomputed"):
        require_graph_proposal_verification(
            forged,
            value,
            base,
            verified_evidence_sha256s=tuple(
                item for op in value.operations for item in op.evidence_sha256s
            ),
            allowed_relations=("declares_type", "describes", "documents"),
            expected_verifier_id="deterministic-graph-policy-v1",
            expected_verifier_policy_sha256=POLICY_SHA,
        )


def test_model_text_cannot_substitute_for_verified_evidence() -> None:
    base = snapshot()
    op = GraphOperation(
        operation_id="op-01-rename",
        kind="rename_concept",
        source_plane="code",
        source_node_id="code:c",
        replacement="The model is certain this rename is correct.",
        evidence_sha256s=(EVIDENCE[7],),
    )
    value = proposal(base, ops=(op,))
    report = verify(value, base, evidence=())
    assert report.decisions[0].verdict == "rejected"
    assert report.decisions[0].reasons == ("unverified-evidence",)


def test_counter_review_verifier_has_no_snapshot_mutation_or_application_calls() -> None:
    source = Path("daedalus/twin/proposals.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    verifier = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "verify_graph_proposal"
    )
    forbidden_calls = {
        "replace",
        "setattr",
        "update",
        "append_binding",
        "remove_binding",
        "apply",
        "publish",
        "promote",
    }
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(verifier)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not forbidden_calls.intersection(calls)
    assert "FourfoldSnapshot" not in {
        node.func.id
        for node in ast.walk(verifier)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
