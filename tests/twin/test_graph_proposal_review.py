from __future__ import annotations

from copy import deepcopy

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import (
    FourfoldSnapshot,
    GraphOperation,
    GraphProposal,
    GraphWritableScope,
    PlaneSnapshot,
    parse_graph_proposal,
    parse_proposal_verification_report,
    require_graph_proposal_verification,
    verify_graph_proposal,
)

REVISION = "a" * 40
FOREST_SHA = "b" * 64
MODEL_SHA = "c" * 64
RUNTIME_SHA = "d" * 64
CONTEXT_SHA = "e" * 64
EVIDENCE_SHA = "f" * 64
POLICY_SHA = "1" * 64
CREATED_AT = "2026-08-03T12:30:00+00:00"
VERIFIER_ID = "deterministic-graph-policy-v1"


def _snapshot() -> FourfoldSnapshot:
    plane_nodes = {
        "code": ("code:event.voltage",),
        "type": ("type:float",),
        "data": ("data:event.voltage",),
        "knowledge": ("knowledge:event-voltage",),
    }
    planes = tuple(
        PlaneSnapshot(
            plane=plane,
            source_revision=REVISION,
            status="complete",
            node_ids=nodes,
            evidence_sha256s=(canonical_sha({"plane": plane}),),
        )
        for plane, nodes in plane_nodes.items()
    )
    provenance = ContractProvenance(
        origin="tests.graph-proposal-review-snapshot",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(FOREST_SHA, *(item.digest for item in planes)),
    )
    return FourfoldSnapshot(
        repository_id="proposal-review-fixture",
        source_revision=REVISION,
        source_forest_sha256=FOREST_SHA,
        planes=planes,
        bindings=(),
        provenance=provenance,
    )


def _proposal(snapshot: FourfoldSnapshot) -> GraphProposal:
    scope = GraphWritableScope(
        planes=("code",),
        node_ids=("code:event.voltage",),
        relations=(),
        allow_renames=True,
    )
    operation = GraphOperation(
        operation_id="op-01-rename",
        kind="rename_concept",
        source_plane="code",
        source_node_id="code:event.voltage",
        replacement="bias_voltage",
        evidence_sha256s=(EVIDENCE_SHA,),
    )
    provenance = ContractProvenance(
        origin="tests.graph-proposal-review",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            snapshot.digest,
            MODEL_SHA,
            RUNTIME_SHA,
            CONTEXT_SHA,
            scope.digest,
            operation.digest,
        ),
    )
    return GraphProposal(
        proposal_id="proposal-review-1",
        base_snapshot_sha256=snapshot.digest,
        source_revision=REVISION,
        objective="Rename the bounded code concept.",
        model_manifest_sha256=MODEL_SHA,
        runtime_manifest_sha256=RUNTIME_SHA,
        context_capsule_sha256=CONTEXT_SHA,
        budget_microusd=100,
        scope=scope,
        operations=(operation,),
        provenance=provenance,
    )


def _report(proposal: GraphProposal, snapshot: FourfoldSnapshot):
    return verify_graph_proposal(
        proposal,
        snapshot,
        verified_evidence_sha256s=(EVIDENCE_SHA,),
        allowed_relations=(),
        verifier_id=VERIFIER_ID,
        verifier_policy_sha256=POLICY_SHA,
        created_at=CREATED_AT,
    )


def test_consumer_owns_verifier_identity_and_policy() -> None:
    snapshot = _snapshot()
    proposal = _proposal(snapshot)
    report = _report(proposal, snapshot)

    with pytest.raises(ValueError, match="unexpected verifier"):
        require_graph_proposal_verification(
            report,
            proposal,
            snapshot,
            verified_evidence_sha256s=(EVIDENCE_SHA,),
            allowed_relations=(),
            expected_verifier_id="different-verifier-v1",
            expected_verifier_policy_sha256=POLICY_SHA,
        )

    with pytest.raises(ValueError, match="unexpected policy"):
        require_graph_proposal_verification(
            report,
            proposal,
            snapshot,
            verified_evidence_sha256s=(EVIDENCE_SHA,),
            allowed_relations=(),
            expected_verifier_id=VERIFIER_ID,
            expected_verifier_policy_sha256="2" * 64,
        )


def test_public_parsers_refuse_nested_array_normalization() -> None:
    snapshot = _snapshot()
    proposal = _proposal(snapshot)
    report = _report(proposal, snapshot)

    proposal_wire = deepcopy(proposal.to_dict())
    proposal_wire["provenance"]["input_digests"].reverse()
    with pytest.raises(ValueError, match="graph proposal wire is not canonical"):
        parse_graph_proposal(proposal_wire)

    report_wire = deepcopy(report.to_dict())
    report_wire["provenance"]["input_digests"].reverse()
    with pytest.raises(
        ValueError,
        match="proposal verification report wire is not canonical",
    ):
        parse_proposal_verification_report(report_wire)


def test_verifier_cannot_change_the_base_snapshot() -> None:
    snapshot = _snapshot()
    proposal = _proposal(snapshot)
    before = snapshot.to_dict()

    report = _report(proposal, snapshot)

    assert report.all_accepted is True
    assert snapshot.to_dict() == before
    assert snapshot.digest == proposal.base_snapshot_sha256
