from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.runtimes.provider.executable_targets import (
    ProviderExecutableTargetAuthority,
    ProviderExecutableTargetDescriptor,
    ProviderExecutableTargetManifest,
    build_provider_executable_target_manifest,
    issue_provider_executable_target_authority,
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
from daedalus.runtimes.provider.target_verification import (
    issue_provider_target_verification_receipt,
    verify_provider_target_verification_receipt,
)
from daedalus.runtimes.provider.target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    ProviderTargetVerificationBindingError,
    ProviderTargetVerificationSignatureError,
    ProviderTargetVerificationSourceError,
    VerifiedPythonTarget,
)


NOW = datetime(2026, 8, 5, 2, 0, tzinfo=timezone.utc)
NOW_WIRE = "2026-08-05T02:00:00+00:00"
REVISION = "824b1ec93b9c38c071613031be516facb0e6405b"
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
VERIFIER_SECRET = b"provider-verifier-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}
VERIFIER_KEYRING = {"provider-verifier-key": VERIFIER_SECRET}
TARGET_CONTRACT_ID = "provider-executable-target-contract"
SOURCE_PATH = "daedalus/runtimes/adapters/fixture.py"
SOURCE = b"""class FixtureAdapter:
    def invoke(self, request):
        return request

    def output_digests(self, response):
        return (\"a\" * 64,)
"""


@dataclass(frozen=True)
class Fixture:
    store: SourceTreeStore
    tree_ref: ArtifactRef
    execution: EffectExecutionRequest
    identity_registry: ProviderInvocationRegistryManifest
    invocation_authority: ProviderInvocationObservationAuthority
    target_manifest: ProviderExecutableTargetManifest
    target_authority: ProviderExecutableTargetAuthority


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-target-verification-execution",
        idempotency_key="provider-target-verification-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=11,
    )


def _identity_descriptor() -> ProviderAdapterDescriptor:
    return ProviderAdapterDescriptor(
        provider_id="provider.external-fixture",
        adapter_id="adapter.external-fixture",
        implementation_id="implementation.external-fixture-v1",
        adapter_artifact_sha256="2" * 64,
        adapter_config_sha256="3" * 64,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        source_revision=REVISION,
    )


def _identity_registry() -> ProviderInvocationRegistryManifest:
    return build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=(_identity_descriptor(),),
    )


def _invocation_authority(
    execution: EffectExecutionRequest,
    registry: ProviderInvocationRegistryManifest,
) -> ProviderInvocationObservationAuthority:
    subject = ProviderInvocationSubject(
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
    observation = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-target-verification-binding",
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
    return issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=subject,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=registry.digest,
        authority_secret=AUTHORITY_SECRET,
    )


def _target_manifest(
    registry: ProviderInvocationRegistryManifest,
    source_digest: str,
    *,
    invoke_target: str = (
        "daedalus.runtimes.adapters.fixture:FixtureAdapter.invoke"
    ),
    output_target: str = (
        "daedalus.runtimes.adapters.fixture:FixtureAdapter.output_digests"
    ),
) -> ProviderExecutableTargetManifest:
    identity = registry.descriptors[0]
    descriptor = ProviderExecutableTargetDescriptor(
        provider_id=identity.provider_id,
        adapter_id=identity.adapter_id,
        implementation_id=identity.implementation_id,
        entrypoint_id=identity.entrypoint_id,
        runtime_id=identity.runtime_id,
        source_revision=identity.source_revision,
        identity_descriptor_sha256=identity.digest,
        adapter_artifact_sha256=identity.adapter_artifact_sha256,
        adapter_config_sha256=identity.adapter_config_sha256,
        invoke_target=invoke_target,
        invoke_source_sha256=source_digest,
        output_digests_target=output_target,
        output_digests_source_sha256=source_digest,
    )
    return build_provider_executable_target_manifest(
        manifest_id="provider-executable-targets",
        source_revision=REVISION,
        identity_registry_sha256=registry.digest,
        descriptors=(descriptor,),
    )


def _target_authority(
    invocation_authority: ProviderInvocationObservationAuthority,
    registry: ProviderInvocationRegistryManifest,
    execution: EffectExecutionRequest,
    manifest: ProviderExecutableTargetManifest,
) -> ProviderExecutableTargetAuthority:
    return issue_provider_executable_target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        authority_secret=AUTHORITY_SECRET,
        at=NOW,
    )


