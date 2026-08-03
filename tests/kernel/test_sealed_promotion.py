from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kairos.gated_writes import GatedCandidate, promote_candidates
from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalLedger,
    ConsumedOwnerApproval,
    issue_owner_approval,
)
from daedalus.kernel.promotion import (
    PromotionAuthorizationError,
    authorize_promotion,
    candidate_batch_sha256,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ResourceUsage,
)
from daedalus.spine.attempt import AttemptResult, PatchArtifact, STATE_CLEAN
from daedalus.spine.envelope import canonical_sha

NOW = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _candidate(base: str, *, suffix: str = "one") -> GatedCandidate:
    diff = f"diff --git a/x b/x\n+{suffix}\n".encode()
    artifact = PatchArtifact(
        task_id=f"task-{suffix}",
        branch=f"candidate-{suffix}",
        base_revision=base,
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
        base_revision=base,
        artifact=artifact,
    )
    return GatedCandidate(assignment=None, spec=None, result=result)


def _packet(candidate_sha: str, revision: str) -> EvidencePacket:
    output = _sha("gate-output")
    item = EvidenceItem(
        evidence_id="promotion-gate",
        evaluator="promotion-fixture",
        assurance="deterministic",
        verdict="passed",
        output_sha256=output,
        evidence_locator=f"artifact-locator:sha256:{output}",
        collected_at=NOW.isoformat(),
        provenance=ContractProvenance(
            origin="tests.sealed-promotion.item",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(output,),
        ),
        details={"passed": True},
    )
    attempt = _sha("attempt")
    policy = _sha("policy")
    return EvidencePacket(
        packet_id="promotion-evidence",
        mission_id="promotion-mission",
        attempt_id="promotion-attempt",
        source_revision=revision,
        attempt_contract_sha256=attempt,
        subject_sha256=candidate_sha,
        evaluation_status="passed",
        items=(item,),
        policy_decision_sha256=policy,
        usage=ResourceUsage(wall_time_ms=1),
        provenance=ContractProvenance(
            origin="tests.sealed-promotion.packet",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=tuple(sorted({attempt, policy, candidate_sha, output})),
        ),
        candidate_artifact_sha256=candidate_sha,
        candidate_artifact_locator=f"artifact-locator:sha256:{candidate_sha}",
    )


def _consumed(candidate_sha: str, packet: EvidencePacket, revision: str, target: str, tmp_path: Path):
    nomination = _sha("nomination")
    approval = issue_owner_approval(
        approval_id="approval-promotion",
        owner_id="KTY137",
        key_id="owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet.digest,
        base_revision=revision,
        target_ref="experimental",
        expected_target_revision=target,
        nonce="promotion-nonce",
        issued_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.sealed-promotion.approval",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(nomination, candidate_sha, packet.digest),
        ),
        secret=SECRET,
    )
    expectation = ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet.digest,
        base_revision=revision,
        target_ref="experimental",
        current_target_revision=target,
    )
    ledger = ApprovalLedger(tmp_path / "approval.sqlite3")
    consumed = ledger.consume(
        approval,
        keyring={("KTY137", "owner-key"): SECRET},
        expectation=expectation,
        promotion_id="promotion-001",
        verified_at=NOW + timedelta(seconds=1),
        consumed_at=NOW + timedelta(seconds=2),
    )
    return ledger, consumed


def test_authorization_binds_consumed_approval_packet_batch_and_live_head(tmp_path: Path) -> None:
    revision = "a" * 40
    target = "b" * 40
    candidates = [_candidate(revision)]
    candidate_sha = candidate_batch_sha256(candidates)
    packet = _packet(candidate_sha, revision)
    ledger, consumed = _consumed(candidate_sha, packet, revision, target, tmp_path)

    auth = authorize_promotion(
        consumed_approval=consumed,
        evidence_packet=packet,
        candidates=candidates,
        target_ref="experimental",
        live_target_revision=target,
    )
    assert auth.candidate_artifact_sha256 == candidate_sha
    assert auth.evidence_packet_sha256 == packet.digest
    assert len(auth.authorization_sha256) == 64


@pytest.mark.parametrize("mutation", ["candidate", "evidence", "head", "revision"])
def test_authorization_refuses_every_stale_binding(tmp_path: Path, mutation: str) -> None:
    revision = "a" * 40
    target = "b" * 40
    candidates = [_candidate(revision)]
    candidate_sha = candidate_batch_sha256(candidates)
    packet = _packet(candidate_sha, revision)
    ledger, consumed = _consumed(candidate_sha, packet, revision, target, tmp_path)

    if mutation == "candidate":
        candidates = [_candidate(revision, suffix="changed")]
    elif mutation == "evidence":
        packet = _packet(candidate_sha, revision)
        packet = EvidencePacket.from_dict({**packet.to_dict(), "packet_id": "different-packet"})
    elif mutation == "head":
        target = "c" * 40
    else:
        candidates = [_candidate("d" * 40)]

    with pytest.raises(PromotionAuthorizationError):
        authorize_promotion(
            consumed_approval=consumed,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target,
        )


def test_public_promotion_rechecks_head_before_worktree_or_lock(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "x").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "x"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "branch", "experimental"], cwd=repo, check=True)

    candidates = [_candidate(revision)]
    candidate_sha = candidate_batch_sha256(candidates)
    packet = _packet(candidate_sha, revision)
    ledger, consumed = _consumed(
        candidate_sha, packet, revision, "f" * 40, tmp_path
    )

    class ForbiddenManager:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("worktree manager constructed before authorization")

    monkeypatch.setattr("daedalus.kairos.gated_writes.GitWorktreeManager", ForbiddenManager)
    report = promote_candidates(
        str(repo),
        candidates,
        project=None,
        availability={},
        consumed_approval=consumed,
        evidence_packet=packet,
        target_ref="experimental",
    )
    assert report["integration_branch"] is None
    assert report["authorization"] is None
    assert "target_head" in report["refused"][0]["reason"]


def test_fabricated_consumption_capability_cannot_enter_promotion(
    tmp_path: Path,
) -> None:
    revision = "a" * 40
    target = "b" * 40
    candidates = [_candidate(revision)]
    candidate_sha = candidate_batch_sha256(candidates)
    packet = _packet(candidate_sha, revision)
    _ledger, consumed = _consumed(
        candidate_sha, packet, revision, target, tmp_path
    )

    consumed_at = (NOW + timedelta(seconds=3)).isoformat(timespec="microseconds")
    record = {
        **consumed.verified.to_dict(),
        "promotion_id": "promotion-fabricated",
        "consumed_at": consumed_at,
    }
    empty_ledger = ApprovalLedger(tmp_path / "empty-approval.sqlite3")
    fabricated = ConsumedOwnerApproval(
        verified=consumed.verified,
        promotion_id="promotion-fabricated",
        consumed_at=consumed_at,
        consumption_sha256=canonical_sha(record),
        ledger_path=str(empty_ledger.path.resolve()),
    )

    with pytest.raises(PromotionAuthorizationError, match="not authentic"):
        authorize_promotion(
            consumed_approval=fabricated,
            evidence_packet=packet,
            candidates=candidates,
            target_ref="experimental",
            live_target_revision=target,
        )
