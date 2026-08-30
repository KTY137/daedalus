# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderAdapterDescriptor,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider_invocation_resolution import (
    ProviderInvocationResolutionAuthenticationError,
    ProviderInvocationResolutionBindingError,
    ProviderInvocationResolutionReceipt,
    resolve_provider_invocation_authority,
    verify_provider_invocation_resolution_receipt,
)
from daedalus.runtimes.provider_observation import issue_provider_observation_authority


REVISION = "f2c7de5c65ba49f3a6de11dd1d5a26f89fa49f7b"
NOW = datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc)
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-resolution-execution",
        idempotency_key="provider-resolution-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=11,
    )


def _descriptor(**changes: str) -> ProviderAdapterDescriptor:
    values = {
        "provider_id": "provider.external-fixture",
        "adapter_id": "adapter.external-fixture",
        "implementation_id": "implementation.external-fixture-v1",
        "adapter_artifact_sha256": "2" * 64,
        "adapter_config_sha256": "3" * 64,
        "entrypoint_id": "provider.runtime-fixture",
        "runtime_id": "runtime-fixture",
        "source_revision": REVISION,
    }
    values.update(changes)
    return ProviderAdapterDescriptor(**values)


def _manifest(descriptor: ProviderAdapterDescriptor | None = None):
    return build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=(descriptor or _descriptor(),),
    )


def _subject(
    execution: EffectExecutionRequest,
    **changes: str,
) -> ProviderInvocationSubject:
    values = {
        "provider_id": "provider.external-fixture",
        "adapter_id": "adapter.external-fixture",
        "adapter_artifact_sha256": "2" * 64,
        "adapter_config_sha256": "3" * 64,
        "entrypoint_id": "provider.runtime-fixture",
        "runtime_id": "runtime-fixture",
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
        "lease_sha256": LEASE_SHA256,
        "source_revision": REVISION,
    }
    values.update(changes)
    return ProviderInvocationSubject(**values)


def _authority(
    execution: EffectExecutionRequest,
    *,
    manifest=None,
    subject: ProviderInvocationSubject | None = None,
) -> ProviderInvocationObservationAuthority:
    registry = manifest or _manifest()
    invocation = subject or _subject(execution)
    observation = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-resolution-binding",
        provider_id=invocation.provider_id,
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id=invocation.entrypoint_id,
        runtime_id=invocation.runtime_id,
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    return issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=invocation,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=registry.digest,
        authority_secret=AUTHORITY_SECRET,
    )


def _resolve(
    authority: ProviderInvocationObservationAuthority,
    manifest,
    execution: EffectExecutionRequest,
    *,
    at: datetime = NOW,
    source_revision: str = REVISION,
):
    return resolve_provider_invocation_authority(
        authority,
        manifest,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        invocation_contract_id="provider-invocation-contract",
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=source_revision,
        at=at,
    )


def _verify_receipt(
    receipt: ProviderInvocationResolutionReceipt,
    authority: ProviderInvocationObservationAuthority,
    manifest,
    execution: EffectExecutionRequest,
    *,
    at: datetime = NOW,
) -> None:
    verify_provider_invocation_resolution_receipt(
        receipt,
        authority,
        manifest,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        invocation_contract_id="provider-invocation-contract",
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        at=at,
    )


def test_exact_resolution_emits_round_trippable_receipt() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)

    receipt = _resolve(authority, manifest, execution)
    restored = ProviderInvocationResolutionReceipt.from_dict(receipt.to_dict())
    _verify_receipt(restored, authority, manifest, execution)

    assert restored == receipt
    assert receipt.registry_sha256 == manifest.digest
    assert receipt.authority_sha256 == authority.digest
    assert receipt.invocation_subject_sha256 == authority.invocation_subject.digest
    assert receipt.descriptor_sha256 == manifest.descriptors[0].digest
    assert receipt.implementation_id == "implementation.external-fixture-v1"
    assert receipt.digest == receipt.receipt_sha256


