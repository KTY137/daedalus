# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import copy

import pytest

from daedalus.runtimes.provider_target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider_target_receipt_retention_recovery import (
    ProviderTargetReceiptRetentionRecoveryBindingError,
    ProviderTargetReceiptRetentionRecoveryDecision,
    ProviderTargetReceiptRetentionRecoveryShapeError,
    decide_provider_target_receipt_retention_recovery,
)


REVISION = "1" * 40


def _admission(state: str = "not_started") -> ProviderTargetReceiptRetentionAdmissionReceipt:
    started = state != "not_started"
    terminal = state in {"COMPLETED", "FAILED", "CANCELLED"}
    return ProviderTargetReceiptRetentionAdmissionReceipt(
        source_revision=REVISION,
        preflight_sha256="2" * 64,
        provider_target_receipt_sha256="3" * 64,
        retention_inventory_sha256="4" * 64,
        retention_authority_sha256="5" * 64,
        retention_execution_request_sha256="6" * 64,
        retention_effect_lease_sha256="7" * 64,
        retention_effect_lease_request_sha256="8" * 64,
        retention_policy_decision_sha256="9" * 64,
        guard_contract=RETENTION_GUARD_CONTRACT,
        guard_evidence=f"authority_sha256={'a' * 64};subject_sha256={'b' * 64}",
        execution_state=state,
        start_receipt_sha256="c" * 64 if started else None,
        terminal_receipt_sha256="d" * 64 if terminal else None,
        primary_checkout_path="/work/primary",
        retention_root_path="/work/retention",
        event_store_path="/work/retention/state/spine.sqlite3",
        receipt_cas_path="/work/retention/cas/receipts",
        effect_lease_store_path="/work/effects/effects.sqlite3",
    )


@pytest.mark.parametrize(
    ("state", "decision", "reconciliation", "terminal"),
    (
        (
            "not_started",
            "request_fresh_start_authorization",
            False,
            False,
        ),
        ("started", "manual_reconciliation_required", True, False),
        (
            "COMPLETED",
            "verify_completed_retention_evidence",
            False,
            True,
        ),
        ("FAILED", "terminal_failure_refusal", False, True),
        ("CANCELLED", "terminal_cancellation_refusal", False, True),
    ),
)
def test_recovery_decision_is_exact_non_authorizing_projection(
    state: str,
    decision: str,
    reconciliation: bool,
    terminal: bool,
) -> None:
    admission = _admission(state)

    result = decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=REVISION,
    )
    payload = result.to_dict()

    assert result.source_revision == REVISION
    assert result.admission_sha256 == admission.digest
    assert result.execution_state == state
    assert result.decision == decision
    assert result.start_receipt_sha256 == admission.start_receipt_sha256
    assert result.terminal_receipt_sha256 == admission.terminal_receipt_sha256
    assert payload["admission_identity_bound"] is True
    assert payload["persisted_state_reverified"] is False
    assert payload["manual_reconciliation_required"] is reconciliation
    assert payload["terminal_state_observed"] is terminal
    for field in (
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert payload[field] is False


def test_recovery_decision_round_trip_and_digest_are_deterministic() -> None:
    result = decide_provider_target_receipt_retention_recovery(
        _admission("started"),
        expected_source_revision=REVISION,
    )

    restored = ProviderTargetReceiptRetentionRecoveryDecision.from_dict(
        result.to_dict()
    )

    assert restored == result
    assert restored.digest == result.digest
    assert restored.to_dict() == result.to_dict()


def test_recovery_decision_refuses_stale_or_malformed_revision() -> None:
    admission = _admission()

    with pytest.raises(ProviderTargetReceiptRetentionRecoveryBindingError):
        decide_provider_target_receipt_retention_recovery(
            admission,
            expected_source_revision="f" * 40,
        )

    for value in ("", "1" * 39, "G" * 40, True, None):
        with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
            decide_provider_target_receipt_retention_recovery(
                admission,
                expected_source_revision=value,  # type: ignore[arg-type]
            )


def test_recovery_decision_requires_exact_admission_type() -> None:
    class AdmissionSubclass(ProviderTargetReceiptRetentionAdmissionReceipt):
        pass

    original = _admission()
    subclassed = AdmissionSubclass(**{
        field: getattr(original, field)
        for field in original.__dataclass_fields__
    })

    for value in (object(), subclassed):
        with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
            decide_provider_target_receipt_retention_recovery(
                value,  # type: ignore[arg-type]
                expected_source_revision=REVISION,
            )


def test_recovery_decision_refuses_bypassed_inconsistent_admission() -> None:
    admission = _admission("not_started")
    object.__setattr__(admission, "execution_state", "started")

    with pytest.raises(ProviderTargetReceiptRetentionRecoveryBindingError):
        decide_provider_target_receipt_retention_recovery(
            admission,
            expected_source_revision=REVISION,
        )


def test_recovery_wire_refuses_action_receipt_and_claim_substitution() -> None:
    valid = decide_provider_target_receipt_retention_recovery(
        _admission("started"),
        expected_source_revision=REVISION,
    ).to_dict()
    mutations: list[dict[str, object]] = []

    payload = copy.deepcopy(valid)
    payload["decision"] = "request_fresh_start_authorization"
    mutations.append(payload)

    payload = copy.deepcopy(valid)
    payload["start_receipt_sha256"] = None
    mutations.append(payload)

    payload = copy.deepcopy(valid)
    payload["terminal_receipt_sha256"] = "d" * 64
    mutations.append(payload)

    for field in (
        "persisted_state_reverified",
        "automatic_reexecution_allowed",
        "effect_start_authorized",
        "retention_write_authorized",
        "effect_terminalization_authorized",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        payload = copy.deepcopy(valid)
        payload[field] = True
        mutations.append(payload)

    payload = copy.deepcopy(valid)
    payload["unexpected"] = False
    mutations.append(payload)

    for payload in mutations:
        with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
            ProviderTargetReceiptRetentionRecoveryDecision.from_dict(payload)


def test_each_state_changes_decision_identity() -> None:
    decisions = [
        decide_provider_target_receipt_retention_recovery(
            _admission(state),
            expected_source_revision=REVISION,
        )
        for state in (
            "not_started",
            "started",
            "COMPLETED",
            "FAILED",
            "CANCELLED",
        )
    ]

    assert len({row.digest for row in decisions}) == len(decisions)
    assert len({row.decision for row in decisions}) == len(decisions)
