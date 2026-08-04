from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_recovery import PromotionRecoveryPlan
from daedalus.kernel.promotion_recovery_decision import (
    PromotionRecoveryDecision,
    PromotionRecoveryDecisionBindingMismatch,
    PromotionRecoveryDecisionExpired,
    PromotionRecoveryDecisionSignatureError,
    recovery_expectation,
    verify_promotion_recovery_decision,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
AUTHORIZATION_DIGEST = "c" * 64
EFFECT_START_DIGEST = "d" * 64
SECRET = b"owner-recovery-secret-material-0001"
NOW = datetime(2026, 8, 4, 8, 0, tzinfo=timezone.utc)
ISSUED_AT = NOW.isoformat(timespec="microseconds")
EXPIRES_AT = (NOW + timedelta(hours=1)).isoformat(timespec="microseconds")


def _authorization(*, source_revision: str = REVISION) -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-recovery-1",
        "candidate_artifact_sha256": "1" * 64,
        "evidence_packet_sha256": "2" * 64,
        "source_revision": source_revision,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": REVISION,
        "approval_consumption_sha256": "3" * 64,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def _capability(*, source_revision: str = REVISION) -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(
        capability,
        "promotion",
        _authorization(source_revision=source_revision),
    )
    return capability


def _plan_body(**changes):
    authorization = _authorization()
    body = {
        "schema": "daedalus-promotion-recovery-plan/1",
        "promotion_authorization_sha256": authorization.authorization_sha256,
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
    body.update(changes)
    return body


def _plan(**changes) -> PromotionRecoveryPlan:
    body = _plan_body(**changes)
    return PromotionRecoveryPlan(
        **body,
        plan_sha256=canonical_sha(body),
    )


def _decision(
    *,
    plan: PromotionRecoveryPlan | None = None,
    capability: PromotionEffectCapability | None = None,
    source_revision: str = REVISION,
    issued_at: str = ISSUED_AT,
    expires_at: str = EXPIRES_AT,
    secret: bytes = SECRET,
    **changes,
) -> PromotionRecoveryDecision:
    selected_plan = plan or _plan()
    selected_capability = capability or _capability()
    expectation = recovery_expectation(selected_plan, selected_capability)
    body = {
        "decision_id": "recovery-decision-1",
        "owner_id": "owner-1",
        "key_id": "key-1",
        "operation": "cancel-unentered-promotion-effect",
        "promotion_authorization_sha256": (
            expectation.promotion_authorization_sha256
        ),
        "recovery_plan_sha256": expectation.recovery_plan_sha256,
        "effect_start_receipt_sha256": expectation.effect_start_receipt_sha256,
        "nonce": "recovery-nonce-1",
        "issued_at": issued_at,
        "expires_at": expires_at,
        "signature_sha256": "0" * 64,
        "provenance": ContractProvenance(
            origin="owner-console",
            source_revision=source_revision,
            created_at=issued_at,
            input_digests=(
                expectation.promotion_authorization_sha256,
                expectation.recovery_plan_sha256,
                expectation.effect_start_receipt_sha256,
            ),
        ),
    }
    body.update(changes)
    placeholder = PromotionRecoveryDecision(**body)
    signature = hmac.new(
        secret,
        placeholder.signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return replace(placeholder, signature_sha256=signature)


def test_expectation_accepts_only_exact_effect_only_plan() -> None:
    plan = _plan()
    capability = _capability()

    expectation = recovery_expectation(plan, capability)

    assert expectation.promotion_authorization_sha256 == (
        capability.promotion.authorization_sha256
    )
    assert expectation.recovery_plan_sha256 == plan.plan_sha256
    assert expectation.effect_start_receipt_sha256 == EFFECT_START_DIGEST
    assert expectation.source_revision == REVISION


@pytest.mark.parametrize(
    "changes",
    [
        {"schema": "daedalus-promotion-recovery-plan/2"},
        {"disposition": "promotion-pending-reconciliation"},
        {"action": "forensic-promotion-reconciliation"},
        {"automatic_external_reexecution": True},
        {"manual_reconciliation_required": False},
        {"owner_decision_required": False},
        {"effect_start_receipt_sha256": None},
        {"effect_terminal_receipt_sha256": "e" * 64},
        {"promotion_start_sha256": "f" * 64},
    ],
)
def test_expectation_refuses_coherently_rehashed_wrong_state(changes) -> None:
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_expectation(_plan(**changes), _capability())


def test_expectation_refuses_stale_digest_and_other_capability() -> None:
    plan = _plan()
    stale = replace(plan, plan_sha256="0" * 64)
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_expectation(stale, _capability())

    other = _capability(source_revision=OTHER_REVISION)
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_expectation(plan, other)


def test_signed_decision_verifies_and_round_trips() -> None:
    plan = _plan()
    capability = _capability()
    expectation = recovery_expectation(plan, capability)
    decision = _decision(plan=plan, capability=capability)

    verified = verify_promotion_recovery_decision(
        decision,
        keyring={("owner-1", "key-1"): SECRET},
        expectation=expectation,
        now=NOW + timedelta(minutes=1),
    )
    restored = PromotionRecoveryDecision.from_dict(decision.to_dict())

    assert restored == decision
    assert verified.decision_sha256 == decision.digest
    assert verified.recovery_plan_sha256 == plan.plan_sha256
    assert verified.effect_start_receipt_sha256 == EFFECT_START_DIGEST
    assert verified.source_revision == REVISION


def test_signature_unknown_key_and_substitution_refuse() -> None:
    expectation = recovery_expectation(_plan(), _capability())
    decision = _decision()

    with pytest.raises(PromotionRecoveryDecisionSignatureError):
        verify_promotion_recovery_decision(
            decision,
            keyring={},
            expectation=expectation,
            now=NOW,
        )
    with pytest.raises(PromotionRecoveryDecisionSignatureError):
        verify_promotion_recovery_decision(
            replace(decision, signature_sha256="9" * 64),
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"promotion_authorization_sha256": "4" * 64},
        {"recovery_plan_sha256": "5" * 64},
        {"effect_start_receipt_sha256": "6" * 64},
    ],
)
def test_resigned_subject_substitution_refuses(changes) -> None:
    expectation = recovery_expectation(_plan(), _capability())
    decision = _decision(**changes)

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        verify_promotion_recovery_decision(
            decision,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )


def test_resigned_source_revision_substitution_refuses() -> None:
    expectation = recovery_expectation(_plan(), _capability())
    decision = _decision(source_revision=OTHER_REVISION)

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        verify_promotion_recovery_decision(
            decision,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )


def test_future_expired_and_overlong_decisions_refuse() -> None:
    expectation = recovery_expectation(_plan(), _capability())

    future = _decision(
        issued_at=(NOW + timedelta(hours=2)).isoformat(timespec="microseconds"),
        expires_at=(NOW + timedelta(hours=3)).isoformat(timespec="microseconds"),
    )
    with pytest.raises(PromotionRecoveryDecisionExpired):
        verify_promotion_recovery_decision(
            future,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )

    expired = _decision(
        issued_at=(NOW - timedelta(hours=2)).isoformat(timespec="microseconds"),
        expires_at=(NOW - timedelta(hours=1)).isoformat(timespec="microseconds"),
    )
    with pytest.raises(PromotionRecoveryDecisionExpired):
        verify_promotion_recovery_decision(
            expired,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )

    overlong = _decision(
        issued_at=ISSUED_AT,
        expires_at=(NOW + timedelta(hours=25)).isoformat(timespec="microseconds"),
    )
    with pytest.raises(PromotionRecoveryDecisionExpired):
        verify_promotion_recovery_decision(
            overlong,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )


def test_malformed_types_refuse_without_verification() -> None:
    expectation = recovery_expectation(_plan(), _capability())
    decision = _decision()

    with pytest.raises(TypeError):
        verify_promotion_recovery_decision(
            object(),
            keyring={("owner-1", "key-1"): SECRET},
            expectation=expectation,
            now=NOW,
        )
    with pytest.raises(TypeError):
        verify_promotion_recovery_decision(
            decision,
            keyring=[],
            expectation=expectation,
            now=NOW,
        )
    with pytest.raises(TypeError):
        verify_promotion_recovery_decision(
            decision,
            keyring={("owner-1", "key-1"): SECRET},
            expectation=object(),
            now=NOW,
        )
