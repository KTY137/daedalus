from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.approvals import ApprovalLedger, ApprovalReplay, issue_owner_approval
from daedalus.kernel.promotion import (
    PromotionBindingMismatch,
    PromotionCapabilityError,
    PromotionTargetMoved,
    assert_authorized_promotion_start,
    build_approved_promotion_receipt,
    consume_prepared_promotion,
    prepare_promotion,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    NominationReceipt,
    ResourceUsage,
)
from daedalus.twin import compile_reference_project

BASE_REVISION = "a" * 40
CANDIDATE_SHA = "b" * 64
OTHER_CANDIDATE_SHA = "c" * 64
TARGET_REVISION = "d" * 40
MOVED_TARGET_REVISION = "e" * 40
POLICY_SHA = "1" * 64
ATTEMPT_SHA = "2" * 64
SECRET = b"fourfold-promotion-owner-secret-material-32-bytes"
NOW = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


@pytest.fixture(scope="module")
def candidate_snapshot():
    result = compile_reference_project(
        FIXTURE,
        source_revision=CANDIDATE_SHA,
        created_at=NOW.isoformat(),
        trace_id="g0-fourfold-promotion",
    )
    assert all(plane.status == "complete" for plane in result.snapshot.planes)
    return result.snapshot


def _provenance(origin: str, *inputs: str) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=BASE_REVISION,
        created_at=NOW.isoformat(),
        input_digests=tuple(dict.fromkeys(inputs)),
        trace_id="promotion-1",
    )


def _evidence(candidate_snapshot, *, subject: str = CANDIDATE_SHA, details=None):
    snapshot_digest = candidate_snapshot.digest
    item = EvidenceItem(
        evidence_id="candidate-fourfold",
        evaluator="fourfold.snapshot",
        assurance="deterministic",
        verdict="passed",
        output_sha256=snapshot_digest,
        evidence_locator=f"artifact-locator:sha256:{snapshot_digest}",
        collected_at=(NOW + timedelta(seconds=1)).isoformat(),
        provenance=_provenance("tests.fourfold-item", snapshot_digest),
        details=details or {
            "candidate_artifact_sha256": CANDIDATE_SHA,
            "snapshot_source_revision": candidate_snapshot.source_revision,
            "repository_id": candidate_snapshot.repository_id,
            "snapshot_contract_type": candidate_snapshot.CONTRACT_TYPE,
        },
    )
    return EvidencePacket(
        packet_id="evidence-1",
        mission_id="mission-1",
        attempt_id="attempt-1",
        source_revision=BASE_REVISION,
        attempt_contract_sha256=ATTEMPT_SHA,
        subject_sha256=subject,
        evaluation_status="passed",
        items=(item,),
        policy_decision_sha256=POLICY_SHA,
        usage=ResourceUsage(),
        provenance=_provenance(
            "tests.fourfold-packet",
            ATTEMPT_SHA,
            subject,
            POLICY_SHA,
            snapshot_digest,
            CANDIDATE_SHA,
        ),
        candidate_artifact_sha256=CANDIDATE_SHA,
        candidate_artifact_locator=f"artifact-locator:sha256:{CANDIDATE_SHA}",
    )


def _nomination(evidence: EvidencePacket) -> NominationReceipt:
    return NominationReceipt(
        nomination_id="nomination-1",
        mission_id=evidence.mission_id,
        attempt_id=evidence.attempt_id,
        source_revision=BASE_REVISION,
        candidate_artifact_sha256=CANDIDATE_SHA,
        candidate_artifact_locator=f"artifact-locator:sha256:{CANDIDATE_SHA}",
        evidence_packet_sha256=evidence.digest,
        evidence_locator=f"artifact-locator:sha256:{evidence.digest}",
        policy_decision_sha256=POLICY_SHA,
        nomination_status="nominated",
        reasons=("all deterministic gates passed",),
        provenance=_provenance(
            "tests.nomination",
            CANDIDATE_SHA,
            evidence.digest,
            POLICY_SHA,
        ),
    )


