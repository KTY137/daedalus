from __future__ import annotations

import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from threading import Lock

import daedalus.kernel.promotion_recovery_decision as recovery_decision
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_recovery import PromotionRecoveryPlan
from daedalus.kernel.promotion_recovery_consumption import (
    ConsumedPromotionRecoveryDecision,
    PromotionRecoveryConsumptionLedger,
    PromotionRecoveryConsumptionReplay,
)
from daedalus.kernel.promotion_recovery_decision import PromotionRecoveryDecision
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
EFFECT_START_DIGEST = "d" * 64
SECRET = b"owner-recovery-secret-material-0001"
NOW = datetime(2026, 8, 4, 9, 30, tzinfo=timezone.utc)
ISSUED_AT = (NOW - timedelta(minutes=5)).isoformat(timespec="microseconds")
EXPIRES_AT = (NOW + timedelta(hours=1)).isoformat(timespec="microseconds")


def _authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-recovery-concurrent",
        "candidate_artifact_sha256": "1" * 64,
        "evidence_packet_sha256": "2" * 64,
        "source_revision": REVISION,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": "3" * 64,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def _capability() -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(capability, "promotion", _authorization())
    return capability


def _promotion_ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


def _plan() -> PromotionRecoveryPlan:
    body = {
        "schema": "daedalus-promotion-recovery-plan/1",
        "promotion_authorization_sha256": _authorization().authorization_sha256,
        "disposition": "effect-only-pending-reconciliation",
        "action": "owner-decision-before-effect-cancellation",
        "automatic_external_reexecution": False,
        "manual_reconciliation_required": True,
        "owner_decision_required": True,
        "effect_start_receipt_sha256": EFFECT_START_DIGEST,
        "effect_terminal_receipt_sha256": None,
        "promotion_start_sha256": None,
        "promotion_terminal_sha256": None,
    }
    return PromotionRecoveryPlan(
        **body,
        plan_sha256=canonical_sha(body),
    )


def _decision(plan: PromotionRecoveryPlan) -> PromotionRecoveryDecision:
    body = {
        "decision_id": "recovery-decision-concurrent",
        "owner_id": "owner-1",
        "key_id": "key-1",
        "operation": "cancel-unentered-promotion-effect",
        "promotion_authorization_sha256": plan.promotion_authorization_sha256,
        "recovery_plan_sha256": plan.plan_sha256,
        "effect_start_receipt_sha256": plan.effect_start_receipt_sha256,
        "nonce": "recovery-nonce-concurrent",
        "issued_at": ISSUED_AT,
        "expires_at": EXPIRES_AT,
        "signature_sha256": "0" * 64,
        "provenance": ContractProvenance(
            origin="owner-console",
            source_revision=REVISION,
            created_at=ISSUED_AT,
            input_digests=(
                plan.promotion_authorization_sha256,
                plan.plan_sha256,
                plan.effect_start_receipt_sha256,
            ),
        ),
    }
    unsigned = PromotionRecoveryDecision(**body)
    signature = hmac.new(
        SECRET,
        unsigned.signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return replace(unsigned, signature_sha256=signature)


def test_concurrent_same_decision_has_exactly_one_durable_winner(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    projection_lock = Lock()
    projection_calls = 0

    def project(current_capability, current_promotion_ledger):
        nonlocal projection_calls
        assert current_capability is capability
        assert current_promotion_ledger is promotion_ledger
        with projection_lock:
            projection_calls += 1
        return plan

    monkeypatch.setattr(
        recovery_decision,
        "plan_promotion_recovery",
        project,
    )

    path = tmp_path / "recovery.sqlite3"
    ledgers = (
        PromotionRecoveryConsumptionLedger(path, clock=lambda: NOW),
        PromotionRecoveryConsumptionLedger(path, clock=lambda: NOW),
    )
    decision = _decision(plan)

    def consume(ledger: PromotionRecoveryConsumptionLedger):
        try:
            return ledger.consume(
                decision,
                keyring={("owner-1", "key-1"): SECRET},
                capability=capability,
                promotion_ledger=promotion_ledger,
            )
        except PromotionRecoveryConsumptionReplay as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(consume, ledgers))

    receipts = [
        result
        for result in results
        if isinstance(result, ConsumedPromotionRecoveryDecision)
    ]
    replays = [
        result
        for result in results
        if isinstance(result, PromotionRecoveryConsumptionReplay)
    ]

    assert len(receipts) == 1
    assert len(replays) == 1
    assert projection_calls == 4
    assert ledgers[0].consumed(decision.digest) is True
    assert ledgers[1].verify_consumption(
        receipts[0],
        keyring={("owner-1", "key-1"): SECRET},
    ) == receipts[0]
