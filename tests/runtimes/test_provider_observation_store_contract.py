# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.runtimes.provider_observation import issue_provider_observation_authority
from daedalus.runtimes.provider_observation_store import ProviderObservationStoreTarget
from daedalus.runtimes.provider_observation_store_contract import (
    BIND_PROVIDER_START,
    INITIALIZE_STORE,
    STORE_GUARD_CONTRACT,
    ProviderObservationStoreContractBindingError,
    ProviderObservationStoreContractExpired,
    ProviderObservationStoreContractSignatureError,
    ProviderObservationStoreOperationAuthority,
    ProviderObservationStoreOperationSubject,
    authorize_provider_observation_store_operation,
    build_provider_observation_store_operation_subject,
    issue_provider_observation_store_operation_authority,
    verify_provider_observation_store_operation_authority,
)
from daedalus.schemas import ContractProvenance, EffectScope
from daedalus.spine.envelope import canonical_sha


REVISION = "4e105dc5b976aa4d3b1c8601592c5a4d08895b18"
NOW = datetime(2026, 8, 5, 0, 0, tzinfo=timezone.utc)
STORE_SECRET = b"provider-store-operation-secret-material-at-least-32-bytes"
STORE_KEYRING = {"provider-store-operation-key": STORE_SECRET}
PROVIDER_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}
RUNTIME_MANIFEST_SHA256 = "8" * 64
RUNTIME_CONFORMANCE_SHA256 = "9" * 64
PROVIDER_LEASE_SHA256 = "a" * 64
# The guarded scope path is the store path relative to the attempt root, so it
# carries no "attempt/" prefix of its own.
STORE_SCOPE_PATH = "state/provider-observation.sqlite3"


def _target(tmp_path: Path) -> ProviderObservationStoreTarget:
    primary = tmp_path / "primary"
    attempt = tmp_path / "attempt"
    state = attempt / "state"
    primary.mkdir(exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return ProviderObservationStoreTarget(
        path=str((state / "provider-observation.sqlite3").resolve()),
        attempt_root=str(attempt.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=REVISION,
    )


def _execution(operation: str) -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id=f"provider-store-{operation}",
        idempotency_key=f"provider-store-{operation}-idempotency",
        requested_effects=("filesystem_write",),
        writable_paths=(STORE_SCOPE_PATH,),
        kill_switch_ref="provider-store-kill-switch",
        kill_switch_generation=17,
    )


def _lease(operation: str, **changes) -> EffectLease:
    request_sha = "1" * 64
    policy_sha = "2" * 64
    registry_sha = "3" * 64
    values = {
        "lease_id": f"provider-store-{operation}-lease",
        "request_id": f"provider-store-{operation}-request",
        "request_sha256": request_sha,
        "policy_decision_id": f"provider-store-{operation}-policy",
        "policy_decision_sha256": policy_sha,
        "registry_sha256": registry_sha,
        "entrypoint_id": (
            "provider.observation-store.initialize"
            if operation == INITIALIZE_STORE
            else "provider.observation-store.bind-start"
        ),
        "requested_effects": ("filesystem_write",),
        "effect_scope": EffectScope(
            read_only=False,
            writable_paths=(STORE_SCOPE_PATH,),
            kill_switch_ref="provider-store-kill-switch",
        ),
        "idempotency_namespace": f"provider-store-{operation}",
        "kill_switch_generation": 17,
        "runtime_id": "",
        "runtime_manifest_sha256": None,
        "runtime_conformance_sha256": None,
        "issuer_key_id": "effect-lease-key",
        "issued_at": (NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
        "expires_at": (NOW + timedelta(minutes=30)).isoformat(timespec="microseconds"),
        "signature_sha256": "4" * 64,
        "provenance": ContractProvenance(
            origin="test.provider-store-contract",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
            input_digests=(request_sha, policy_sha, registry_sha),
            trace_id="provider-store-contract-trace",
        ),
    }
    values.update(changes)
    return EffectLease(**values)


def _provider_execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-external-execution",
        idempotency_key="provider-external-idempotency",
        requested_effects=("network_egress",),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=19,
    )


def _provider_authority(execution: EffectExecutionRequest):
    return issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=PROVIDER_SECRET,
        binding_id="provider-store-binding",
        provider_id="provider.external-fixture",
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=PROVIDER_LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=2),
        expires_at=NOW + timedelta(hours=1),
    )


def _provider_start(execution: EffectExecutionRequest) -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": PROVIDER_LEASE_SHA256,
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
        "boundary_receipt_sha256": "b" * 64,
        "started_at": (NOW - timedelta(seconds=1)).isoformat(timespec="microseconds"),
    }
    return LeasedEffectStartReceipt(
        **body,
        receipt_sha256=canonical_sha(body),
    )