def _approval(evidence: EvidencePacket, nomination: NominationReceipt):
    return issue_owner_approval(
        approval_id="approval-1",
        owner_id="KTY137",
        key_id="owner-key-1",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination.digest,
        candidate_artifact_sha256=CANDIDATE_SHA,
        evidence_packet_sha256=evidence.digest,
        base_revision=BASE_REVISION,
        target_ref="experimental",
        expected_target_revision=TARGET_REVISION,
        nonce="nonce-1",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=_provenance(
            "tests.owner-approval",
            nomination.digest,
            CANDIDATE_SHA,
            evidence.digest,
        ),
        secret=SECRET,
    )


def _prepared(candidate_snapshot):
    evidence = _evidence(candidate_snapshot)
    nomination = _nomination(evidence)
    approval = _approval(evidence, nomination)
    prepared = prepare_promotion(
        promotion_id="promotion-1",
        approval=approval,
        nomination=nomination,
        evidence=evidence,
        candidate_snapshot=candidate_snapshot,
        target_ref="experimental",
        current_target_revision=TARGET_REVISION,
        keyring={("KTY137", "owner-key-1"): SECRET},
        now=NOW + timedelta(seconds=2),
    )
    return prepared, evidence, nomination


def test_real_wiki_fourfold_snapshot_is_bound_before_consumption(
    candidate_snapshot, tmp_path
) -> None:
    prepared, evidence, nomination = _prepared(candidate_snapshot)
    assert prepared.candidate_snapshot_sha256 == candidate_snapshot.digest
    assert prepared.candidate_snapshot_revision == CANDIDATE_SHA
    assert prepared.evidence_packet_sha256 == evidence.digest
    assert prepared.nomination_receipt_sha256 == nomination.digest

    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    authorization = consume_prepared_promotion(
        prepared,
        ledger=ledger,
        current_target_revision=TARGET_REVISION,
        consumed_at=NOW + timedelta(seconds=3),
    )
    assert_authorized_promotion_start(
        authorization,
        ledger=ledger,
        current_target_revision=TARGET_REVISION,
    )
    assert authorization.consumed_approval.promotion_id == "promotion-1"


def test_stale_target_refuses_before_approval_consumption(
    candidate_snapshot, tmp_path
) -> None:
    prepared, _, _ = _prepared(candidate_snapshot)
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    with pytest.raises(PromotionTargetMoved, match="moved"):
        consume_prepared_promotion(
            prepared,
            ledger=ledger,
            current_target_revision=MOVED_TARGET_REVISION,
            consumed_at=NOW + timedelta(seconds=3),
        )
    assert not ledger.consumed(prepared.owner_approval_sha256)


def test_candidate_snapshot_revision_must_equal_candidate_tree_digest() -> None:
    other = compile_reference_project(
        FIXTURE,
        source_revision=OTHER_CANDIDATE_SHA,
        created_at=NOW.isoformat(),
        trace_id="wrong-candidate",
    ).snapshot
    evidence = _evidence(other)
    nomination = _nomination(evidence)
    approval = _approval(evidence, nomination)
    with pytest.raises(PromotionBindingMismatch, match="source_revision"):
        prepare_promotion(
            promotion_id="promotion-1",
            approval=approval,
            nomination=nomination,
            evidence=evidence,
            candidate_snapshot=other,
            target_ref="experimental",
            current_target_revision=TARGET_REVISION,
            keyring={("KTY137", "owner-key-1"): SECRET},
            now=NOW + timedelta(seconds=2),
        )


def test_fourfold_evidence_detail_tampering_is_refused(candidate_snapshot) -> None:
    details = {
        "candidate_artifact_sha256": OTHER_CANDIDATE_SHA,
        "snapshot_source_revision": candidate_snapshot.source_revision,
        "repository_id": candidate_snapshot.repository_id,
        "snapshot_contract_type": candidate_snapshot.CONTRACT_TYPE,
    }
    evidence = _evidence(candidate_snapshot, details=details)
    nomination = _nomination(evidence)
    approval = _approval(evidence, nomination)
    with pytest.raises(PromotionBindingMismatch, match="detail mismatch"):
        prepare_promotion(
            promotion_id="promotion-1",
            approval=approval,
            nomination=nomination,
            evidence=evidence,
            candidate_snapshot=candidate_snapshot,
            target_ref="experimental",
            current_target_revision=TARGET_REVISION,
            keyring={("KTY137", "owner-key-1"): SECRET},
            now=NOW + timedelta(seconds=2),
        )


