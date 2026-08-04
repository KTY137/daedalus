from __future__ import annotations

import hashlib
import hmac
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import daedalus.kernel.promotion_recovery_decision as recovery_decision
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_recovery import PromotionRecoveryPlan
from daedalus.kernel.promotion_recovery_consumption import (
    ConsumedPromotionRecoveryDecision,
    PromotionRecoveryConsumptionLedger,
    PromotionRecoveryConsumptionReplay,
    PromotionRecoveryConsumptionStateError,
)
from daedalus.kernel.promotion_recovery_decision import (
    PromotionRecoveryDecision,
    PromotionRecoveryDecisionBindingMismatch,
    PromotionRecoveryDecisionExpired,
    PromotionRecoveryDecisionSignatureError,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
EFFECT_START_DIGEST = "d" * 64
OTHER_EFFECT_START_DIGEST = "e" * 64
SECRET = b"owner-recovery-secret-material-0001"
NOW = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
ISSUED_AT = (NOW - timedelta(minutes=5)).isoformat(timespec="microseconds")
EXPIRES_AT = (NOW + timedelta(hours=1)).isoformat(timespec="microseconds")


class SequenceClock:
    def __init__(self, *values: datetime):
        self.values = list(values)

    def __call__(self) -> datetime:
        if not self.values:
            raise AssertionError("test clock exhausted")
        return self.values.pop(0)


def _authorization() -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-recovery-1",
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


def _plan(*, effect_start: str = EFFECT_START_DIGEST) -> PromotionRecoveryPlan:
    body = {
        "schema": "daedalus-promotion-recovery-plan/1",
        "promotion_authorization_sha256": _authorization().authorization_sha256,
        "disposition": "effect-only-pending-reconciliation",
        "action": "owner-decision-before-effect-cancellation",
        "automatic_external_reexecution": False,
        "manual_reconciliation_required": True,
        "owner_decision_required": True,
        "effect_start_receipt_sha256": effect_start,
        "effect_terminal_receipt_sha256": None,
        "promotion_start_sha256": None,
        "promotion_terminal_sha256": None,
    }
    return PromotionRecoveryPlan(
        **body,
        plan_sha256=canonical_sha(body),
    )


def _project(monkeypatch, *plans: PromotionRecoveryPlan):
    queue = list(plans)
    calls = []

    def projection(capability, promotion_ledger):
        calls.append((capability, promotion_ledger))
        if not queue:
            raise AssertionError("test recovery projection exhausted")
        return queue.pop(0)

    monkeypatch.setattr(
        recovery_decision,
        "plan_promotion_recovery",
        projection,
    )
    return calls


def _decision(
    *,
    plan: PromotionRecoveryPlan | None = None,
    decision_id: str = "recovery-decision-1",
    nonce: str = "recovery-nonce-1",
    issued_at: str = ISSUED_AT,
    expires_at: str = EXPIRES_AT,
    secret: bytes = SECRET,
) -> PromotionRecoveryDecision:
    selected = plan or _plan()
    body = {
        "decision_id": decision_id,
        "owner_id": "owner-1",
        "key_id": "key-1",
        "operation": "cancel-unentered-promotion-effect",
        "promotion_authorization_sha256": (
            selected.promotion_authorization_sha256
        ),
        "recovery_plan_sha256": selected.plan_sha256,
        "effect_start_receipt_sha256": (
            selected.effect_start_receipt_sha256
        ),
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signature_sha256": "0" * 64,
        "provenance": ContractProvenance(
            origin="owner-console",
            source_revision=REVISION,
            created_at=issued_at,
            input_digests=(
                selected.promotion_authorization_sha256,
                selected.plan_sha256,
                selected.effect_start_receipt_sha256,
            ),
        ),
    }
    placeholder = PromotionRecoveryDecision(**body)
    signature = hmac.new(
        secret,
        placeholder.signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return replace(placeholder, signature_sha256=signature)


def _consume(
    ledger: PromotionRecoveryConsumptionLedger,
    decision: PromotionRecoveryDecision,
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
):
    return ledger.consume(
        decision,
        keyring={("owner-1", "key-1"): SECRET},
        capability=capability,
        promotion_ledger=promotion_ledger,
    )


def test_consumption_is_durable_one_use_and_round_trips(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    calls = _project(monkeypatch, plan, plan)
    ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "recovery.sqlite3",
        clock=SequenceClock(NOW, NOW, NOW),
    )
    decision = _decision(plan=plan)

    receipt = _consume(ledger, decision, capability, promotion_ledger)
    persisted = ledger.verify_consumption(
        receipt,
        keyring={("owner-1", "key-1"): SECRET},
    )
    restored = ConsumedPromotionRecoveryDecision.from_dict(receipt.to_dict())

    assert calls == [
        (capability, promotion_ledger),
        (capability, promotion_ledger),
    ]
    assert persisted == receipt == restored
    assert ledger.consumed(decision.digest) is True
    assert receipt.verified.decision_sha256 == decision.digest
    assert receipt.expectation.recovery_plan_sha256 == plan.plan_sha256
    assert receipt.expectation.effect_start_receipt_sha256 == EFFECT_START_DIGEST


def test_same_decision_replay_and_same_subject_reauthorization_refuse(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    _project(monkeypatch, plan, plan, plan, plan, plan, plan)
    ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "recovery.sqlite3",
        clock=SequenceClock(*(NOW for _ in range(9))),
    )
    first = _decision(plan=plan)
    second = _decision(
        plan=plan,
        decision_id="recovery-decision-2",
        nonce="recovery-nonce-2",
    )

    _consume(ledger, first, capability, promotion_ledger)
    with pytest.raises(PromotionRecoveryConsumptionReplay):
        _consume(ledger, first, capability, promotion_ledger)
    with pytest.raises(PromotionRecoveryConsumptionReplay):
        _consume(ledger, second, capability, promotion_ledger)

    assert ledger.consumed(first.digest) is True
    assert ledger.consumed(second.digest) is False


def test_forged_decision_refuses_before_persistence_and_second_projection(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    calls = _project(monkeypatch, plan)
    ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "recovery.sqlite3",
        clock=SequenceClock(NOW),
    )
    forged = replace(
        _decision(plan=plan),
        signature_sha256="9" * 64,
    )

    with pytest.raises(PromotionRecoveryDecisionSignatureError):
        _consume(ledger, forged, capability, promotion_ledger)

    assert calls == []
    assert ledger.consumed(forged.digest) is False


def test_state_change_between_preflight_and_transaction_rolls_back(
    tmp_path,
    monkeypatch,
) -> None:
    initial = _plan()
    changed = _plan(effect_start=OTHER_EFFECT_START_DIGEST)
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    calls = _project(monkeypatch, initial, changed)
    ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "recovery.sqlite3",
        clock=SequenceClock(NOW, NOW),
    )
    decision = _decision(plan=initial)

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        _consume(ledger, decision, capability, promotion_ledger)

    assert len(calls) == 2
    assert ledger.consumed(decision.digest) is False


def test_clock_rollback_and_expiry_before_commit_leave_no_consumption(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    decision = _decision(plan=plan)

    _project(monkeypatch, plan)
    rollback_ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "rollback.sqlite3",
        clock=SequenceClock(NOW, NOW - timedelta(seconds=1)),
    )
    with pytest.raises(PromotionRecoveryConsumptionStateError):
        _consume(rollback_ledger, decision, capability, promotion_ledger)
    assert rollback_ledger.consumed(decision.digest) is False

    _project(monkeypatch, plan, plan)
    expiry_ledger = PromotionRecoveryConsumptionLedger(
        tmp_path / "expiry.sqlite3",
        clock=SequenceClock(
            NOW,
            NOW + timedelta(minutes=1),
            NOW + timedelta(hours=2),
        ),
    )
    with pytest.raises(PromotionRecoveryDecisionExpired):
        _consume(expiry_ledger, decision, capability, promotion_ledger)
    assert expiry_ledger.consumed(decision.digest) is False


def test_verify_consumption_detects_redundant_column_tampering(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    _project(monkeypatch, plan, plan)
    path = tmp_path / "recovery.sqlite3"
    ledger = PromotionRecoveryConsumptionLedger(
        path,
        clock=SequenceClock(NOW, NOW, NOW),
    )
    receipt = _consume(
        ledger,
        _decision(plan=plan),
        capability,
        promotion_ledger,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE promotion_recovery_consumptions_v1 "
            "SET operation='tampered-operation'"
        )

    with pytest.raises(PromotionRecoveryConsumptionStateError):
        ledger.verify_consumption(
            receipt,
            keyring={("owner-1", "key-1"): SECRET},
        )


def test_verify_consumption_detects_json_corruption(
    tmp_path,
    monkeypatch,
) -> None:
    plan = _plan()
    capability = _capability()
    promotion_ledger = _promotion_ledger()
    _project(monkeypatch, plan, plan)
    path = tmp_path / "recovery.sqlite3"
    ledger = PromotionRecoveryConsumptionLedger(
        path,
        clock=SequenceClock(NOW, NOW, NOW),
    )
    receipt = _consume(
        ledger,
        _decision(plan=plan),
        capability,
        promotion_ledger,
    )

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE promotion_recovery_consumptions_v1 "
            "SET consumption_json='not-json'"
        )

    with pytest.raises(PromotionRecoveryConsumptionStateError):
        ledger.verify_consumption(
            receipt,
            keyring={("owner-1", "key-1"): SECRET},
        )


def test_malformed_inputs_refuse(tmp_path) -> None:
    ledger = PromotionRecoveryConsumptionLedger(tmp_path / "recovery.sqlite3")

    with pytest.raises(TypeError):
        ledger.consume(
            object(),
            keyring={},
            capability=_capability(),
            promotion_ledger=_promotion_ledger(),
        )
    with pytest.raises(TypeError):
        ledger.verify_consumption(object(), keyring={})
    with pytest.raises(ValueError):
        ledger.consumed("not-a-digest")