def _subject(tmp_path: Path, operation: str):
    target = _target(tmp_path)
    execution = _execution(operation)
    lease = _lease(operation)
    if operation == INITIALIZE_STORE:
        subject = build_provider_observation_store_operation_subject(
            operation=operation,
            target=target,
            execution=execution,
            effect_lease=lease,
        )
        return target, execution, lease, subject
    provider_execution = _provider_execution()
    provider_authority = _provider_authority(provider_execution)
    provider_start = _provider_start(provider_execution)
    subject = build_provider_observation_store_operation_subject(
        operation=operation,
        target=target,
        execution=execution,
        effect_lease=lease,
        provider_observation_authority=provider_authority,
        provider_start_receipt=provider_start,
        runtime_manifest_sha256=RUNTIME_MANIFEST_SHA256,
        runtime_conformance_sha256=RUNTIME_CONFORMANCE_SHA256,
    )
    return target, execution, lease, subject


def _authority(subject: ProviderObservationStoreOperationSubject):
    return issue_provider_observation_store_operation_authority(
        authority_id="authority.provider-observation-store",
        authority_key_id="provider-store-operation-key",
        authority_secret=STORE_SECRET,
        nonce="provider-store-operation-nonce",
        subject=subject,
        issued_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=5),
    )


@pytest.mark.parametrize("operation", [INITIALIZE_STORE, BIND_PROVIDER_START])
def test_exact_subject_and_signed_authority_round_trip(
    tmp_path: Path,
    operation: str,
) -> None:
    _, _, _, subject = _subject(tmp_path, operation)
    authority = _authority(subject)

    restored_subject = ProviderObservationStoreOperationSubject.from_dict(
        subject.to_dict()
    )
    restored_authority = ProviderObservationStoreOperationAuthority.from_dict(
        authority.to_dict()
    )
    verify_provider_observation_store_operation_authority(
        restored_authority,
        expected_authority_id="authority.provider-observation-store",
        authority_keyring=STORE_KEYRING,
        expected_subject=restored_subject,
        at=NOW,
    )
    decision = authorize_provider_observation_store_operation(
        restored_authority,
        expected_authority_id="authority.provider-observation-store",
        authority_keyring=STORE_KEYRING,
        expected_subject=restored_subject,
        at=NOW,
    )

    assert restored_subject == subject
    assert restored_authority == authority
    assert decision.contract == STORE_GUARD_CONTRACT
    assert decision.allowed is True
    assert authority.digest in decision.evidence
    assert subject.digest in decision.evidence


def test_initialize_subject_refuses_provider_runtime_authority(tmp_path: Path) -> None:
    target = _target(tmp_path)
    execution = _execution(INITIALIZE_STORE)
    lease = _lease(INITIALIZE_STORE)

    with pytest.raises(ProviderObservationStoreContractBindingError):
        build_provider_observation_store_operation_subject(
            operation=INITIALIZE_STORE,
            target=target,
            execution=execution,
            effect_lease=lease,
            runtime_manifest_sha256=RUNTIME_MANIFEST_SHA256,
        )


def test_bind_subject_requires_complete_provider_runtime_authority(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    execution = _execution(BIND_PROVIDER_START)
    lease = _lease(BIND_PROVIDER_START)

    with pytest.raises(ProviderObservationStoreContractBindingError):
        build_provider_observation_store_operation_subject(
            operation=BIND_PROVIDER_START,
            target=target,
            execution=execution,
            effect_lease=lease,
        )


def test_stale_store_lease_revision_and_wrong_entrypoint_refuse(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    execution = _execution(INITIALIZE_STORE)
    stale_provenance = dataclasses.replace(
        _lease(INITIALIZE_STORE).provenance,
        source_revision="c" * 40,
    )
    stale = _lease(INITIALIZE_STORE, provenance=stale_provenance)
    wrong_entrypoint = _lease(
        INITIALIZE_STORE,
        entrypoint_id="provider.observation-store.bind-start",
    )

    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="source_revision",
    ):
        build_provider_observation_store_operation_subject(
            operation=INITIALIZE_STORE,
            target=target,
            execution=execution,
            effect_lease=stale,
        )
    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="entrypoint_id",
    ):
        build_provider_observation_store_operation_subject(
            operation=INITIALIZE_STORE,
            target=target,
            execution=execution,
            effect_lease=wrong_entrypoint,
        )


