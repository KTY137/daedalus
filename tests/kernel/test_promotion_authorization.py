from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalLedger,
    ApprovalReplay,
    issue_owner_approval,
)
from daedalus.kernel.promotion import (
    PromotionBindingMismatch,
    PromotionEvidenceError,
    authorize_fourfold_promotion,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    NominationReceipt,
    ResourceUsage,
)
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot, compile_reference_project


BASE_REVISION = "a" * 40
CANDIDATE_REVISION = "b" * 64
TARGET_REVISION = "c" * 40
POLICY_SHA256 = "d" * 64
ATTEMPT_SHA256 = "e" * 64
SECRET = b"fourfold-owner-secret-material-at-least-32-bytes"
NOW = datetime(2026, 8, 3, 3, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def locator(digest: str) -> str:
    return f"artifact-locator:sha256:{digest}"


def provenance(origin: str, source_revision: str, *inputs: str) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=source_revision,
        created_at=NOW.isoformat(),
        input_digests=tuple(sorted(set(inputs))),
        trace_id="mission-fourfold-promotion",
    )


def candidate_snapshot(*, revision: str = CANDIDATE_REVISION) -> FourfoldSnapshot:
    return compile_reference_project(
        FIXTURE,
        source_revision=revision,
        created_at=NOW.isoformat(),
        trace_id="mission-fourfold-promotion",
    ).snapshot


def incomplete_snapshot(snapshot: FourfoldSnapshot) -> FourfoldSnapshot:
    planes = list(snapshot.planes)
    code = planes[0]
    planes[0] = PlaneSnapshot(
        plane=code.plane,
        source_revision=code.source_revision,
        status="partial",
        node_ids=code.node_ids,
        relation_sha256s=code.relation_sha256s,
        evidence_sha256s=code.evidence_sha256s,
        reason="mutation: code extraction intentionally incomplete",
    )
    snapshot_provenance = provenance(
        "tests.partial-fourfold",
        snapshot.source_revision,
        snapshot.source_forest_sha256,
        *(plane.digest for plane in planes),
        *(binding.digest for binding in snapshot.bindings),
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=snapshot.source_forest_sha256,
        planes=tuple(planes),
        bindings=snapshot.bindings,
        provenance=snapshot_provenance,
    )


def evidence_packet(
    snapshot: FourfoldSnapshot,
    *,
    subject_sha256: str | None = None,
    output_sha256: str | None = None,
    candidate_sha256: str = CANDIDATE_REVISION,
) -> EvidencePacket:
    output = output_sha256 or snapshot.digest
    output_locator = locator(output)
    item = EvidenceItem(
        evidence_id="fourfold-candidate-snapshot",
        evaluator="fourfold-reference-compiler",
        assurance="deterministic",
        verdict="passed",
        output_sha256=output,
        evidence_locator=output_locator,
        collected_at=NOW.isoformat(),
        provenance=provenance(
            "tests.fourfold-evidence-item",
            BASE_REVISION,
            output,
        ),
        details={
            "candidate_source_revision": snapshot.source_revision,
            "repository_id": snapshot.repository_id,
        },
    )
    candidate_locator = locator(candidate_sha256)
    subject = subject_sha256 or snapshot.digest
    return EvidencePacket(
        packet_id="evidence-fourfold-promotion",
        mission_id="mission-fourfold-promotion",
        attempt_id="attempt-fourfold-promotion",
        source_revision=BASE_REVISION,
        attempt_contract_sha256=ATTEMPT_SHA256,
        subject_sha256=subject,
        evaluation_status="passed",
        items=(item,),
        policy_decision_sha256=POLICY_SHA256,
        usage=ResourceUsage(wall_time_ms=1),
        provenance=provenance(
            "tests.fourfold-evidence-packet",
            BASE_REVISION,
            ATTEMPT_SHA256,
            subject,
            POLICY_SHA256,
            output,
            candidate_sha256,
        ),
        candidate_artifact_sha256=candidate_sha256,
        candidate_artifact_locator=candidate_locator,
    )


