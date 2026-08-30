# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import hashlib
import inspect
from dataclasses import replace
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
    snapshot_promotion_candidates,
)
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ResourceUsage,
)
from daedalus.spine.attempt import (
    AttemptResult,
    GateResult,
    PatchArtifact,
    STATE_CLEAN,
)

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
        gates=GateResult(passed=True, name="fixture-gate"),
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


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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


def test_candidate_digest_recomputes_exact_patch_bytes() -> None:
    candidate = _candidate("a" * 40)
    artifact = replace(candidate.result.artifact, diff_sha256="0" * 64)
    candidate.result = replace(candidate.result, artifact=artifact)

    with pytest.raises(PromotionAuthorizationError, match="patch digest"):
        candidate_batch_sha256([candidate])


def test_candidate_result_and_artifact_identity_must_match() -> None:
    candidate = _candidate("a" * 40)
    candidate.result = replace(candidate.result, base_revision="b" * 40)
    with pytest.raises(PromotionAuthorizationError, match="result base"):
        candidate_batch_sha256([candidate])

    candidate = _candidate("a" * 40)
    candidate.result = replace(candidate.result, task_id="other-task")
    with pytest.raises(PromotionAuthorizationError, match="task_id"):
        candidate_batch_sha256([candidate])

    candidate = _candidate("a" * 40)
    candidate.result = replace(candidate.result, branch="other-branch")
    with pytest.raises(PromotionAuthorizationError, match="branch"):
        candidate_batch_sha256([candidate])


def test_candidate_requires_real_passed_terminal_gate() -> None:
    candidate = _candidate("a" * 40)
    candidate.result = replace(candidate.result, gates=None)
    with pytest.raises(PromotionAuthorizationError, match="passed terminal gate"):
        candidate_batch_sha256([candidate])

    candidate = _candidate("a" * 40)
    candidate.result = replace(
        candidate.result,
        gates=GateResult(passed=True, cancelled=True),
    )
    with pytest.raises(PromotionAuthorizationError, match="passed terminal gate"):
        candidate_batch_sha256([candidate])


def test_candidate_paths_are_canonical_and_unique() -> None:
    candidate = _candidate("a" * 40)
    artifact = replace(candidate.result.artifact, changed_paths=("../outside",))
    candidate.result = replace(candidate.result, artifact=artifact)
    with pytest.raises(PromotionAuthorizationError, match="canonical"):
        candidate_batch_sha256([candidate])

    candidate = _candidate("a" * 40)
    artifact = replace(candidate.result.artifact, changed_paths=("x", "x"))
    candidate.result = replace(candidate.result, artifact=artifact)
    with pytest.raises(PromotionAuthorizationError, match="duplicates"):
        candidate_batch_sha256([candidate])


def test_candidate_snapshot_is_immune_to_later_result_swap() -> None:
    candidate = _candidate("a" * 40)
    snapshots = snapshot_promotion_candidates([candidate])
    approved_digest = candidate_batch_sha256(snapshots)

    candidate.result = _candidate("a" * 40, suffix="changed").result

    assert candidate_batch_sha256(snapshots) == approved_digest
    assert candidate_batch_sha256([candidate]) != approved_digest


@pytest.mark.xfail(strict=True, reason=(
    "FIXTURE SIGNING MISSING (measured 2026-08-24, unification merge): the "
    "owner HAS landed .agentenv/promotion_allowed_signers (897405d0), and "
    "these still fail -- their temp repos cannot mint a git-SIGNED tag for "
    "the trust root to verify, which needs a signing key in the test "
    "environment. The owed work is test infrastructure (a throwaway signing "
    "identity per fixture), not an owner act. strict=True stands: the day "
    "the fixtures can sign, these PASS and the marks come off."))
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
