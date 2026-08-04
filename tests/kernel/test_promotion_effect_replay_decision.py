from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger, issue_effect_lease
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayMismatch,
    inspect_promotion_effect_replay,
)
from daedalus.kernel.promotion_effects import (
    PROMOTION_EFFECTS,
    PROMOTION_ENTRYPOINT_ID,
    PROMOTION_GUARD_CONTRACTS,
    PROMOTION_TARGET,
    PromotionEffectCapability,
)
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
TARGET = "b" * 40
CANDIDATE = "c" * 64
EVIDENCE = "d" * 64
APPROVAL = "e" * 64
POLICY = "f" * 64
PRIMARY = "1" * 64
INTEGRATION = "2" * 40
SECRET = b"promotion-effect-replay-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)


def build_fixture(tmp_path, *, promotion_clock=None):
    promotion_body = {
        "promotion_id": "promotion-1",
        "candidate_artifact_sha256": CANDIDATE,
        "evidence_packet_sha256": EVIDENCE,
        "source_revision": REVISION,
        "target_ref": "experimental",
        "live_target_revision": TARGET,
        "approval_consumption_sha256": APPROVAL,
    }
    promotion = PromotionAuthorization(
        **promotion_body,
        authorization_sha256=canonical_sha(promotion_body),
    )
    row = EntrypointSpec(
        id=PROMOTION_ENTRYPOINT_ID,
        surface=Surface.PYTHON,
        target=PROMOTION_TARGET,
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.REPOSITORY_MUTATION,
        ),
        guard_contracts=PROMOTION_GUARD_CONTRACTS,
        wiring=Wiring.CENTRAL,
    )
    registry = {PROMOTION_ENTRYPOINT_ID: row}
    scope = EffectScope(
        read_only=False,
        writable_paths=("integration-worktrees", "state"),
        tools=("git",),
        timeout_s=300,
        max_concurrency=1,
        kill_switch_ref="promotion-kill",
    )
    request = EffectLeaseRequest(
        request_id="promotion-replay-request-1",
        mission_id="mission-1",
        attempt_id=promotion.promotion_id,
        entrypoint_id=PROMOTION_ENTRYPOINT_ID,
        requested_effects=PROMOTION_EFFECTS,
        effect_scope=scope,
        idempotency_namespace="promotion-effects",
        kill_switch_generation=7,
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.promotion-effect-replay",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(
                promotion.authorization_sha256,
                promotion.candidate_artifact_sha256,
                promotion.evidence_packet_sha256,
                promotion.approval_consumption_sha256,
            ),
            trace_id=promotion.promotion_id,
        ),
    )
    policy = PolicyDecision(
        decision_id="promotion-replay-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY,
        verdict="allow",
        reasons=("bounded owner-approved promotion",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.promotion-effect-replay-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY),
            trace_id=promotion.promotion_id,
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="promotion-replay-lease-1",
        issuer_key_id="promotion-replay-key-1",
        issued_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        secret=SECRET,
        registry=registry,
    )
    authorization = NonRuntimeEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        effect_ledger=EffectLeaseLedger(tmp_path / "effects.sqlite3"),
        lease_keyring={"promotion-replay-key-1": SECRET},
        guard_decisions=(
            GuardDecision(
                "containment.worktree",
                True,
                "artifact:sha256:" + "3" * 64,
            ),
            GuardDecision(
                "promotion.owner_approval",
                True,
                "artifact:sha256:" + promotion.approval_consumption_sha256,
            ),
            GuardDecision(
                "spine.intent_ledger",
                True,
                "artifact:sha256:" + "4" * 64,
            ),
        ),
        kill_switch_generation_reader=lambda: 7,
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id=promotion.promotion_id,
        idempotency_key=promotion.authorization_sha256,
        requested_effects=PROMOTION_EFFECTS,
        writable_paths=("integration-worktrees/promotion-1", "state/spine.sqlite3"),
        tools=("git",),
        kill_switch_ref="promotion-kill",
        kill_switch_generation=7,
    )
    capability = PromotionEffectCapability(
        promotion=promotion,
        authorization=authorization,
        execution=execution,
    )
    ledger = PromotionExecutionLedger(
        tmp_path / "spine.sqlite3",
        clock=promotion_clock,
    )
    return capability, ledger


def promotion_report(capability):
    return {
        "promoted": [{"task_id": "task-1", "promoted": True}],
        "refused": [],
        "not_gated": [],
        "integration_branch": "integration/promotion-1",
        "integration_revision": INTEGRATION,
        "authorization": capability.promotion.to_dict(),
        "cleanup_error": None,
    }


def start_effect(capability):
    capability.grant()
    started = capability.begin()
    assert started.execute is True
    return started.receipt