def nomination(
    evidence: EvidencePacket,
    *,
    candidate_locator: str | None = None,
) -> NominationReceipt:
    assert evidence.candidate_artifact_sha256 is not None
    assert evidence.candidate_artifact_locator is not None
    selected_locator = candidate_locator or evidence.candidate_artifact_locator
    evidence_locator = evidence.items[0].evidence_locator
    return NominationReceipt(
        nomination_id="nomination-fourfold-promotion",
        mission_id=evidence.mission_id,
        attempt_id=evidence.attempt_id,
        source_revision=BASE_REVISION,
        candidate_artifact_sha256=evidence.candidate_artifact_sha256,
        candidate_artifact_locator=selected_locator,
        evidence_packet_sha256=evidence.digest,
        evidence_locator=evidence_locator,
        policy_decision_sha256=evidence.policy_decision_sha256,
        nomination_status="nominated",
        reasons=("candidate Twin and deterministic evidence retained",),
        provenance=provenance(
            "tests.fourfold-nomination",
            BASE_REVISION,
            evidence.candidate_artifact_sha256,
            selected_locator.rsplit(":", 1)[1],
            evidence.digest,
            evidence_locator.rsplit(":", 1)[1],
            evidence.policy_decision_sha256,
        ),
    )


def approval(nomination_value: NominationReceipt, evidence: EvidencePacket):
    return issue_owner_approval(
        approval_id="approval-fourfold-promotion",
        owner_id="KTY137",
        key_id="owner-key-1",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination_value.digest,
        candidate_artifact_sha256=nomination_value.candidate_artifact_sha256,
        evidence_packet_sha256=evidence.digest,
        base_revision=BASE_REVISION,
        target_ref="experimental",
        expected_target_revision=TARGET_REVISION,
        nonce="nonce-fourfold-promotion",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=provenance(
            "tests.fourfold-owner-approval",
            BASE_REVISION,
            nomination_value.digest,
            nomination_value.candidate_artifact_sha256,
            evidence.digest,
        ),
        secret=SECRET,
    )


def authorize(
    tmp_path: Path,
    snapshot: FourfoldSnapshot,
    evidence: EvidencePacket,
    nomination_value: NominationReceipt,
    approval_value,
):
    return authorize_fourfold_promotion(
        promotion_id="promotion-fourfold-1",
        nomination=nomination_value,
        evidence=evidence,
        candidate_snapshot=snapshot,
        repository_id=snapshot.repository_id,
        owner_approval=approval_value,
        owner_approval_locator=locator(approval_value.digest),
        owner_keyring={("KTY137", "owner-key-1"): SECRET},
        approval_ledger=ApprovalLedger(tmp_path / "approvals.sqlite3"),
        target_ref="experimental",
        current_target_revision=TARGET_REVISION,
        authorized_at=NOW + timedelta(seconds=1),
    )


def test_real_fourfold_snapshot_is_bound_through_evidence_and_consumed_approval(
    tmp_path: Path,
) -> None:
    snapshot = candidate_snapshot()
    evidence = evidence_packet(snapshot)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)

    authorization = authorize(
        tmp_path, snapshot, evidence, nomination_value, approval_value
    )

    assert authorization.receipt.promotion_status == "approved"
    assert authorization.receipt.target_revision == TARGET_REVISION
    assert authorization.candidate_snapshot_sha256 == snapshot.digest
    assert authorization.required_complete_planes == (
        "code",
        "data",
        "knowledge",
        "type",
    )
    assert snapshot.digest in authorization.receipt.provenance.input_digests
    assert authorization.consumed_approval.digest in (
        authorization.receipt.provenance.input_digests
    )
    assert authorization.receipt.owner_approval_ref == locator(approval_value.digest)


def test_approval_replay_is_refused_after_first_authorization(tmp_path: Path) -> None:
    snapshot = candidate_snapshot()
    evidence = evidence_packet(snapshot)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)

    authorize(tmp_path, snapshot, evidence, nomination_value, approval_value)
    with pytest.raises(ApprovalReplay):
        authorize(tmp_path, snapshot, evidence, nomination_value, approval_value)


def test_stale_target_refuses_before_consuming_owner_capability(tmp_path: Path) -> None:
    snapshot = candidate_snapshot()
    evidence = evidence_packet(snapshot)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")

    with pytest.raises(ApprovalBindingMismatch, match="expected_target_revision"):
        authorize_fourfold_promotion(
            promotion_id="promotion-fourfold-1",
            nomination=nomination_value,
            evidence=evidence,
            candidate_snapshot=snapshot,
            repository_id=snapshot.repository_id,
            owner_approval=approval_value,
            owner_approval_locator=locator(approval_value.digest),
            owner_keyring={("KTY137", "owner-key-1"): SECRET},
            approval_ledger=ledger,
            target_ref="experimental",
            current_target_revision="f" * 40,
            authorized_at=NOW + timedelta(seconds=1),
        )
    assert not ledger.consumed(approval_value.digest)


