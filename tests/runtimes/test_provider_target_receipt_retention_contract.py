from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
    RETENTION_GUARD_CONTRACT,
    ProviderTargetReceiptRetentionContractBindingError,
    ProviderTargetReceiptRetentionContractExpired,
    ProviderTargetReceiptRetentionContractSignatureError,
    ProviderTargetReceiptRetentionOperationAuthority,
    ProviderTargetReceiptRetentionOperationSubject,
    authorize_provider_target_receipt_retention_operation,
    build_provider_target_receipt_retention_operation_subject,
    issue_provider_target_receipt_retention_operation_authority,
    verify_provider_target_receipt_retention_operation_authority,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    VerifiedPythonTarget,
)
from daedalus.schemas import ContractProvenance, EffectScope

REVISION = "bf678e837a374787c0198ba6047777001a991f41"
NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
SECRET = b"retention-operation-authority-secret-at-least-32-bytes"
KEYRING = {"retention-operation-key": SECRET}
EVENT_PATH = "attempt/state/spine.sqlite3"
CAS_PATH = "attempt/cas/receipts"
INVENTORY_SHA256 = "8" * 64
INVENTORY_SOURCE_SHA256 = "9" * 64


def _verified_target(name: str) -> VerifiedPythonTarget:
    return VerifiedPythonTarget(
        target=f"daedalus.runtimes.provider_runtime_broker:{name}",
        repository_path="daedalus/runtimes/provider_runtime_broker.py",
        source_sha256=("a" if name == "run_runtime_provider" else "b") * 64,
        source_size=2048,
        qualified_name=name,
        node_kind="function",
        line=10 if name == "run_runtime_provider" else 30,
        end_line=20 if name == "run_runtime_provider" else 40,
    )


def _receipt() -> ProviderExecutableTargetVerificationReceipt:
    source_tree_sha256 = "1" * 64
    return ProviderExecutableTargetVerificationReceipt(
        verifier_id="verifier.provider-target",
        verifier_key_id="provider-target-key",
        source_revision=REVISION,
        source_tree_id="provider-target-source-tree",
        source_tree_sha256=source_tree_sha256,
        source_tree_locator=ArtifactRef.from_sha256(source_tree_sha256).locator,
        target_authority_sha256="2" * 64,
        target_projection_sha256="3" * 64,
        target_manifest_sha256="4" * 64,
        target_descriptor_sha256="5" * 64,
        provider_id="provider.fixture",
        adapter_id="adapter.fixture",
        implementation_id="implementation.fixture",
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime.fixture",
        execution_id="provider-execution",
        idempotency_key="provider-idempotency",
        lease_sha256="6" * 64,
        invoke=_verified_target("run_runtime_provider"),
        output_digests=_verified_target("materialize_output_digests"),
        signature_sha256="7" * 64,
    )


def _execution(**changes) -> EffectExecutionRequest:
    values = {
        "execution_id": "retention-execution",
        "idempotency_key": "retention-idempotency",
        "requested_effects": ("filesystem_write",),
        "writable_paths": (EVENT_PATH, CAS_PATH),
        "kill_switch_ref": "retention-kill-switch",
        "kill_switch_generation": 23,
    }
    values.update(changes)
    return EffectExecutionRequest(**values)


def _lease(**changes) -> EffectLease:
    request_sha256 = "c" * 64
    policy_sha256 = "d" * 64
    registry_sha256 = "e" * 64
    values = {
        "lease_id": "provider-target-receipt-retention-lease",
        "request_id": "provider-target-receipt-retention-request",
        "request_sha256": request_sha256,
        "policy_decision_id": "provider-target-receipt-retention-policy",
        "policy_decision_sha256": policy_sha256,
        "registry_sha256": registry_sha256,
        "entrypoint_id": RETENTION_ENTRYPOINT,
        "requested_effects": ("filesystem_write",),
        "effect_scope": EffectScope(
            read_only=False,
            writable_paths=(EVENT_PATH, CAS_PATH),
            kill_switch_ref="retention-kill-switch",
        ),
        "idempotency_namespace": "provider-target-receipt-retention",
        "kill_switch_generation": 23,
        "runtime_id": "",
        "runtime_manifest_sha256": None,
        "runtime_conformance_sha256": None,
        "issuer_key_id": "effect-lease-key",
        "issued_at": (NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(timespec="microseconds"),
        "signature_sha256": "f" * 64,
        "provenance": ContractProvenance(
            origin="test.provider-target-receipt-retention-contract",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
            input_digests=(request_sha256, policy_sha256, registry_sha256),
            trace_id="provider-target-receipt-retention-contract-trace",
        ),
    }
    values.update(changes)
    return EffectLease(**values)


def _subject(
    *,
    receipt: ProviderExecutableTargetVerificationReceipt | None = None,
    execution: EffectExecutionRequest | None = None,
    lease: EffectLease | None = None,
    inventory_sha256: str = INVENTORY_SHA256,
    inventory_source_sha256: str = INVENTORY_SOURCE_SHA256,
    event_path: str = EVENT_PATH,
    cas_path: str = CAS_PATH,
) -> ProviderTargetReceiptRetentionOperationSubject:
    return build_provider_target_receipt_retention_operation_subject(
        receipt=_receipt() if receipt is None else receipt,
        retention_inventory_sha256=inventory_sha256,
        retention_inventory_source_sha256=inventory_source_sha256,
        execution=_execution() if execution is None else execution,
        effect_lease=_lease() if lease is None else lease,
        event_store_scope_path=event_path,
        receipt_cas_scope_path=cas_path,
    )


def _authority(
    subject: ProviderTargetReceiptRetentionOperationSubject,
) -> ProviderTargetReceiptRetentionOperationAuthority:
    return issue_provider_target_receipt_retention_operation_authority(
        authority_id="authority.provider-target-receipt-retention",
        authority_key_id="retention-operation-key",
        authority_secret=SECRET,
        nonce="provider-target-receipt-retention-nonce",
        subject=subject,
        issued_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=5),
    )