def start_promotion(capability, ledger):
    started = ledger.begin(
        capability.promotion,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert started.execute is True
    return started.start


def complete_promotion(capability, ledger, start):
    return ledger.complete(
        start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=promotion_report(capability),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )


def test_both_absent_is_the_only_fresh_decision(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    capability.grant()
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "fresh"
        assert decision.permits_fresh_execution is True
        assert decision.requires_reconciliation is False
        assert decision.effect is None
        assert decision.promotion is None
    finally:
        ledger.close()


def test_promotion_start_without_top_level_effect_start_is_refused(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    capability.grant()
    start_promotion(capability, ledger)
    try:
        with pytest.raises(
            PromotionEffectReplayMismatch,
            match="without top-level Effect-Lease start",
        ):
            inspect_promotion_effect_replay(capability, ledger)
    finally:
        ledger.close()


def test_effect_start_without_promotion_start_remains_pending(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "pending_reconciliation"
        assert decision.permits_fresh_execution is False
        assert decision.requires_reconciliation is True
        assert decision.promotion is None
    finally:
        ledger.close()


def test_both_pending_remain_reconciliation_only(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    start_promotion(capability, ledger)
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "pending_reconciliation"
        assert decision.effect is not None
        assert decision.promotion is not None
        assert decision.promotion.pending_reconciliation is True
    finally:
        ledger.close()


def test_terminal_promotion_under_started_effect_requires_terminal_reconciliation(
    tmp_path,
) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    promotion_start = start_promotion(capability, ledger)
    completion = complete_promotion(capability, ledger, promotion_start)
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "reconcile_effect_terminal"
        assert decision.expected_output_digests == (
            completion.receipt.report_sha256,
        )
        assert decision.expected_detail_sha256 == completion.receipt.digest
        assert decision.requires_reconciliation is True
    finally:
        ledger.close()


def test_exact_cross_ledger_terminal_replays_promotion_report(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    effect_start = start_effect(capability)
    promotion_start = start_promotion(capability, ledger)
    completion = complete_promotion(capability, ledger, promotion_start)
    capability.finish(
        effect_start,
        outcome="completed",
        output_digests=(completion.receipt.report_sha256,),
        detail_sha256=completion.receipt.digest,
    )
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "replay_promotion_report"
        assert decision.expected_output_digests == (
            completion.receipt.report_sha256,
        )
        assert decision.expected_detail_sha256 == completion.receipt.digest
        assert decision.promotion is not None
        assert decision.promotion.completion == completion
    finally:
        ledger.close()


def test_failed_effect_without_promotion_replays_only_its_terminal(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    effect_start = start_effect(capability)
    capability.finish(effect_start, outcome="failed", detail_sha256="5" * 64)
    try:
        decision = inspect_promotion_effect_replay(capability, ledger)
        assert decision.action == "replay_effect_terminal_without_report"
        assert decision.expected_output_digests == ()
        assert decision.promotion is None
    finally:
        ledger.close()


def test_completed_effect_without_promotion_report_is_refused(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    effect_start = start_effect(capability)
    capability.finish(effect_start, outcome="completed", output_digests=("6" * 64,))
    try:
        with pytest.raises(
            PromotionEffectReplayMismatch,
            match="no persisted promotion report",
        ):
            inspect_promotion_effect_replay(capability, ledger)
    finally:
        ledger.close()


def test_terminal_effect_cannot_hide_pending_promotion(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    effect_start = start_effect(capability)
    start_promotion(capability, ledger)
    capability.finish(effect_start, outcome="failed", detail_sha256="7" * 64)
    try:
        with pytest.raises(
            PromotionEffectReplayMismatch,
            match="pending promotion execution",
        ):
            inspect_promotion_effect_replay(capability, ledger)
    finally:
        ledger.close()


@pytest.mark.parametrize(
    ("outputs", "detail", "match"),
    [
        (("8" * 64,), None, "output_digests|detail_sha256"),
        (None, "9" * 64, "output_digests|detail_sha256"),
    ],
)
def test_completed_effect_must_bind_exact_promotion_report(
    tmp_path, outputs, detail, match
) -> None:
    capability, ledger = build_fixture(tmp_path)
    effect_start = start_effect(capability)
    promotion_start = start_promotion(capability, ledger)
    completion = complete_promotion(capability, ledger, promotion_start)
    capability.finish(
        effect_start,
        outcome="completed",
        output_digests=(
            outputs
            if outputs is not None
            else (completion.receipt.report_sha256,)
        ),
        detail_sha256=(
            detail if detail is not None else completion.receipt.digest
        ),
    )
    try:
        with pytest.raises(PromotionEffectReplayMismatch, match=match):
            inspect_promotion_effect_replay(capability, ledger)
    finally:
        ledger.close()


def test_promotion_start_must_not_precede_effect_start(tmp_path) -> None:
    early = NOW - timedelta(seconds=1)
    capability, ledger = build_fixture(tmp_path, promotion_clock=lambda: early)
    capability.grant()
    start_promotion(capability, ledger)
    start_effect(capability)
    try:
        with pytest.raises(
            PromotionEffectReplayMismatch,
            match="precedes its top-level Effect-Lease start",
        ):
            inspect_promotion_effect_replay(capability, ledger)
    finally:
        ledger.close()
