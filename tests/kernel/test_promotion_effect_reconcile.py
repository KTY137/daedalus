from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectLeaseStateError,
    issue_effect_lease,
)
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effect_reconcile import (
    PromotionEffectReconciliationMismatch,
    PromotionEffectReconciliationRefused,
    reconcile_promotion_effect_terminal,
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
SECRET = b"promotion-effect-reconcile-secret-32-bytes-minimum"
NOW = datetime.now(timezone.utc).replace(microsecond=0)
PROMOTION_TIME = NOW + timedelta(seconds=1)


def build_fixture(tmp_path):
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
        request_id="promotion-reconcile-request-1",
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
            origin="tests.promotion-effect-reconcile",
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
        decision_id="promotion-reconcile-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-04",
        policy_sha256=POLICY,
        verdict="allow",
        reasons=("bounded owner-approved promotion",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.promotion-effect-reconcile-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY),
            trace_id=promotion.promotion_id,
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="promotion-reconcile-lease-1",
        issuer_key_id="promotion-reconcile-key-1",
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
        lease_keyring={"promotion-reconcile-key-1": SECRET},
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
    promotion_ledger = PromotionExecutionLedger(
        tmp_path / "spine.sqlite3",
        clock=lambda: PROMOTION_TIME,
    )
    return capability, promotion_ledger


def report(capability, outcome):
    payload = {
        "promoted": [],
        "refused": [],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": capability.promotion.to_dict(),
        "cleanup_error": None,
    }
    if outcome == "succeeded":
        payload["promoted"] = [{"task_id": "task-1", "promoted": True}]
        payload["integration_branch"] = "integration/promotion-1"
        payload["integration_revision"] = INTEGRATION
    elif outcome == "refused":
        payload["refused"] = [{"task_id": "task-1", "reason": "policy refusal"}]
    elif outcome == "faulted":
        payload["fault"] = "simulated persisted fault"
    else:
        raise AssertionError(outcome)
    return payload


def start_effect(capability):
    capability.grant()
    started = capability.begin()
    assert started.execute is True
    return started.receipt


def complete_promotion(capability, ledger, outcome):
    started = ledger.begin(
        capability.promotion,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    assert started.execute is True
    integration_branch = "integration/promotion-1" if outcome == "succeeded" else None
    integration_revision = INTEGRATION if outcome == "succeeded" else None
    return ledger.complete(
        started.start,
        receipt_id="promotion-receipt-1",
        outcome=outcome,
        report=report(capability, outcome),
        integration_branch=integration_branch,
        integration_revision=integration_revision,
        primary_checkout_after_sha256=PRIMARY,
    )


@pytest.mark.parametrize(
    ("promotion_outcome", "effect_outcome"),
    [
        ("succeeded", "COMPLETED"),
        ("refused", "COMPLETED"),
        ("faulted", "FAILED"),
    ],
)
def test_reconciles_exact_terminal_from_retained_promotion(
    tmp_path,
    promotion_outcome,
    effect_outcome,
) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    completion = complete_promotion(capability, ledger, promotion_outcome)
    try:
        result = reconcile_promotion_effect_terminal(capability, ledger)
        assert result.changed is True
        assert result.decision.action == "replay_promotion_report"
        assert result.terminal_receipt.outcome == effect_outcome
        assert result.terminal_receipt.output_digests == (
            completion.receipt.report_sha256,
        )
        assert result.terminal_receipt.detail_sha256 == completion.receipt.digest
        assert result.terminal_receipt.finished_at == completion.receipt.completed_at
    finally:
        ledger.close()


def test_exact_second_reconciliation_is_read_only_replay(tmp_path) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    complete_promotion(capability, ledger, "succeeded")
    try:
        first = reconcile_promotion_effect_terminal(capability, ledger)
        second = reconcile_promotion_effect_terminal(capability, ledger)
        assert first.changed is True
        assert second.changed is False
        assert second.terminal_receipt == first.terminal_receipt
    finally:
        ledger.close()


def test_later_lease_revocation_does_not_erase_effect_that_already_happened(
    tmp_path,
) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    complete_promotion(capability, ledger, "succeeded")
    capability.authorization.effect_ledger.revoke(
        capability.authorization.lease.digest,
        reason="administrative revocation after persisted promotion terminal",
    )
    try:
        result = reconcile_promotion_effect_terminal(capability, ledger)
        assert result.changed is True
        assert result.terminal_receipt.outcome == "COMPLETED"
    finally:
        ledger.close()


@pytest.mark.parametrize("state", ["fresh", "effect_pending", "promotion_pending"])
def test_nonterminal_promotion_states_are_refused_without_effect_terminal(
    tmp_path,
    state,
) -> None:
    capability, ledger = build_fixture(tmp_path)
    capability.grant()
    if state in {"effect_pending", "promotion_pending"}:
        capability.begin()
    if state == "promotion_pending":
        ledger.begin(
            capability.promotion,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
    try:
        with pytest.raises(PromotionEffectReconciliationRefused):
            reconcile_promotion_effect_terminal(capability, ledger)
        assert (
            capability.authorization.effect_ledger.execution_state(
                capability.execution.execution_id
            )
            in {None, "STARTED"}
        )
    finally:
        ledger.close()


def test_concurrent_exact_terminalization_is_replayed_not_duplicated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    complete_promotion(capability, ledger, "succeeded")
    effect_ledger = capability.authorization.effect_ledger
    original_finish = effect_ledger.finish

    def racing_finish(*args, **kwargs):
        original_finish(*args, **kwargs)
        raise EffectLeaseStateError("simulated concurrent terminalization")

    monkeypatch.setattr(effect_ledger, "finish", racing_finish)
    try:
        result = reconcile_promotion_effect_terminal(capability, ledger)
        assert result.changed is False
        assert result.decision.action == "replay_promotion_report"
    finally:
        ledger.close()


def test_nonmatching_concurrent_terminal_is_refused(tmp_path, monkeypatch) -> None:
    capability, ledger = build_fixture(tmp_path)
    start_effect(capability)
    complete_promotion(capability, ledger, "succeeded")
    effect_ledger = capability.authorization.effect_ledger
    original_finish = effect_ledger.finish

    def racing_wrong_finish(start, **_kwargs):
        original_finish(
            start,
            outcome="failed",
            detail_sha256="9" * 64,
            finished_at=PROMOTION_TIME,
        )
        raise EffectLeaseStateError("simulated contradictory terminalization")

    monkeypatch.setattr(effect_ledger, "finish", racing_wrong_finish)
    try:
        with pytest.raises(
            (PromotionEffectReconciliationMismatch, Exception),
        ) as raised:
            reconcile_promotion_effect_terminal(capability, ledger)
        assert "promotion report" in str(raised.value) or "terminal" in str(raised.value)
    finally:
        ledger.close()