def test_candidate_snapshot_revision_and_repository_are_exact(tmp_path: Path) -> None:
    snapshot = candidate_snapshot(revision="f" * 64)
    evidence = evidence_packet(snapshot, candidate_sha256=CANDIDATE_REVISION)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)

    with pytest.raises(PromotionBindingMismatch, match="candidate artifact digest"):
        authorize(tmp_path, snapshot, evidence, nomination_value, approval_value)

    correct_snapshot = candidate_snapshot()
    correct_evidence = evidence_packet(correct_snapshot)
    correct_nomination = nomination(correct_evidence)
    correct_approval = approval(correct_nomination, correct_evidence)
    with pytest.raises(PromotionBindingMismatch, match="different repository"):
        authorize_fourfold_promotion(
            promotion_id="promotion-fourfold-2",
            nomination=correct_nomination,
            evidence=correct_evidence,
            candidate_snapshot=correct_snapshot,
            repository_id="another-repository",
            owner_approval=correct_approval,
            owner_approval_locator=locator(correct_approval.digest),
            owner_keyring={("KTY137", "owner-key-1"): SECRET},
            approval_ledger=ApprovalLedger(tmp_path / "repo.sqlite3"),
            target_ref="experimental",
            current_target_revision=TARGET_REVISION,
            authorized_at=NOW + timedelta(seconds=1),
        )


def test_snapshot_subject_and_deterministic_output_are_both_required(
    tmp_path: Path,
) -> None:
    snapshot = candidate_snapshot()
    wrong_subject = evidence_packet(snapshot, subject_sha256="f" * 64)
    wrong_nomination = nomination(wrong_subject)
    wrong_approval = approval(wrong_nomination, wrong_subject)
    with pytest.raises(PromotionBindingMismatch, match="evidence subject"):
        authorize(tmp_path, snapshot, wrong_subject, wrong_nomination, wrong_approval)

    wrong_output = evidence_packet(snapshot, output_sha256="f" * 64)
    output_nomination = nomination(wrong_output)
    output_approval = approval(output_nomination, wrong_output)
    with pytest.raises(PromotionEvidenceError, match="candidate Twin evidence"):
        authorize(
            tmp_path,
            snapshot,
            wrong_output,
            output_nomination,
            output_approval,
        )


def test_partial_required_plane_and_locator_repackaging_are_refused(
    tmp_path: Path,
) -> None:
    partial = incomplete_snapshot(candidate_snapshot())
    evidence = evidence_packet(partial)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)
    with pytest.raises(PromotionEvidenceError, match="code=partial"):
        authorize(tmp_path, partial, evidence, nomination_value, approval_value)

    complete = candidate_snapshot()
    complete_evidence = evidence_packet(complete)
    repackaged = nomination(
        complete_evidence,
        candidate_locator=locator("1" * 64),
    )
    repackaged_approval = approval(repackaged, complete_evidence)
    with pytest.raises(PromotionBindingMismatch, match="candidate locators"):
        authorize(
            tmp_path,
            complete,
            complete_evidence,
            repackaged,
            repackaged_approval,
        )


def test_owner_locator_must_address_exact_authenticated_payload(tmp_path: Path) -> None:
    snapshot = candidate_snapshot()
    evidence = evidence_packet(snapshot)
    nomination_value = nomination(evidence)
    approval_value = approval(nomination_value, evidence)
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")

    with pytest.raises(PromotionBindingMismatch, match="does not address"):
        authorize_fourfold_promotion(
            promotion_id="promotion-fourfold-1",
            nomination=nomination_value,
            evidence=evidence,
            candidate_snapshot=snapshot,
            repository_id=snapshot.repository_id,
            owner_approval=approval_value,
            owner_approval_locator=locator("f" * 64),
            owner_keyring={("KTY137", "owner-key-1"): SECRET},
            approval_ledger=ledger,
            target_ref="experimental",
            current_target_revision=TARGET_REVISION,
            authorized_at=NOW + timedelta(seconds=1),
        )
    assert not ledger.consumed(approval_value.digest)