def _capture(
    tmp_path: Path,
    source: bytes = SOURCE,
    *,
    revision: str = REVISION,
    package_shadow: bytes | None = None,
    extra: dict[str, bytes] | None = None,
) -> tuple[SourceTreeStore, ArtifactRef]:
    root = tmp_path / "source"
    target = root / SOURCE_PATH
    target.parent.mkdir(parents=True)
    target.write_bytes(source)
    if package_shadow is not None:
        package = root / "daedalus/runtimes/adapters/fixture/__init__.py"
        package.parent.mkdir(parents=True)
        package.write_bytes(package_shadow)
    for path, payload in (extra or {}).items():
        output = root / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    store = SourceTreeStore(tmp_path / "cas")
    stored = store.capture_tree(
        root,
        tree_id="provider-verification-source-tree",
        source_revision=revision,
        origin="tests.provider-target-verification",
        created_at=NOW_WIRE,
        trace_id="provider-target-verification-trace",
    )
    return store, stored.ref


def _fixture(
    tmp_path: Path,
    *,
    source: bytes = SOURCE,
    signed_source_digest: str | None = None,
    revision: str = REVISION,
    package_shadow: bytes | None = None,
    invoke_target: str = (
        "daedalus.runtimes.adapters.fixture:FixtureAdapter.invoke"
    ),
    output_target: str = (
        "daedalus.runtimes.adapters.fixture:FixtureAdapter.output_digests"
    ),
    extra: dict[str, bytes] | None = None,
) -> Fixture:
    store, tree_ref = _capture(
        tmp_path,
        source,
        revision=revision,
        package_shadow=package_shadow,
        extra=extra,
    )
    execution = _execution()
    registry = _identity_registry()
    invocation = _invocation_authority(execution, registry)
    manifest = _target_manifest(
        registry,
        signed_source_digest or sha256(source).hexdigest(),
        invoke_target=invoke_target,
        output_target=output_target,
    )
    authority = _target_authority(
        invocation,
        registry,
        execution,
        manifest,
    )
    return Fixture(
        store=store,
        tree_ref=tree_ref,
        execution=execution,
        identity_registry=registry,
        invocation_authority=invocation,
        target_manifest=manifest,
        target_authority=authority,
    )


def _issue(fixture: Fixture) -> ProviderExecutableTargetVerificationReceipt:
    return issue_provider_target_verification_receipt(
        fixture.target_authority,
        fixture.invocation_authority,
        fixture.identity_registry,
        fixture.execution,
        fixture.target_manifest,
        fixture.store,
        fixture.tree_ref,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        verifier_id="provider-target-verifier",
        verifier_key_id="provider-verifier-key",
        verifier_keyring=VERIFIER_KEYRING,
        at=NOW,
    )


def _verify(
    receipt: ProviderExecutableTargetVerificationReceipt,
    fixture: Fixture,
    *,
    verifier_keyring=VERIFIER_KEYRING,
):
    return verify_provider_target_verification_receipt(
        receipt,
        fixture.target_authority,
        fixture.invocation_authority,
        fixture.identity_registry,
        fixture.execution,
        fixture.target_manifest,
        fixture.store,
        fixture.tree_ref,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        verifier_id="provider-target-verifier",
        verifier_keyring=verifier_keyring,
        at=NOW,
    )


def test_exact_source_tree_issues_and_reverifies_inert_signed_receipt(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    receipt = _issue(fixture)
    restored = ProviderExecutableTargetVerificationReceipt.from_dict(
        receipt.to_dict()
    )
    projection = _verify(restored, fixture)

    assert restored == receipt
    assert restored.digest == receipt.digest
    assert restored.source_tree_sha256 == fixture.tree_ref.sha256
    assert restored.source_tree_locator == fixture.tree_ref.locator
    assert restored.target_authority_sha256 == fixture.target_authority.digest
    assert restored.target_manifest_sha256 == fixture.target_manifest.digest
    assert restored.invoke.repository_path == SOURCE_PATH
    assert restored.invoke.qualified_name == "FixtureAdapter.invoke"
    assert restored.invoke.node_kind == "method"
    assert restored.output_digests.node_kind == "method"
    assert restored.to_dict()["targets_structurally_verified"] is True
    assert restored.to_dict()["provider_execution_allowed"] is False
    assert projection.provider_id == "provider.external-fixture"
    assert not hasattr(restored, "invoke_provider")
    assert not hasattr(projection, "invoke")


def test_invalid_target_authority_refuses_before_source_tree_read(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path)
    invalid = dataclasses.replace(
        fixture.target_authority,
        signature_sha256="f" * 64,
    )

    def forbidden_load(self, ref, **kwargs):
        raise AssertionError("source tree loaded before signed target authentication")

    monkeypatch.setattr(SourceTreeStore, "load_tree", forbidden_load)
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="did not authenticate",
    ):
        issue_provider_target_verification_receipt(
            invalid,
            fixture.invocation_authority,
            fixture.identity_registry,
            fixture.execution,
            fixture.target_manifest,
            fixture.store,
            fixture.tree_ref,
            target_contract_id=TARGET_CONTRACT_ID,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            verifier_id="provider-target-verifier",
            verifier_key_id="provider-verifier-key",
            verifier_keyring=VERIFIER_KEYRING,
            at=NOW,
        )