def test_changed_registry_manifest_cannot_satisfy_signed_authority() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)
    changed = _manifest(
        dataclasses.replace(
            manifest.descriptors[0],
            implementation_id="implementation.external-fixture-v2",
        )
    )

    with pytest.raises(
        ProviderInvocationResolutionBindingError,
        match="registry digest",
    ):
        _resolve(authority, changed, execution)


def test_valid_signed_subject_that_does_not_resolve_is_refused() -> None:
    execution = _execution()
    manifest = _manifest()
    foreign_subject = _subject(execution, adapter_id="adapter.foreign")
    authority = _authority(
        execution,
        manifest=manifest,
        subject=foreign_subject,
    )

    with pytest.raises(
        ProviderInvocationResolutionBindingError,
        match="did not resolve",
    ):
        _resolve(authority, manifest, execution)


def test_composite_signature_or_nested_authority_tamper_is_authentication_error() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)
    tampered = dataclasses.replace(authority, signature_sha256="0" * 64)

    with pytest.raises(ProviderInvocationResolutionAuthenticationError):
        _resolve(tampered, manifest, execution)

    nested = dataclasses.replace(
        authority.observation_authority,
        signature_sha256="0" * 64,
    )
    tampered_nested = dataclasses.replace(
        authority,
        observation_authority=nested,
    )
    with pytest.raises(ProviderInvocationResolutionAuthenticationError):
        _resolve(tampered_nested, manifest, execution)


def test_stale_revision_and_wrong_execution_are_refused() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)

    with pytest.raises(ProviderInvocationResolutionBindingError):
        _resolve(authority, manifest, execution, source_revision="4" * 40)

    other = dataclasses.replace(
        execution,
        execution_id="provider-resolution-other-execution",
    )
    with pytest.raises(ProviderInvocationResolutionAuthenticationError):
        _resolve(authority, manifest, other)


def test_naive_or_non_datetime_verification_time_is_refused() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)

    with pytest.raises(ProviderInvocationResolutionBindingError):
        _resolve(authority, manifest, execution, at=NOW.replace(tzinfo=None))
    with pytest.raises(ProviderInvocationResolutionBindingError):
        _resolve(authority, manifest, execution, at="2026-08-04T23:00:00Z")


def test_receipt_digest_and_exact_shape_are_fail_closed() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)
    receipt = _resolve(authority, manifest, execution)

    with pytest.raises(ProviderInvocationResolutionBindingError, match="digest"):
        dataclasses.replace(receipt, implementation_id="implementation.tampered")

    payload = receipt.to_dict()
    payload["unexpected"] = True
    with pytest.raises(ProviderInvocationResolutionBindingError):
        ProviderInvocationResolutionReceipt.from_dict(payload)

    payload = receipt.to_dict()
    del payload["descriptor_sha256"]
    with pytest.raises(ProviderInvocationResolutionBindingError):
        ProviderInvocationResolutionReceipt.from_dict(payload)


def test_receipt_verifier_reauthenticates_authority_and_registry() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)
    receipt = _resolve(authority, manifest, execution)

    changed_authority = dataclasses.replace(
        authority,
        invocation_registry_sha256="5" * 64,
    )
    with pytest.raises(
        ProviderInvocationResolutionBindingError,
        match="registry digest",
    ):
        _verify_receipt(receipt, changed_authority, manifest, execution)

    tampered_signature = dataclasses.replace(
        authority,
        signature_sha256="0" * 64,
    )
    with pytest.raises(ProviderInvocationResolutionAuthenticationError):
        _verify_receipt(receipt, tampered_signature, manifest, execution)


def test_receipt_verification_time_is_part_of_exact_subject() -> None:
    execution = _execution()
    manifest = _manifest()
    authority = _authority(execution, manifest=manifest)
    receipt = _resolve(authority, manifest, execution)

    with pytest.raises(
        ProviderInvocationResolutionBindingError,
        match="subject mismatch",
    ):
        _verify_receipt(
            receipt,
            authority,
            manifest,
            execution,
            at=NOW + timedelta(microseconds=1),
        )