def test_exact_subject_and_signed_authority_round_trip() -> None:
    subject = _subject()
    authority = _authority(subject)

    restored_subject = ProviderTargetReceiptRetentionOperationSubject.from_dict(
        subject.to_dict()
    )
    restored_authority = ProviderTargetReceiptRetentionOperationAuthority.from_dict(
        authority.to_dict()
    )
    verify_provider_target_receipt_retention_operation_authority(
        restored_authority,
        expected_authority_id="authority.provider-target-receipt-retention",
        authority_keyring=KEYRING,
        expected_subject=restored_subject,
        at=NOW,
    )
    decision = authorize_provider_target_receipt_retention_operation(
        restored_authority,
        expected_authority_id="authority.provider-target-receipt-retention",
        authority_keyring=KEYRING,
        expected_subject=restored_subject,
        at=NOW,
    )

    assert restored_subject == subject
    assert restored_authority == authority
    assert decision.contract == RETENTION_GUARD_CONTRACT
    assert decision.allowed is True
    assert authority.digest in decision.evidence
    assert subject.digest in decision.evidence
    assert subject.to_dict()["provider_execution_allowed"] is False
    assert subject.to_dict()["retention_effect_started"] is False
    assert subject.to_dict()["primary_checkout_disjointness_verified"] is False


def test_subject_binds_receipt_inventory_and_separate_retention_lease() -> None:
    receipt = _receipt()
    execution = _execution()
    lease = _lease()
    subject = _subject(receipt=receipt, execution=execution, lease=lease)

    assert subject.source_revision == receipt.source_revision
    assert subject.receipt_sha256 == receipt.digest
    assert subject.provider_effect_lease_sha256 == receipt.lease_sha256
    assert subject.retention_inventory_sha256 == INVENTORY_SHA256
    assert subject.retention_inventory_source_sha256 == INVENTORY_SOURCE_SHA256
    assert subject.retention_execution_request_sha256 == execution.digest
    assert subject.retention_effect_lease_sha256 == lease.digest
    assert subject.provider_effect_lease_sha256 != subject.retention_effect_lease_sha256


@pytest.mark.parametrize(
    "execution,lease,match",
    [
        (
            _execution(writable_paths=(EVENT_PATH,)),
            _lease(),
            "execution_writable_paths",
        ),
        (
            _execution(),
            _lease(entrypoint_id="provider.observation-store.initialize"),
            "entrypoint_id",
        ),
        (
            _execution(egress_endpoints=("https://unexpected.invalid",)),
            _lease(),
            "unrelated effect scope",
        ),
        (
            _execution(kill_switch_ref=""),
            _lease(
                effect_scope=EffectScope(
                    read_only=False,
                    writable_paths=(EVENT_PATH, CAS_PATH),
                    kill_switch_ref="",
                )
            ),
            "requires a kill switch",
        ),
        (
            _execution(execution_id="provider-execution"),
            _lease(),
            "distinct identities",
        ),
        (
            _execution(idempotency_key="provider-idempotency"),
            _lease(),
            "must be distinct",
        ),
    ],
)
def test_scope_identity_and_bypass_substitutions_refuse(
    execution: EffectExecutionRequest,
    lease: EffectLease,
    match: str,
) -> None:
    with pytest.raises(
        ProviderTargetReceiptRetentionContractBindingError,
        match=match,
    ):
        _subject(execution=execution, lease=lease)


def test_stale_revision_and_runtime_bound_retention_lease_refuse() -> None:
    stale_provenance = dataclasses.replace(
        _lease().provenance,
        source_revision="0" * 40,
    )
    stale = _lease(provenance=stale_provenance)
    runtime_bound = _lease(
        runtime_id="runtime.retention",
        runtime_manifest_sha256="1" * 64,
        runtime_conformance_sha256="2" * 64,
        provenance=dataclasses.replace(
            _lease().provenance,
            input_digests=("c" * 64, "d" * 64, "e" * 64, "1" * 64, "2" * 64),
        ),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionContractBindingError,
        match="source_revision",
    ):
        _subject(lease=stale)
    with pytest.raises(
        ProviderTargetReceiptRetentionContractBindingError,
        match="runtime_",
    ):
        _subject(lease=runtime_bound)