def test_evidence_subject_must_be_exact_candidate(candidate_snapshot) -> None:
    evidence = _evidence(candidate_snapshot, subject=OTHER_CANDIDATE_SHA)
    nomination = _nomination(evidence)
    approval = _approval(evidence, nomination)
    with pytest.raises(PromotionBindingMismatch, match="subject"):
        prepare_promotion(
            promotion_id="promotion-1",
            approval=approval,
            nomination=nomination,
            evidence=evidence,
            candidate_snapshot=candidate_snapshot,
            target_ref="experimental",
            current_target_revision=TARGET_REVISION,
            keyring={("KTY137", "owner-key-1"): SECRET},
            now=NOW + timedelta(seconds=2),
        )


def test_prepared_capability_refuses_contradictory_owner_digest(
    candidate_snapshot,
) -> None:
    prepared, _, _ = _prepared(candidate_snapshot)
    with pytest.raises(PromotionCapabilityError, match="owner digest"):
        dataclasses.replace(prepared, owner_approval_sha256="9" * 64)


def test_consumed_approval_cannot_be_replayed(candidate_snapshot, tmp_path) -> None:
    prepared, _, _ = _prepared(candidate_snapshot)
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    consume_prepared_promotion(
        prepared,
        ledger=ledger,
        current_target_revision=TARGET_REVISION,
        consumed_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(ApprovalReplay):
        consume_prepared_promotion(
            prepared,
            ledger=ledger,
            current_target_revision=TARGET_REVISION,
            consumed_at=NOW + timedelta(seconds=4),
        )


def test_target_and_ledger_are_rechecked_after_consumption(
    candidate_snapshot, tmp_path
) -> None:
    prepared, _, _ = _prepared(candidate_snapshot)
    ledger = ApprovalLedger(tmp_path / "approvals.sqlite3")
    authorization = consume_prepared_promotion(
        prepared,
        ledger=ledger,
        current_target_revision=TARGET_REVISION,
        consumed_at=NOW + timedelta(seconds=3),
    )
    with pytest.raises(PromotionTargetMoved, match="new owner approval"):
        assert_authorized_promotion_start(
            authorization,
            ledger=ledger,
            current_target_revision=MOVED_TARGET_REVISION,
        )
    with pytest.raises(PromotionCapabilityError, match="not present"):
        assert_authorized_promotion_start(
            authorization,
            ledger=ApprovalLedger(tmp_path / "other.sqlite3"),
            current_target_revision=TARGET_REVISION,
        )


def test_promotion_receipt_references_consumed_authorization(
    candidate_snapshot, tmp_path
) -> None:
    prepared, evidence, nomination = _prepared(candidate_snapshot)
    authorization = consume_prepared_promotion(
        prepared,
        ledger=ApprovalLedger(tmp_path / "approvals.sqlite3"),
        current_target_revision=TARGET_REVISION,
        consumed_at=NOW + timedelta(seconds=3),
    )
    provenance = _provenance(
        "tests.promotion-receipt",
        nomination.digest,
        CANDIDATE_SHA,
        evidence.digest,
        authorization.digest,
        candidate_snapshot.digest,
    )
    receipt = build_approved_promotion_receipt(
        authorization,
        target_revision="f" * 40,
        owner_approval_ref=f"artifact-locator:sha256:{authorization.digest}",
        reasons=("integration branch passed cumulative gates",),
        provenance=provenance,
    )
    assert receipt.promotion_status == "approved"
    assert receipt.owner_approval_ref.endswith(authorization.digest)

    with pytest.raises(PromotionCapabilityError, match="exact consumed"):
        build_approved_promotion_receipt(
            authorization,
            target_revision="f" * 40,
            owner_approval_ref=f"artifact-locator:sha256:{'9' * 64}",
            reasons=("integration branch passed cumulative gates",),
            provenance=provenance,
        )