def test_store_write_execution_refuses_unrelated_scope(tmp_path: Path) -> None:
    target = _target(tmp_path)
    execution = dataclasses.replace(
        _execution(INITIALIZE_STORE),
        egress_endpoints=("https://unexpected.invalid",),
    )

    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="unrelated effect scope",
    ):
        build_provider_observation_store_operation_subject(
            operation=INITIALIZE_STORE,
            target=target,
            execution=execution,
            effect_lease=_lease(INITIALIZE_STORE),
        )


def test_tampered_provider_start_receipt_refuses(tmp_path: Path) -> None:
    target = _target(tmp_path)
    provider_execution = _provider_execution()
    authority = _provider_authority(provider_execution)
    start = dataclasses.replace(
        _provider_start(provider_execution),
        receipt_sha256="d" * 64,
    )

    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="digest mismatch",
    ):
        build_provider_observation_store_operation_subject(
            operation=BIND_PROVIDER_START,
            target=target,
            execution=_execution(BIND_PROVIDER_START),
            effect_lease=_lease(BIND_PROVIDER_START),
            provider_observation_authority=authority,
            provider_start_receipt=start,
            runtime_manifest_sha256=RUNTIME_MANIFEST_SHA256,
            runtime_conformance_sha256=RUNTIME_CONFORMANCE_SHA256,
        )


def test_provider_start_and_observation_authority_mismatch_refuses(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    provider_execution = _provider_execution()
    authority = _provider_authority(provider_execution)
    other_execution = dataclasses.replace(
        provider_execution,
        execution_id="provider-other-execution",
    )

    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="execution_id",
    ):
        build_provider_observation_store_operation_subject(
            operation=BIND_PROVIDER_START,
            target=target,
            execution=_execution(BIND_PROVIDER_START),
            effect_lease=_lease(BIND_PROVIDER_START),
            provider_observation_authority=authority,
            provider_start_receipt=_provider_start(other_execution),
            runtime_manifest_sha256=RUNTIME_MANIFEST_SHA256,
            runtime_conformance_sha256=RUNTIME_CONFORMANCE_SHA256,
        )


def test_signature_expiry_and_expected_subject_substitution_refuse(
    tmp_path: Path,
) -> None:
    _, _, _, subject = _subject(tmp_path, INITIALIZE_STORE)
    authority = _authority(subject)

    with pytest.raises(ProviderObservationStoreContractSignatureError):
        verify_provider_observation_store_operation_authority(
            dataclasses.replace(authority, signature_sha256="e" * 64),
            expected_authority_id="authority.provider-observation-store",
            authority_keyring=STORE_KEYRING,
            expected_subject=subject,
            at=NOW,
        )
    with pytest.raises(ProviderObservationStoreContractExpired):
        verify_provider_observation_store_operation_authority(
            authority,
            expected_authority_id="authority.provider-observation-store",
            authority_keyring=STORE_KEYRING,
            expected_subject=subject,
            at=NOW + timedelta(minutes=6),
        )
    changed = dataclasses.replace(
        subject,
        store_idempotency_key="provider-store-substituted-idempotency",
    )
    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="subject",
    ):
        verify_provider_observation_store_operation_authority(
            authority,
            expected_authority_id="authority.provider-observation-store",
            authority_keyring=STORE_KEYRING,
            expected_subject=changed,
            at=NOW,
        )


def test_exact_parser_and_short_ttl_are_fail_closed(tmp_path: Path) -> None:
    _, _, _, subject = _subject(tmp_path, INITIALIZE_STORE)
    payload = subject.to_dict()
    payload["unexpected"] = True
    with pytest.raises(ProviderObservationStoreContractBindingError):
        ProviderObservationStoreOperationSubject.from_dict(payload)

    authority = _authority(subject)
    payload = authority.to_dict()
    del payload["nonce"]
    with pytest.raises(ProviderObservationStoreContractBindingError):
        ProviderObservationStoreOperationAuthority.from_dict(payload)

    with pytest.raises(
        ProviderObservationStoreContractBindingError,
        match="TTL",
    ):
        issue_provider_observation_store_operation_authority(
            authority_id="authority.provider-observation-store",
            authority_key_id="provider-store-operation-key",
            authority_secret=STORE_SECRET,
            nonce="provider-store-operation-long-ttl",
            subject=subject,
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=16),
        )


def test_malformed_keyring_is_contained(tmp_path: Path) -> None:
    _, _, _, subject = _subject(tmp_path, INITIALIZE_STORE)
    authority = _authority(subject)

    with pytest.raises(ProviderObservationStoreContractBindingError):
        verify_provider_observation_store_operation_authority(
            authority,
            expected_authority_id="authority.provider-observation-store",
            authority_keyring={"provider-store-operation-key": b"short"},
            expected_subject=subject,
            at=NOW,
        )
