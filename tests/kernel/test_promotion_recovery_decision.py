from __future__ import annotations

import hashlib
import hmac
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

import daedalus.kernel.promotion_recovery_decision as recovery_decision
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_recovery import PromotionRecoveryPlan
from daedalus.kernel.promotion_recovery_decision import (
    PromotionRecoveryDecision,
    PromotionRecoveryDecisionBindingMismatch,
    PromotionRecoveryDecisionExpired,
    PromotionRecoveryDecisionSignatureError,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
EFFECT_START_DIGEST = "d" * 64
OTHER_EFFECT_START_DIGEST = "e" * 64
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


def _ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


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


@pytest.fixture
def current_projection(monkeypatch):
    state = {"plan": _plan(), "calls": []}

    def project(capability, promotion_ledger):
        state["calls"].append((capability, promotion_ledger))
        return state["plan"]

    monkeypatch.setattr(recovery_decision, "plan_promotion_recovery", project)
    return state


def _decision(
    *,
    capability: PromotionEffectCapability,
    promotion_ledger: PromotionExecutionLedger,
    source_revision: str = REVISION,
    issued_at: str = ISSUED_AT,
    expires_at: str = EXPIRES_AT,
    secret: bytes = SECRET,
    **changes,
) -> PromotionRecoveryDecision:
    expectation = recovery_decision.recovery_expectation(
        capability,
        promotion_ledger,
    )
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
    }
    body.update(changes)
    body.setdefault(
        "provenance",
        ContractProvenance(
            origin="owner-console",
            source_revision=source_revision,
            created_at=str(body["issued_at"]),
            input_digests=(
                str(body["promotion_authorization_sha256"]),
                str(body["recovery_plan_sha256"]),
                str(body["effect_start_receipt_sha256"]),
            ),
        ),
    )
    placeholder = PromotionRecoveryDecision(**body)
    signature = hmac.new(
        secret,
        placeholder.signing_digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return replace(placeholder, signature_sha256=signature)


def _verify(decision, *, capability, promotion_ledger, now=NOW):
    return recovery_decision.verify_promotion_recovery_decision(
        decision,
        keyring={("owner-1", "key-1"): SECRET},
        capability=capability,
        promotion_ledger=promotion_ledger,
        now=now,
    )


def test_expectation_is_derived_from_current_strict_projection(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()

    expectation = recovery_decision.recovery_expectation(
        capability,
        promotion_ledger,
    )

    assert current_projection["calls"] == [(capability, promotion_ledger)]
    assert expectation.promotion_authorization_sha256 == (
        capability.promotion.authorization_sha256
    )
    assert expectation.recovery_plan_sha256 == current_projection["plan"].plan_sha256
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
        {"effect_terminal_receipt_sha256": "f" * 64},
        {"promotion_start_sha256": "9" * 64},
    ],
)
def test_expectation_refuses_coherently_rehashed_wrong_current_state(
    current_projection,
    changes,
) -> None:
    current_projection["plan"] = _plan(**changes)
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_decision.recovery_expectation(_capability(), _ledger())


def test_expectation_refuses_stale_digest_and_other_capability(
    current_projection,
) -> None:
    current_projection["plan"] = replace(
        _plan(),
        plan_sha256="0" * 64,
    )
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_decision.recovery_expectation(_capability(), _ledger())

    current_projection["plan"] = _plan()
    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        recovery_decision.recovery_expectation(
            _capability(source_revision=OTHER_REVISION),
            _ledger(),
        )


def test_signed_decision_verifies_against_fresh_projection_and_round_trips(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
    )
    current_projection["calls"].clear()

    verified = _verify(
        decision,
        capability=capability,
        promotion_ledger=promotion_ledger,
        now=NOW + timedelta(minutes=1),
    )
    restored = PromotionRecoveryDecision.from_dict(decision.to_dict())

    assert current_projection["calls"] == [(capability, promotion_ledger)]
    assert restored == decision
    assert verified.decision_sha256 == decision.digest
    assert verified.recovery_plan_sha256 == current_projection["plan"].plan_sha256
    assert verified.effect_start_receipt_sha256 == EFFECT_START_DIGEST
    assert verified.source_revision == REVISION


