from __future__ import annotations

import ast
import hashlib
import inspect
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kairos.gated_writes import GatedCandidate
from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalLedger,
    ApprovalSignatureError,
    ApprovalStateError,
    issue_owner_approval,
)
from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    authorize_persisted_promotion,
    candidate_batch_sha256,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ResourceUsage,
)
from daedalus.spine.attempt import AttemptResult, PatchArtifact, STATE_CLEAN

NOW = datetime(2026, 8, 3, 18, 0, tzinfo=timezone.utc)
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"
KEYRING = {("KTY137", "owner-key"): SECRET}


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _candidate(base_revision: str, *, suffix: str = "one") -> GatedCandidate:
    diff = f"diff --git a/x b/x\n+{suffix}\n".encode("utf-8")
    artifact = PatchArtifact(
        task_id=f"task-{suffix}",
        branch=f"candidate-{suffix}",
        base_revision=base_revision,
        diff_bytes=diff,
        diff_sha256=hashlib.sha256(diff).hexdigest(),
        changed_paths=("x",),
        created_ts=NOW.isoformat(),
    )
    result = AttemptResult(
        state=STATE_CLEAN,
        task_id=artifact.task_id,
        started_ts=NOW.isoformat(),
        finished_ts=NOW.isoformat(),
        duration_s=0.1,
        effect_key=f"effect-{suffix}",
        branch=artifact.branch,
        base_revision=base_revision,
        artifact=artifact,
    )
    return GatedCandidate(assignment=None, spec=None, result=result)


def _packet(candidate_sha256: str, revision: str) -> EvidencePacket:
    output = _sha("promotion-gate-output")
    attempt = _sha("promotion-attempt")
    policy = _sha("promotion-policy")
    item = EvidenceItem(
        evidence_id="persisted-promotion-gate",
        evaluator="persisted-promotion-fixture",
        assurance="deterministic",
        verdict="passed",
        output_sha256=output,
        evidence_locator=f"artifact-locator:sha256:{output}",
        collected_at=NOW.isoformat(),
        provenance=ContractProvenance(
            origin="tests.persisted-promotion.item",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(output,),
        ),
        details={"passed": True},
    )
    return EvidencePacket(
        packet_id="persisted-promotion-evidence",
        mission_id="persisted-promotion-mission",
        attempt_id="persisted-promotion-attempt",
        source_revision=revision,
        attempt_contract_sha256=attempt,
        subject_sha256=candidate_sha256,
        evaluation_status="passed",
        items=(item,),
        policy_decision_sha256=policy,
        usage=ResourceUsage(wall_time_ms=1),
        provenance=ContractProvenance(
            origin="tests.persisted-promotion.packet",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=tuple(
                sorted({attempt, policy, candidate_sha256, output})
            ),
        ),
        candidate_artifact_sha256=candidate_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{candidate_sha256}"
        ),
    )


def _consume(
    tmp_path: Path,
    *,
    candidate_sha256: str,
    packet: EvidencePacket,
    revision: str,
    target_revision: str,
):
    nomination = _sha("persisted-promotion-nomination")
    approval = issue_owner_approval(
        approval_id="persisted-promotion-approval",
        owner_id="KTY137",
        key_id="owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha256,
        evidence_packet_sha256=packet.digest,
        base_revision=revision,
        target_ref="experimental",
        expected_target_revision=target_revision,
        nonce="persisted-promotion-nonce",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.persisted-promotion.approval",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(nomination, candidate_sha256, packet.digest),
        ),
        secret=SECRET,
    )
    expectation = ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha256,
        evidence_packet_sha256=packet.digest,
        base_revision=revision,
        target_ref="experimental",
        current_target_revision=target_revision,
    )
    ledger = ApprovalLedger(
        tmp_path / "approval.sqlite3",
        clock=lambda: NOW + timedelta(seconds=2),
    )
    consumed = ledger.consume(
        approval,
        keyring=KEYRING,
        expectation=expectation,
        promotion_id="persisted-promotion-001",
    )
    return ledger, consumed


def _fixture(tmp_path: Path):
    revision = "a" * 40
    target_revision = "b" * 40
    candidates = [_candidate(revision)]
    candidate_sha256 = candidate_batch_sha256(candidates)
    packet = _packet(candidate_sha256, revision)
    ledger, consumed = _consume(
        tmp_path,
        candidate_sha256=candidate_sha256,
        packet=packet,
        revision=revision,
        target_revision=target_revision,
    )
    return revision, target_revision, candidates, packet, ledger, consumed


