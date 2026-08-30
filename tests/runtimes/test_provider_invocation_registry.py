# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationAuthorityBindingError,
    issue_provider_invocation_observation_authority,
    verify_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderAdapterDescriptor,
    ProviderInvocationRegistryManifest,
    ProviderInvocationRegistryResolutionError,
    ProviderInvocationRegistryShapeError,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider_observation import (
    issue_provider_observation_authority,
)


REVISION = "2eee927a49ee3c75efc2e1392691b81095ed72db"
NOW = datetime(2026, 8, 4, 22, 30, tzinfo=timezone.utc)
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _descriptor(
    provider_id: str = "provider.external-fixture",
    **changes: str,
) -> ProviderAdapterDescriptor:
    values = {
        "provider_id": provider_id,
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


def _manifest(*descriptors: ProviderAdapterDescriptor):
    rows = descriptors or (_descriptor(),)
    return build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=rows,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-registry-execution",
        idempotency_key="provider-registry-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=9,
    )


def _subject(execution: EffectExecutionRequest, **changes: str):
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


def test_manifest_build_round_trip_and_exact_resolution() -> None:
    second = _descriptor(
        "provider.second",
        adapter_id="adapter.second",
        implementation_id="implementation.second-v1",
        adapter_artifact_sha256="4" * 64,
        adapter_config_sha256="5" * 64,
    )
    first = _descriptor()
    manifest = _manifest(second, first)
    restored = ProviderInvocationRegistryManifest.from_dict(manifest.to_dict())

    assert tuple(row.provider_id for row in manifest.descriptors) == (
        "provider.external-fixture",
        "provider.second",
    )
    assert restored == manifest
    assert restored.digest == manifest.digest
    assert manifest.resolve(_subject(_execution())) == first
    assert manifest.descriptor_for_provider("provider.second") == second


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_id", "adapter.foreign"),
        ("adapter_artifact_sha256", "6" * 64),
        ("adapter_config_sha256", "7" * 64),
        ("entrypoint_id", "provider.foreign-entrypoint"),
        ("runtime_id", "runtime-foreign"),
        ("source_revision", "8" * 40),
    ],
)
def test_subject_descriptor_substitution_refuses(field: str, value: str) -> None:
    manifest = _manifest()
    subject = _subject(_execution(), **{field: value})

    with pytest.raises(
        ProviderInvocationRegistryResolutionError,
        match=field,
    ):
        manifest.resolve(subject)


def test_provider_lookup_is_unique_and_unknown_provider_refuses() -> None:
    manifest = _manifest()

    with pytest.raises(ProviderInvocationRegistryResolutionError):
        manifest.descriptor_for_provider("provider.unknown")
    with pytest.raises(ProviderInvocationRegistryResolutionError):
        manifest.resolve(
            _subject(_execution(), provider_id="provider.unknown")
        )


def test_direct_manifest_requires_canonical_order_and_unique_provider_ids() -> None:
    first = _descriptor()
    second = _descriptor(
        "provider.second",
        adapter_id="adapter.second",
        implementation_id="implementation.second-v1",
        adapter_artifact_sha256="4" * 64,
        adapter_config_sha256="5" * 64,
    )

    with pytest.raises(ProviderInvocationRegistryShapeError, match="ordered"):
        ProviderInvocationRegistryManifest(
            registry_id="provider-invocation-registry",
            source_revision=REVISION,
            descriptors=(second, first),
        )
    with pytest.raises(ProviderInvocationRegistryShapeError, match="unique"):
        ProviderInvocationRegistryManifest(
            registry_id="provider-invocation-registry",
            source_revision=REVISION,
            descriptors=(first, dataclasses.replace(first, adapter_id="adapter.duplicate")),
        )


def test_descriptor_revision_must_match_manifest_revision() -> None:
    stale = _descriptor(source_revision="9" * 40)

    with pytest.raises(
        ProviderInvocationRegistryShapeError,
        match="source revision mismatch",
    ):
        build_provider_invocation_registry_manifest(
            registry_id="provider-invocation-registry",
            source_revision=REVISION,
            descriptors=(stale,),
        )


def test_implementation_identity_is_bound_into_registry_digest() -> None:
    manifest = _manifest()
    changed = _manifest(
        dataclasses.replace(
            manifest.descriptors[0],
            implementation_id="implementation.external-fixture-v2",
        )
    )

    assert changed.digest != manifest.digest
    assert changed.descriptors[0].implementation_id.endswith("v2")


def test_exact_manifest_shape_and_descriptor_shape_are_required() -> None:
    manifest = _manifest()
    payload = manifest.to_dict()
    payload["unexpected"] = True
    with pytest.raises(ProviderInvocationRegistryShapeError):
        ProviderInvocationRegistryManifest.from_dict(payload)

    payload = manifest.to_dict()
    del payload["descriptors"][0]["implementation_id"]
    with pytest.raises(ProviderInvocationRegistryShapeError):
        ProviderInvocationRegistryManifest.from_dict(payload)


def test_builder_refuses_strings_mappings_and_non_descriptor_rows() -> None:
    for rows in ("descriptor", b"descriptor", {"provider": "descriptor"}, [object()]):
        with pytest.raises(ProviderInvocationRegistryShapeError):
            build_provider_invocation_registry_manifest(
                registry_id="provider-invocation-registry",
                source_revision=REVISION,
                descriptors=rows,
            )


def test_signed_composite_binds_exact_registry_manifest_digest() -> None:
    execution = _execution()
    subject = _subject(execution)
    manifest = _manifest()
    observation = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-registry-binding",
        provider_id=subject.provider_id,
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    authority = issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=subject,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=manifest.digest,
        authority_secret=AUTHORITY_SECRET,
    )

    verify_provider_invocation_observation_authority(
        authority,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        invocation_subject=subject,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=manifest.digest,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        at=NOW,
    )
    assert manifest.resolve(subject).implementation_id == (
        "implementation.external-fixture-v1"
    )

    changed = _manifest(
        dataclasses.replace(
            manifest.descriptors[0],
            implementation_id="implementation.external-fixture-v2",
        )
    )
    with pytest.raises(ProviderInvocationAuthorityBindingError):
        verify_provider_invocation_observation_authority(
            authority,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            invocation_subject=subject,
            invocation_contract_id="provider-invocation-contract",
            invocation_registry_sha256=changed.digest,
            entrypoint_id=subject.entrypoint_id,
            runtime_id=subject.runtime_id,
            execution=execution,
            lease_sha256=LEASE_SHA256,
            source_revision=REVISION,
            at=NOW,
        )
