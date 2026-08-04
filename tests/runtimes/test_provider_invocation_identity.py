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
from daedalus.runtimes.provider_invocation_identity import (
    ProviderInvocationIdentityAuthenticationError,
    ProviderInvocationIdentityBindingError,
    ProviderInvocationIdentityProjection,
    project_provider_invocation_identity,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderAdapterDescriptor,
    ProviderInvocationRegistryManifest,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider_observation import (
    issue_provider_observation_authority,
)


NOW = datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc)
REVISION = "f2c7de5c65ba49f3a6de11dd1d5a26f89fa49f7b"
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-invocation-execution",
        idempotency_key="provider-invocation-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=7,
    )


def _subject(execution: EffectExecutionRequest) -> ProviderInvocationSubject:
    return ProviderInvocationSubject(
        provider_id="provider.external-fixture",
        adapter_id="adapter.external-fixture",
        adapter_artifact_sha256="2" * 64,
        adapter_config_sha256="3" * 64,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
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


def _registry(
    descriptor: ProviderAdapterDescriptor | None = None,
) -> ProviderInvocationRegistryManifest:
    return build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=(descriptor or _descriptor(),),
    )


def _observation(execution: EffectExecutionRequest):
    return issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-invocation-binding",
        provider_id="provider.external-fixture",
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _authority(
    execution: EffectExecutionRequest,
    registry: ProviderInvocationRegistryManifest,
    *,
    contract_id: str = "provider-invocation-contract",
) -> ProviderInvocationObservationAuthority:
    return issue_provider_invocation_observation_authority(
        observation_authority=_observation(execution),
        invocation_subject=_subject(execution),
        invocation_contract_id=contract_id,
        invocation_registry_sha256=registry.digest,
        authority_secret=AUTHORITY_SECRET,
    )


def _project(
    authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
) -> ProviderInvocationIdentityProjection:
    return project_provider_invocation_identity(
        authority,
        registry,
        execution,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )


def test_exact_identity_projection_round_trips_without_execution_authority() -> None:
    execution = _execution()
    registry = _registry()
    authority = _authority(execution, registry)

    projection = _project(authority, registry, execution)
    restored = ProviderInvocationIdentityProjection.from_dict(
        projection.to_dict()
    )

    assert restored == projection
    assert restored.digest == projection.digest
    assert restored.provider_id == "provider.external-fixture"
    assert restored.adapter_id == "adapter.external-fixture"
    assert restored.implementation_id == "implementation.external-fixture-v1"
    assert restored.authority_sha256 == authority.digest
    assert restored.observation_authority_sha256 == (
        authority.observation_authority.digest
    )
    assert restored.invocation_contract_sha256 == (
        authority.invocation_contract_sha256
    )
    assert restored.registry_sha256 == registry.digest
    assert restored.descriptor_sha256 == registry.descriptors[0].digest
    assert restored.execution_request_sha256 == execution.digest
    assert restored.to_dict()["runtime_effect_authorized"] is False
    assert restored.to_dict()["provider_execution_allowed"] is False
    assert not hasattr(restored, "invoke")
    assert not hasattr(restored, "execute")


def test_registry_implementation_substitution_refuses_before_resolution_laundering() -> None:
    execution = _execution()
    registry = _registry()
    authority = _authority(execution, registry)
    substituted = _registry(
        _descriptor(implementation_id="implementation.foreign-v2")
    )

    with pytest.raises(
        ProviderInvocationIdentityAuthenticationError,
        match="did not authenticate",
    ):
        _project(authority, substituted, execution)


def test_signed_registry_with_subject_descriptor_mismatch_refuses_exact_resolution() -> None:
    execution = _execution()
    mismatched = _registry(_descriptor(adapter_id="adapter.foreign"))
    authority = _authority(execution, mismatched)

    with pytest.raises(
        ProviderInvocationIdentityBindingError,
        match="did not resolve exactly",
    ):
        _project(authority, mismatched, execution)


def test_foreign_invocation_contract_refuses_even_when_signed() -> None:
    execution = _execution()
    registry = _registry()
    authority = _authority(
        execution,
        registry,
        contract_id="provider-invocation-foreign-contract",
    )

    with pytest.raises(
        ProviderInvocationIdentityAuthenticationError,
        match="did not authenticate",
    ):
        _project(authority, registry, execution)


def test_stale_execution_refuses_authenticated_projection() -> None:
    execution = _execution()
    registry = _registry()
    authority = _authority(execution, registry)
    stale = dataclasses.replace(
        execution,
        execution_id="provider-invocation-stale-execution",
    )

    with pytest.raises(
        ProviderInvocationIdentityAuthenticationError,
        match="did not authenticate",
    ):
        _project(authority, registry, stale)


def test_invalid_composite_signature_refuses_before_registry_resolution(
    monkeypatch,
) -> None:
    execution = _execution()
    registry = _registry()
    authority = dataclasses.replace(
        _authority(execution, registry),
        signature_sha256="f" * 64,
    )

    def forbidden_resolution(self, subject):
        raise AssertionError("registry resolution ran before authentication")

    monkeypatch.setattr(
        ProviderInvocationRegistryManifest,
        "resolve",
        forbidden_resolution,
    )
    with pytest.raises(
        ProviderInvocationIdentityAuthenticationError,
        match="did not authenticate",
    ):
        _project(authority, registry, execution)


@pytest.mark.parametrize(
    "field,value",
    [
        ("runtime_effect_authorized", True),
        ("provider_execution_allowed", True),
        ("schema", "daedalus-provider-invocation-identity/2"),
    ],
)
def test_projection_wire_cannot_escalate_authority(
    field: str,
    value,
) -> None:
    execution = _execution()
    registry = _registry()
    payload = _project(
        _authority(execution, registry),
        registry,
        execution,
    ).to_dict()
    payload[field] = value
    with pytest.raises(ProviderInvocationIdentityBindingError):
        ProviderInvocationIdentityProjection.from_dict(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"schema": "daedalus-provider-invocation-identity/1"},
    ],
)
def test_projection_wire_fields_are_exact(payload) -> None:
    with pytest.raises(
        ProviderInvocationIdentityBindingError,
        match="fields are not exact",
    ):
        ProviderInvocationIdentityProjection.from_dict(payload)


def test_exact_authority_registry_and_execution_types_are_required() -> None:
    execution = _execution()
    registry = _registry()
    authority = _authority(execution, registry)

    class AuthoritySubclass(ProviderInvocationObservationAuthority):
        pass

    class RegistrySubclass(ProviderInvocationRegistryManifest):
        pass

    class ExecutionSubclass(EffectExecutionRequest):
        pass

    with pytest.raises(ProviderInvocationIdentityBindingError, match="authority"):
        _project(
            AuthoritySubclass(
                observation_authority=authority.observation_authority,
                invocation_subject=authority.invocation_subject,
                invocation_contract_id=authority.invocation_contract_id,
                invocation_registry_sha256=authority.invocation_registry_sha256,
                signature_sha256=authority.signature_sha256,
            ),
            registry,
            execution,
        )
    with pytest.raises(ProviderInvocationIdentityBindingError, match="registry"):
        _project(
            authority,
            RegistrySubclass(
                registry_id=registry.registry_id,
                source_revision=registry.source_revision,
                descriptors=registry.descriptors,
            ),
            execution,
        )
    with pytest.raises(ProviderInvocationIdentityBindingError, match="execution"):
        _project(
            authority,
            registry,
            ExecutionSubclass(**dataclasses.asdict(execution)),
        )