def test_signature_refusal_occurs_before_ledger_projection(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
    )
    current_projection["calls"].clear()

    with pytest.raises(PromotionRecoveryDecisionSignatureError):
        recovery_decision.verify_promotion_recovery_decision(
            decision,
            keyring={},
            capability=capability,
            promotion_ledger=promotion_ledger,
            now=NOW,
        )
    assert current_projection["calls"] == []

    with pytest.raises(PromotionRecoveryDecisionSignatureError):
        _verify(
            replace(decision, signature_sha256="9" * 64),
            capability=capability,
            promotion_ledger=promotion_ledger,
        )
    assert current_projection["calls"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"promotion_authorization_sha256": "4" * 64},
        {"recovery_plan_sha256": "5" * 64},
        {"effect_start_receipt_sha256": "6" * 64},
    ],
)
def test_resigned_subject_substitution_refuses_after_current_projection(
    current_projection,
    changes,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
        **changes,
    )
    current_projection["calls"].clear()

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        _verify(
            decision,
            capability=capability,
            promotion_ledger=promotion_ledger,
        )
    assert current_projection["calls"] == [(capability, promotion_ledger)]


def test_resigned_source_revision_substitution_refuses(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
        source_revision=OTHER_REVISION,
    )
    current_projection["calls"].clear()

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        _verify(
            decision,
            capability=capability,
            promotion_ledger=promotion_ledger,
        )


def test_changed_current_effect_start_invalidates_previously_signed_decision(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
    )
    current_projection["plan"] = _plan(
        effect_start_receipt_sha256=OTHER_EFFECT_START_DIGEST,
    )

    with pytest.raises(PromotionRecoveryDecisionBindingMismatch):
        _verify(
            decision,
            capability=capability,
            promotion_ledger=promotion_ledger,
        )


def test_future_expired_and_overlong_decisions_refuse_before_projection(
    current_projection,
) -> None:
    capability = _capability()
    promotion_ledger = _ledger()

    future = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
        issued_at=(NOW + timedelta(hours=2)).isoformat(timespec="microseconds"),
        expires_at=(NOW + timedelta(hours=3)).isoformat(timespec="microseconds"),
    )
    expired = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
        issued_at=(NOW - timedelta(hours=2)).isoformat(timespec="microseconds"),
        expires_at=(NOW - timedelta(hours=1)).isoformat(timespec="microseconds"),
    )
    overlong = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
        issued_at=ISSUED_AT,
        expires_at=(NOW + timedelta(hours=25)).isoformat(timespec="microseconds"),
    )
    current_projection["calls"].clear()

    for decision in (future, expired, overlong):
        with pytest.raises(PromotionRecoveryDecisionExpired):
            _verify(
                decision,
                capability=capability,
                promotion_ledger=promotion_ledger,
            )
    assert current_projection["calls"] == []


def test_malformed_types_refuse_without_projection(current_projection) -> None:
    capability = _capability()
    promotion_ledger = _ledger()
    decision = _decision(
        capability=capability,
        promotion_ledger=promotion_ledger,
    )
    current_projection["calls"].clear()

    with pytest.raises(TypeError):
        recovery_decision.verify_promotion_recovery_decision(
            object(),
            keyring={("owner-1", "key-1"): SECRET},
            capability=capability,
            promotion_ledger=promotion_ledger,
            now=NOW,
        )
    with pytest.raises(TypeError):
        recovery_decision.verify_promotion_recovery_decision(
            decision,
            keyring=[],
            capability=capability,
            promotion_ledger=promotion_ledger,
            now=NOW,
        )
    with pytest.raises(TypeError):
        recovery_decision.verify_promotion_recovery_decision(
            decision,
            keyring={("owner-1", "key-1"): SECRET},
            capability=object(),
            promotion_ledger=promotion_ledger,
            now=NOW,
        )
    with pytest.raises(TypeError):
        recovery_decision.verify_promotion_recovery_decision(
            decision,
            keyring={("owner-1", "key-1"): SECRET},
            capability=capability,
            promotion_ledger=object(),
            now=NOW,
        )
    assert current_projection["calls"] == []