def test_persisted_authorization_accepts_exact_authenticated_consumption(
    tmp_path: Path,
) -> None:
    (
        revision,
        target_revision,
        candidates,
        packet,
        ledger,
        consumed,
    ) = _fixture(tmp_path)

    authorization = authorize_persisted_promotion(
        approval_ledger=ledger,
        owner_keyring=KEYRING,
        consumed_approval=consumed,
        evidence_packet=packet,
        candidates=candidates,
        target_ref="experimental",
        live_target_revision=target_revision,
    )

    assert authorization.promotion_id == consumed.promotion_id
    assert authorization.source_revision == revision
    assert (
        authorization.approval_consumption_sha256
        == consumed.consumption_sha256
    )
    assert authorization.evidence_packet_sha256 == packet.digest


def test_self_consistent_consumption_from_foreign_ledger_is_not_authority(
    tmp_path: Path,
) -> None:
    (
        _revision,
        target_revision,
        candidates,
        packet,
        _ledger,
        consumed,
    ) = _fixture(tmp_path / "source")
    empty_ledger = ApprovalLedger(
        tmp_path / "foreign" / "approval.sqlite3",
        clock=lambda: NOW + timedelta(seconds=3),
    )

    with pytest.raises(
        PromotionAuthorizationError,
        match="not authenticated persisted authority",
    ) as captured:
        authorize_persisted_promotion(
            approval_ledger=empty_ledger,
            owner_keyring=KEYRING,
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target_revision,
        )

    assert isinstance(captured.value.__cause__, ApprovalStateError)


def test_persisted_authorization_reauthenticates_owner_key(
    tmp_path: Path,
) -> None:
    (
        _revision,
        target_revision,
        candidates,
        packet,
        ledger,
        consumed,
    ) = _fixture(tmp_path)

    with pytest.raises(
        PromotionAuthorizationError,
        match="not authenticated persisted authority",
    ) as captured:
        authorize_persisted_promotion(
            approval_ledger=ledger,
            owner_keyring={
                ("KTY137", "owner-key"): b"foreign-secret-material-at-least-32-bytes"
            },
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target_revision,
        )

    assert isinstance(captured.value.__cause__, ApprovalSignatureError)


def test_persisted_authority_does_not_weaken_candidate_binding(
    tmp_path: Path,
) -> None:
    (
        revision,
        target_revision,
        _candidates,
        packet,
        ledger,
        consumed,
    ) = _fixture(tmp_path)
    changed_candidates = [_candidate(revision, suffix="changed")]

    with pytest.raises(PromotionAuthorizationError, match="candidate"):
        authorize_persisted_promotion(
            approval_ledger=ledger,
            owner_keyring=KEYRING,
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=changed_candidates,
            target_ref="experimental",
            live_target_revision=target_revision,
        )


def test_persisted_authorization_requires_explicit_authorities(
    tmp_path: Path,
) -> None:
    (
        _revision,
        target_revision,
        candidates,
        packet,
        ledger,
        consumed,
    ) = _fixture(tmp_path)

    with pytest.raises(PromotionAuthorizationError, match="ApprovalLedger"):
        authorize_persisted_promotion(
            approval_ledger=object(),  # type: ignore[arg-type]
            owner_keyring=KEYRING,
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target_revision,
        )
    with pytest.raises(PromotionAuthorizationError, match="non-empty owner keyring"):
        authorize_persisted_promotion(
            approval_ledger=ledger,
            owner_keyring={},
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target_revision,
        )


def test_source_review_pins_persistence_before_pure_authorization() -> None:
    source = inspect.getsource(authorize_persisted_promotion)
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    verify_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute)
        and node.func.attr == "verify_consumption"
    ]
    authorize_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Name)
        and node.func.id == "authorize_promotion"
    ]

    assert len(verify_calls) == 1
    assert len(authorize_calls) == 1
    assert verify_calls[0].lineno < authorize_calls[0].lineno
    assert "subprocess" not in source
    assert "resolve_live_target_revision" not in source
    assert "GitWorktreeManager" not in source