def test_invalid_receipt_signature_refuses_before_source_tree_read(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = dataclasses.replace(_issue(fixture), signature_sha256="f" * 64)

    def forbidden_load(self, ref, **kwargs):
        raise AssertionError("source tree loaded before receipt authentication")

    monkeypatch.setattr(SourceTreeStore, "load_tree", forbidden_load)
    with pytest.raises(
        ProviderTargetVerificationSignatureError,
        match="signature mismatch",
    ):
        _verify(receipt, fixture)


def test_unknown_verifier_key_refuses_before_source_tree_read(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path)
    receipt = _issue(fixture)

    def forbidden_load(self, ref, **kwargs):
        raise AssertionError("source tree loaded before key authentication")

    monkeypatch.setattr(SourceTreeStore, "load_tree", forbidden_load)
    with pytest.raises(
        ProviderTargetVerificationSignatureError,
        match="key is unknown",
    ):
        _verify(receipt, fixture, verifier_keyring={"foreign-key": VERIFIER_SECRET})


def test_source_bytes_are_rehashed_independently_of_store_method(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path)
    original = SourceTreeStore.read_bytes

    def substituted(self, ref, *, max_bytes):
        payload = original(self, ref, max_bytes=max_bytes)
        digest = ref.sha256 if isinstance(ref, ArtifactRef) else ref.rsplit(":", 1)[-1]
        if digest == fixture.tree_ref.sha256:
            return payload
        return b"x" * len(payload)

    monkeypatch.setattr(SourceTreeStore, "read_bytes", substituted)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="content address",
    ):
        _issue(fixture)


def test_signed_source_digest_substitution_refuses(tmp_path) -> None:
    fixture = _fixture(tmp_path, signed_source_digest="9" * 64)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="digest differs",
    ):
        _issue(fixture)


def test_stale_source_tree_revision_refuses(tmp_path) -> None:
    fixture = _fixture(tmp_path, revision="a" * 40)
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="source tree revision",
    ):
        _issue(fixture)


def test_module_file_and_package_shadow_are_ambiguous(tmp_path) -> None:
    fixture = _fixture(tmp_path, package_shadow=SOURCE)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="exactly one",
    ):
        _issue(fixture)


def test_duplicate_method_definitions_are_ambiguous(tmp_path) -> None:
    source = b"""class FixtureAdapter:
    def invoke(self, request):
        return request
    def invoke(self, request):
        return request
    def output_digests(self, response):
        return ()
"""
    fixture = _fixture(tmp_path, source=source)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="ambiguous",
    ):
        _issue(fixture)


@pytest.mark.parametrize(
    "source,invoke_target,match",
    [
        (
            b"""def real(request):
    return request
class FixtureAdapter:
    invoke = staticmethod(real)
    def output_digests(self, response):
        return ()
""",
            "daedalus.runtimes.adapters.fixture:FixtureAdapter.invoke",
            "missing|ambiguous",
        ),
        (
            b"""class FixtureAdapter:
    def output_digests(self, response):
        return ()
""",
            "daedalus.runtimes.adapters.fixture:FixtureAdapter",
            "function or method",
        ),
        (
            b"""def invoke(request):
    return request
class FixtureAdapter:
    def output_digests(self, response):
        return ()
""",
            "daedalus.runtimes.adapters.fixture:invoke.child",
            "non-final",
        ),
    ],
)
def test_alias_class_and_function_owner_targets_refuse(
    tmp_path,
    source: bytes,
    invoke_target: str,
    match: str,
) -> None:
    fixture = _fixture(
        tmp_path,
        source=source,
        invoke_target=invoke_target,
    )
    with pytest.raises(ProviderTargetVerificationSourceError, match=match):
        _issue(fixture)


def test_async_methods_are_reported_without_execution(tmp_path) -> None:
    source = b"""class FixtureAdapter:
    async def invoke(self, request):
        return request
    async def output_digests(self, response):
        return ()
"""
    receipt = _issue(_fixture(tmp_path, source=source))
    assert receipt.invoke.node_kind == "async_method"
    assert receipt.output_digests.node_kind == "async_method"


@pytest.mark.parametrize(
    "source,match",
    [
        (b"\xff\xfe\x00\x00", "strict UTF-8"),
        (
            b"""class FixtureAdapter:
    def invoke(self, request)
        return request
""",
            "parseable",
        ),
    ],
)
def test_malformed_source_refuses(tmp_path, source: bytes, match: str) -> None:
    fixture = _fixture(tmp_path, source=source)
    with pytest.raises(ProviderTargetVerificationSourceError, match=match):
        _issue(fixture)


def test_source_read_bound_is_enforced(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    with pytest.raises(
        ProviderTargetVerificationSourceError,
        match="read bound",
    ):
        issue_provider_target_verification_receipt(
            fixture.target_authority,
            fixture.invocation_authority,
            fixture.identity_registry,
            fixture.execution,
            fixture.target_manifest,
            fixture.store,
            fixture.tree_ref,
            target_contract_id=TARGET_CONTRACT_ID,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            verifier_id="provider-target-verifier",
            verifier_key_id="provider-verifier-key",
            verifier_keyring=VERIFIER_KEYRING,
            at=NOW,
            max_source_bytes=1,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("targets_structurally_verified", False),
        ("provider_execution_allowed", True),
        ("schema", "daedalus-provider-target-verification-receipt/2"),
    ],
)
def test_receipt_wire_cannot_change_claims(field: str, value, tmp_path) -> None:
    payload = _issue(_fixture(tmp_path)).to_dict()
    payload[field] = value
    with pytest.raises(ProviderTargetVerificationBindingError):
        ProviderExecutableTargetVerificationReceipt.from_dict(payload)


def test_receipt_wire_fields_are_exact(tmp_path) -> None:
    payload = _issue(_fixture(tmp_path)).to_dict()
    payload["extra"] = True
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="fields are not exact",
    ):
        ProviderExecutableTargetVerificationReceipt.from_dict(payload)


def test_signed_receipt_is_bound_to_exact_source_tree_identity(tmp_path) -> None:
    first = _fixture(tmp_path / "first")
    receipt = _issue(first)
    second = _fixture(
        tmp_path / "second",
        extra={"README.md": b"different source tree identity\n"},
    )
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="differs from exact source-tree evidence",
    ):
        _verify(receipt, second)


def test_exact_store_ref_and_receipt_types_are_required(tmp_path) -> None:
    fixture = _fixture(tmp_path)
    receipt = _issue(fixture)

    class StoreSubclass(SourceTreeStore):
        pass

    class RefSubclass(ArtifactRef):
        pass

    class ReceiptSubclass(ProviderExecutableTargetVerificationReceipt):
        pass

    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="source_store must be exact",
    ):
        issue_provider_target_verification_receipt(
            fixture.target_authority,
            fixture.invocation_authority,
            fixture.identity_registry,
            fixture.execution,
            fixture.target_manifest,
            StoreSubclass(fixture.store.root),
            fixture.tree_ref,
            target_contract_id=TARGET_CONTRACT_ID,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            verifier_id="provider-target-verifier",
            verifier_key_id="provider-verifier-key",
            verifier_keyring=VERIFIER_KEYRING,
            at=NOW,
        )
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="source_tree_ref must be exact",
    ):
        issue_provider_target_verification_receipt(
            fixture.target_authority,
            fixture.invocation_authority,
            fixture.identity_registry,
            fixture.execution,
            fixture.target_manifest,
            fixture.store,
            RefSubclass(
                sha256=fixture.tree_ref.sha256,
                locator=fixture.tree_ref.locator,
            ),
            target_contract_id=TARGET_CONTRACT_ID,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            verifier_id="provider-target-verifier",
            verifier_key_id="provider-verifier-key",
            verifier_keyring=VERIFIER_KEYRING,
            at=NOW,
        )
    receipt_values = {
        field.name: getattr(receipt, field.name)
        for field in dataclasses.fields(receipt)
    }
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="receipt must be exact",
    ):
        _verify(ReceiptSubclass(**receipt_values), fixture)


def test_verified_target_wire_refuses_subclasses_and_bad_extent(tmp_path) -> None:
    target = _issue(_fixture(tmp_path)).invoke
    payload = target.to_dict()
    payload["line"] = 0
    with pytest.raises(ProviderTargetVerificationBindingError, match="line range"):
        VerifiedPythonTarget.from_dict(payload)

    class TargetSubclass(VerifiedPythonTarget):
        pass

    receipt = _issue(_fixture(tmp_path / "subclass"))
    with pytest.raises(
        ProviderTargetVerificationBindingError,
        match="invoke must be exact",
    ):
        dataclasses.replace(
            receipt,
            invoke=TargetSubclass(**receipt.invoke.to_dict()),
        )
