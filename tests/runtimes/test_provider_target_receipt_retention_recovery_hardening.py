from __future__ import annotations

import pytest

from daedalus.runtimes.provider.target_receipt_retention_admission import (
    ProviderTargetReceiptRetentionAdmissionReceipt,
)
from daedalus.runtimes.provider.target_receipt_retention_contract import (
    RETENTION_GUARD_CONTRACT,
)
from daedalus.runtimes.provider.target_receipt_retention_recovery import (
    ProviderTargetReceiptRetentionRecoveryDecision,
    ProviderTargetReceiptRetentionRecoveryShapeError,
    decide_provider_target_receipt_retention_recovery,
)


REVISION = "1" * 40


def _admission() -> ProviderTargetReceiptRetentionAdmissionReceipt:
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
        execution_state="not_started",
        start_receipt_sha256=None,
        terminal_receipt_sha256=None,
        primary_checkout_path="/work/primary",
        retention_root_path="/work/retention",
        event_store_path="/work/retention/state/spine.sqlite3",
        receipt_cas_path="/work/retention/cas/receipts",
        effect_lease_store_path="/work/effects/effects.sqlite3",
    )


def _decision() -> ProviderTargetReceiptRetentionRecoveryDecision:
    return decide_provider_target_receipt_retention_recovery(
        _admission(),
        expected_source_revision=REVISION,
    )


def test_recovery_constructor_refuses_generic_64_hex_revision() -> None:
    with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
        ProviderTargetReceiptRetentionRecoveryDecision(
            source_revision="1" * 64,
            admission_sha256="2" * 64,
            execution_state="not_started",
            decision="request_fresh_start_authorization",
            start_receipt_sha256=None,
            terminal_receipt_sha256=None,
        )


def test_recovery_wire_refuses_generic_64_hex_revision() -> None:
    payload = _decision().to_dict()
    payload["source_revision"] = "1" * 64

    with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
        ProviderTargetReceiptRetentionRecoveryDecision.from_dict(payload)


def test_recovery_projection_refuses_64_hex_expected_revision_before_binding() -> None:
    with pytest.raises(ProviderTargetReceiptRetentionRecoveryShapeError):
        decide_provider_target_receipt_retention_recovery(
            _admission(),
            expected_source_revision="1" * 64,
        )
