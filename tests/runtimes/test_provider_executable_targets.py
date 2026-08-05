from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetBindingError,
    ProviderExecutableTargetDescriptor,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
    ProviderExecutableTargetShapeError,
    build_provider_executable_target_manifest,
    project_provider_executable_targets,
)
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderAdapterDescriptor,
    ProviderInvocationRegistryManifest,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider_observation import (
    issue_provider_observation_authority,
)


NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
REVISION = "62be3829e44eebe2d07fe7fc578c8ed59bb0a710"
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-target-execution",
        idempotency_key="provider-target-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=9,
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


def _identity_descriptor(**changes: str) -> ProviderAdapterDescriptor:
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


def _identity_registry(
    descriptor: ProviderAdapterDescriptor | None = None,
) -> ProviderInvocationRegistryManifest:
    return build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=(descriptor or _identity_descriptor(),),
    )


def _authority(
    execution: EffectExecutionRequest,
    registry: ProviderInvocationRegistryManifest,
) -> ProviderInvocationObservationAuthority:
    observation = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-target-binding",
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
    return issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=_subject(execution),
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=registry.digest,
        authority_secret=AUTHORITY_SECRET,
    )


def _target_descriptor(
    identity: ProviderAdapterDescriptor | None = None,
    **changes: str,
) -> ProviderExecutableTargetDescriptor:
    identity = identity or _identity_descriptor()
    values = {
        "provider_id": identity.provider_id,
        "adapter_id": identity.adapter_id,
        "implementation_id": identity.implementation_id,
        "entrypoint_id": identity.entrypoint_id,
        "runtime_id": identity.runtime_id,
        "source_revision": identity.source_revision,
        "identity_descriptor_sha256": identity.digest,
        "adapter_artifact_sha256": identity.adapter_artifact_sha256,
        "adapter_config_sha256": identity.adapter_config_sha256,
        "invoke_target": "daedalus.runtimes.adapters.fixture:FixtureAdapter.invoke",
        "invoke_source_sha256": "4" * 64,
        "output_digests_target": (
            "daedalus.runtimes.adapters.fixture:FixtureAdapter.output_digests"
        ),
        "output_digests_source_sha256": "4" * 64,
    }
    values.update(changes)
    return ProviderExecutableTargetDescriptor(**values)


def _manifest(
    registry: ProviderInvocationRegistryManifest,
    descriptor: ProviderExecutableTargetDescriptor | None = None,
    *,
    source_revision: str = REVISION,
    identity_registry_sha256: str | None = None,
) -> ProviderExecutableTargetManifest:
    return build_provider_executable_target_manifest(
        manifest_id="provider-executable-targets",
        source_revision=source_revision,
        identity_registry_sha256=identity_registry_sha256 or registry.digest,
        descriptors=(descriptor or _target_descriptor(registry.descriptors[0]),),
    )


def _project(
    authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
) -> ProviderExecutableTargetProjection:
    return project_provider_executable_targets(
        authority,
        registry,
        execution,
        manifest,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )


def test_authenticated_target_projection_round_trips_without_execution_authority() -> None:
    execution = _execution()
    registry = _identity_registry()
    manifest = _manifest(registry)
    projection = _project(_authority(execution, registry), registry, execution, manifest)

    restored = ProviderExecutableTargetProjection.from_dict(projection.to_dict())

    assert restored == projection
    assert restored.digest == projection.digest
    assert restored.identity_registry_sha256 == registry.digest
    assert restored.identity_descriptor_sha256 == registry.descriptors[0].digest
    assert restored.target_manifest_sha256 == manifest.digest
    assert restored.target_descriptor_sha256 == manifest.descriptors[0].digest
    assert restored.to_dict()["targets_structurally_verified"] is False
    assert restored.to_dict()["provider_execution_allowed"] is False
    assert not hasattr(restored, "invoke")
    assert not hasattr(restored, "output_digests")


def test_invalid_invocation_signature_refuses_before_target_lookup(monkeypatch) -> None:
    execution = _execution()
    registry = _identity_registry()
    authority = dataclasses.replace(
        _authority(execution, registry),
        signature_sha256="f" * 64,
    )
    manifest = _manifest(registry)

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before invocation authentication")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="did not authenticate",
    ):
        _project(authority, registry, execution, manifest)