@pytest.mark.parametrize(
    "event_path,cas_path",
    [
        (".", CAS_PATH),
        (EVENT_PATH, EVENT_PATH),
        ("attempt", "attempt/cas"),
        ("../outside.sqlite3", CAS_PATH),
    ],
)
def test_malformed_or_overlapping_paths_refuse(event_path: str, cas_path: str) -> None:
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        _subject(event_path=event_path, cas_path=cas_path)


@pytest.mark.parametrize("value", ["", "x", "G" * 64, None])
def test_malformed_inventory_identity_refuses(value: object) -> None:
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        _subject(inventory_sha256=value)  # type: ignore[arg-type]


def test_exact_receipt_execution_and_lease_types_refuse() -> None:
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        build_provider_target_receipt_retention_operation_subject(
            receipt=object(),  # type: ignore[arg-type]
            retention_inventory_sha256=INVENTORY_SHA256,
            retention_inventory_source_sha256=INVENTORY_SOURCE_SHA256,
            execution=_execution(),
            effect_lease=_lease(),
            event_store_scope_path=EVENT_PATH,
            receipt_cas_scope_path=CAS_PATH,
        )
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        build_provider_target_receipt_retention_operation_subject(
            receipt=_receipt(),
            retention_inventory_sha256=INVENTORY_SHA256,
            retention_inventory_source_sha256=INVENTORY_SOURCE_SHA256,
            execution=object(),  # type: ignore[arg-type]
            effect_lease=_lease(),
            event_store_scope_path=EVENT_PATH,
            receipt_cas_scope_path=CAS_PATH,
        )
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        build_provider_target_receipt_retention_operation_subject(
            receipt=_receipt(),
            retention_inventory_sha256=INVENTORY_SHA256,
            retention_inventory_source_sha256=INVENTORY_SOURCE_SHA256,
            execution=_execution(),
            effect_lease=object(),  # type: ignore[arg-type]
            event_store_scope_path=EVENT_PATH,
            receipt_cas_scope_path=CAS_PATH,
        )


def test_wire_claim_escalation_refuses() -> None:
    subject = _subject()
    for field in (
        "provider_execution_allowed",
        "retention_effect_started",
        "primary_checkout_disjointness_verified",
    ):
        payload = subject.to_dict()
        payload[field] = True
        with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
            ProviderTargetReceiptRetentionOperationSubject.from_dict(payload)


def test_signature_unknown_key_expiry_and_subject_substitution_refuse() -> None:
    subject = _subject()
    authority = _authority(subject)

    with pytest.raises(ProviderTargetReceiptRetentionContractSignatureError):
        verify_provider_target_receipt_retention_operation_authority(
            dataclasses.replace(authority, signature_sha256="0" * 64),
            expected_authority_id="authority.provider-target-receipt-retention",
            authority_keyring=KEYRING,
            expected_subject=subject,
            at=NOW,
        )
    with pytest.raises(ProviderTargetReceiptRetentionContractSignatureError):
        verify_provider_target_receipt_retention_operation_authority(
            authority,
            expected_authority_id="authority.provider-target-receipt-retention",
            authority_keyring={"other-key": SECRET},
            expected_subject=subject,
            at=NOW,
        )
    with pytest.raises(ProviderTargetReceiptRetentionContractExpired):
        verify_provider_target_receipt_retention_operation_authority(
            authority,
            expected_authority_id="authority.provider-target-receipt-retention",
            authority_keyring=KEYRING,
            expected_subject=subject,
            at=NOW + timedelta(minutes=6),
        )
    substituted = dataclasses.replace(
        subject,
        retention_inventory_sha256="0" * 64,
    )
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        verify_provider_target_receipt_retention_operation_authority(
            authority,
            expected_authority_id="authority.provider-target-receipt-retention",
            authority_keyring=KEYRING,
            expected_subject=substituted,
            at=NOW,
        )


def test_authority_ttl_and_exact_subject_type_refuse() -> None:
    subject = _subject()
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        issue_provider_target_receipt_retention_operation_authority(
            authority_id="authority.provider-target-receipt-retention",
            authority_key_id="retention-operation-key",
            authority_secret=SECRET,
            nonce="provider-target-receipt-retention-nonce",
            subject=subject,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=16),
        )
    with pytest.raises(ProviderTargetReceiptRetentionContractBindingError):
        issue_provider_target_receipt_retention_operation_authority(
            authority_id="authority.provider-target-receipt-retention",
            authority_key_id="retention-operation-key",
            authority_secret=SECRET,
            nonce="provider-target-receipt-retention-nonce",
            subject=object(),  # type: ignore[arg-type]
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )
