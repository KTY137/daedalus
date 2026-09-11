from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider.executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetBindingError,
    ProviderExecutableTargetDescriptor,
    ProviderExecutableTargetManifest,
    ProviderExecutableTargetProjection,
    ProviderExecutableTargetShapeError,
    ProviderExecutableTargetSignatureError,
    build_provider_executable_target_manifest,
    issue_provider_executable_target_authority,
    project_provider_executable_targets,
)
from daedalus.runtimes.provider.invocation import ProviderInvocationSubject
from daedalus.runtimes.provider.invocation_authority import (
    ProviderInvocationObservationAuthority,
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider.invocation_registry import (
    ProviderAdapterDescriptor,
    ProviderInvocationRegistryManifest,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider.observation import (
    issue_provider_observation_authority,
)


NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
REVISION = "62be3829e44eebe2d07fe7fc578c8ed59bb0a710"
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}
TARGET_CONTRACT_ID = "provider-executable-target-contract"


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


def _target_authority(
    authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str = TARGET_CONTRACT_ID,
) -> ProviderExecutableTargetAuthority:
    return issue_provider_executable_target_authority(
        authority,
        registry,
        execution,
        manifest,
        target_contract_id=target_contract_id,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        authority_secret=AUTHORITY_SECRET,
        at=NOW,
    )


def _project(
    target_authority: ProviderExecutableTargetAuthority,
    authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
    *,
    target_contract_id: str = TARGET_CONTRACT_ID,
) -> ProviderExecutableTargetProjection:
    return project_provider_executable_targets(
        target_authority,
        authority,
        registry,
        execution,
        manifest,
        target_contract_id=target_contract_id,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )


def test_signed_target_authority_and_projection_round_trip_inertly() -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
    )
    restored_authority = ProviderExecutableTargetAuthority.from_dict(
        target_authority.to_dict()
    )
    projection = _project(
        target_authority,
        invocation_authority,
        registry,
        execution,
        manifest,
    )
    restored_projection = ProviderExecutableTargetProjection.from_dict(
        projection.to_dict()
    )

    assert restored_authority == target_authority
    assert restored_authority.digest == target_authority.digest
    assert restored_authority.target_manifest_sha256 == manifest.digest
    assert restored_authority.target_descriptor_sha256 == manifest.descriptors[0].digest
    assert restored_authority.invocation_authority_sha256 == invocation_authority.digest
    assert restored_projection == projection
    assert restored_projection.digest == projection.digest
    assert restored_projection.identity_registry_sha256 == registry.digest
    assert restored_projection.identity_descriptor_sha256 == registry.descriptors[0].digest
    assert restored_projection.target_manifest_sha256 == manifest.digest
    assert restored_projection.target_descriptor_sha256 == manifest.descriptors[0].digest
    assert restored_projection.to_dict()["targets_structurally_verified"] is False
    assert restored_projection.to_dict()["provider_execution_allowed"] is False
    assert not hasattr(restored_projection, "invoke")
    assert not hasattr(restored_projection, "output_digests")


def test_invalid_invocation_signature_refuses_before_target_lookup(monkeypatch) -> None:
    execution = _execution()
    registry = _identity_registry()
    valid_invocation = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        valid_invocation,
        registry,
        execution,
        manifest,
    )
    invalid_invocation = dataclasses.replace(
        valid_invocation,
        signature_sha256="f" * 64,
    )

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
        _project(
            target_authority,
            invalid_invocation,
            registry,
            execution,
            manifest,
        )


def test_invalid_target_authority_signature_refuses_before_target_lookup(
    monkeypatch,
) -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = dataclasses.replace(
        _target_authority(
            invocation_authority,
            registry,
            execution,
            manifest,
        ),
        signature_sha256="f" * 64,
    )

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before target authority authentication")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetSignatureError,
        match="signature mismatch",
    ):
        _project(
            target_authority,
            invocation_authority,
            registry,
            execution,
            manifest,
        )


def test_unsigned_target_manifest_substitution_refuses_before_lookup(
    monkeypatch,
) -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
    )
    substituted = _manifest(
        registry,
        _target_descriptor(
            invoke_target="daedalus.runtimes.adapters.fixture:FixtureAdapter.foreign"
        ),
    )

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before signed manifest binding")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="binding mismatch before target lookup",
    ):
        _project(
            target_authority,
            invocation_authority,
            registry,
            execution,
            substituted,
        )


def test_signed_foreign_target_contract_refuses_before_lookup(monkeypatch) -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    foreign = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
        target_contract_id="provider-executable-target-foreign",
    )

    def forbidden_lookup(self, provider_id):
        raise AssertionError("target lookup ran before target contract binding")

    monkeypatch.setattr(
        ProviderExecutableTargetManifest,
        "descriptor_for_provider",
        forbidden_lookup,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="binding mismatch before target lookup",
    ):
        _project(
            foreign,
            invocation_authority,
            registry,
            execution,
            manifest,
        )


_IDENTITY_MISMATCH = "differs from authenticated identity"
# provider_id is the one field that cannot reach the comparison above it.
# The descriptor is selected out of the manifest BY the authenticated
# provider_id, so substituting it means the manifest no longer registers a
# descriptor for the caller at all, and the registration guard refuses
# first. The substitution is still refused; it is refused earlier, by a
# narrower check. Pinning the message per field is what keeps that visible
# -- if provider_id ever started reporting a field mismatch instead, the
# lookup would be matching something other than the authenticated identity.
_NOT_REGISTERED = "is not registered exactly once"


# Kept out of the parametrisation on purpose: the node ids of these cases
# are referenced from outside this file, so the expected message is looked
# up here rather than added as a third parameter.
_EXPECTED_REFUSAL = {"provider_id": _NOT_REGISTERED}


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
def test_authority_issuance_refuses_identity_target_substitution(
    field: str,
    value: str,
) -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    descriptor = _target_descriptor(**{field: value})
    manifest = _manifest(registry, descriptor)

    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match=_EXPECTED_REFUSAL.get(field, _IDENTITY_MISMATCH),
    ):
        _target_authority(
            invocation_authority,
            registry,
            execution,
            manifest,
        )


def test_stale_target_revision_refuses_authority_issuance() -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    stale_revision = "a" * 40
    stale_descriptor = _target_descriptor(source_revision=stale_revision)
    manifest = _manifest(
        registry,
        stale_descriptor,
        source_revision=stale_revision,
    )

    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="source revision mismatch",
    ):
        _target_authority(
            invocation_authority,
            registry,
            execution,
            manifest,
        )


def test_malformed_target_contract_stays_in_target_error_domain() -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)

    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="authority subject is malformed",
    ):
        _target_authority(
            invocation_authority,
            registry,
            execution,
            manifest,
            target_contract_id=" ",
        )


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


def test_authority_manifest_and_projection_wire_fields_are_exact() -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
    )
    projection = _project(
        target_authority,
        invocation_authority,
        registry,
        execution,
        manifest,
    )

    authority_payload = target_authority.to_dict()
    authority_payload["extra"] = True
    with pytest.raises(ProviderExecutableTargetShapeError, match="fields are not exact"):
        ProviderExecutableTargetAuthority.from_dict(authority_payload)

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
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
    )
    payload = _project(
        target_authority,
        invocation_authority,
        registry,
        execution,
        manifest,
    ).to_dict()
    payload[field] = True

    with pytest.raises(ProviderExecutableTargetShapeError):
        ProviderExecutableTargetProjection.from_dict(payload)


def test_exact_target_authority_and_manifest_types_are_required() -> None:
    execution = _execution()
    registry = _identity_registry()
    invocation_authority = _authority(execution, registry)
    manifest = _manifest(registry)
    target_authority = _target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
    )

    class AuthoritySubclass(ProviderExecutableTargetAuthority):
        pass

    class ManifestSubclass(ProviderExecutableTargetManifest):
        pass

    authority_subclass = AuthoritySubclass(**target_authority.to_dict())
    manifest_subclass = ManifestSubclass(
        manifest_id=manifest.manifest_id,
        source_revision=manifest.source_revision,
        identity_registry_sha256=manifest.identity_registry_sha256,
        descriptors=manifest.descriptors,
    )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="target_authority must be exact",
    ):
        _project(
            authority_subclass,
            invocation_authority,
            registry,
            execution,
            manifest,
        )
    with pytest.raises(
        ProviderExecutableTargetBindingError,
        match="manifest must be exact",
    ):
        _project(
            target_authority,
            invocation_authority,
            registry,
            execution,
            manifest_subclass,
        )