def test_target_manifest_registry_substitution_refuses_before_descriptor_lookup(
    monkeypatch,
) -> None:
    execution = _execution()
    registry = _identity_registry()
    manifest = _manifest(registry, identity_registry_sha256="9" * 64)

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before registry binding")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="identity registry mismatch",
    ):
        _project(_authority(execution, registry), registry, execution, manifest)


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider_id", "provider.foreign"),
        ("adapter_id", "adapter.foreign"),
        ("implementation_id", "implementation.foreign"),
        ("entrypoint_id", "provider.foreign-entrypoint"),
        ("runtime_id", "runtime-foreign"),
        ("identity_descriptor_sha256", "5" * 64),
        ("adapter_artifact_sha256", "6" * 64),
        ("adapter_config_sha256", "7" * 64),
    ],
)
def test_authenticated_identity_and_target_descriptor_substitution_refuses(
    field: str,
    value: str,
) -> None:
    execution = _execution()
    registry = _identity_registry()
    descriptor = _target_descriptor(**{field: value})
    manifest = _manifest(registry, descriptor)

    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="differs from authenticated identity",
    ):
        _project(_authority(execution, registry), registry, execution, manifest)


def test_stale_target_revision_refuses_before_target_lookup(monkeypatch) -> None:
    execution = _execution()
    registry = _identity_registry()
    stale_revision = "a" * 40
    stale_descriptor = _target_descriptor(source_revision=stale_revision)
    manifest = _manifest(
        registry,
        stale_descriptor,
        source_revision=stale_revision,
    )

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before revision binding")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="source revision mismatch",
    ):
        _project(_authority(execution, registry), registry, execution, manifest)


@pytest.mark.parametrize(
    "target",
    [
        "os:system",
        "daedalus.runtimes.fixture",
        "daedalus.runtimes.fixture:",
        "daedalus..fixture:invoke",
        "daedalus.runtimes.Fixture:invoke",
        "daedalus.runtimes.fixture:invoke()",
        "daedalus.runtimes.fixture:invoke;system",
        " daedalus.runtimes.fixture:invoke",
    ],
)
def test_target_grammar_refuses_noncanonical_or_external_targets(target: str) -> None:
    with pytest.raises(
        ProviderExecutableTargetShapeError,
        match="canonical Daedalus Python target",
    ):
        _target_descriptor(invoke_target=target)


def test_manifest_refuses_duplicate_providers_and_descriptor_digests() -> None:
    registry = _identity_registry()
    first = _target_descriptor()
    second = dataclasses.replace(
        first,
        implementation_id="implementation.external-fixture-v2",
        invoke_target="daedalus.runtimes.adapters.fixture:FixtureAdapter.invoke_v2",
    )
    with pytest.raises(
        ProviderExecutableTargetShapeError,
        match="provider IDs must be unique",
    ):
        build_provider_executable_target_manifest(
            manifest_id="provider-executable-targets",
            source_revision=REVISION,
            identity_registry_sha256=registry.digest,
            descriptors=(first, second),
        )


def test_manifest_and_projection_wire_fields_are_exact() -> None:
    execution = _execution()
    registry = _identity_registry()
    manifest = _manifest(registry)
    projection = _project(_authority(execution, registry), registry, execution, manifest)

    manifest_payload = manifest.to_dict()
    manifest_payload["extra"] = True
    with pytest.raises(ProviderExecutableTargetShapeError, match="fields are not exact"):
        ProviderExecutableTargetManifest.from_dict(manifest_payload)

    projection_payload = projection.to_dict()
    projection_payload["extra"] = True
    with pytest.raises(ProviderExecutableTargetShapeError, match="fields are not exact"):
        ProviderExecutableTargetProjection.from_dict(projection_payload)


@pytest.mark.parametrize(
    "field",
    ["targets_structurally_verified", "provider_execution_allowed"],
)
def test_projection_wire_cannot_escalate_authority(field: str) -> None:
    execution = _execution()
    registry = _identity_registry()
    manifest = _manifest(registry)
    payload = _project(
        _authority(execution, registry),
        registry,
        execution,
        manifest,
    ).to_dict()
    payload[field] = True

    with pytest.raises(ProviderExecutableTargetShapeError):
        ProviderExecutableTargetProjection.from_dict(payload)


def test_exact_target_manifest_type_is_required() -> None:
    execution = _execution()
    registry = _identity_registry()
    manifest = _manifest(registry)

    class ManifestSubclass(ProviderExecutableTargetManifest):
        pass

    subclass = ManifestSubclass(
        manifest_id=manifest.manifest_id,
        source_revision=manifest.source_revision,
        identity_registry_sha256=manifest.identity_registry_sha256,
        descriptors=manifest.descriptors,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="manifest must be exact",
    ):
        _project(_authority(execution, registry), registry, execution, subclass)
