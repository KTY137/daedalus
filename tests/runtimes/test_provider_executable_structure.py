# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

import daedalus.runtimes.provider_executable_structure as subject
from daedalus.gates.python_target_structure import resolve_python_target_structure
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_executable_structure import (
    ProviderExecutableStructureBindingError,
    ProviderExecutableStructureReceipt,
    ProviderExecutableStructureShapeError,
    verify_provider_executable_structure,
    verify_provider_executable_structure_receipt,
)
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetDescriptor,
    build_provider_executable_target_manifest,
    issue_provider_executable_target_authority,
    project_provider_executable_targets,
)
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_authority import (
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_registry import (
    ProviderAdapterDescriptor,
    build_provider_invocation_registry_manifest,
)
from daedalus.runtimes.provider_observation import (
    issue_provider_observation_authority,
)


NOW = datetime(2026, 8, 5, 1, 0, tzinfo=timezone.utc)
REVISION = "a" * 40
LEASE_SHA256 = "1" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}
TARGET_CONTRACT_ID = "provider-executable-target-contract"
AUTHORITY_ID = "authority.runtime-provider-observation"
SOURCE = b'''raise RuntimeError("this module must never be imported")

def invoke():
    return "ok"

def output_digests(value):
    return ("0" * 64,)
'''


def _fixture(tmp_path: Path) -> dict[str, Any]:
    package = tmp_path / "daedalus"
    package.mkdir()
    source_path = package / "demo_provider.py"
    source_path.write_bytes(SOURCE)
    source_sha256 = hashlib.sha256(SOURCE).hexdigest()

    execution = EffectExecutionRequest(
        execution_id="provider-target-execution",
        idempotency_key="provider-target-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=9,
    )
    identity = ProviderAdapterDescriptor(
        provider_id="provider.external-fixture",
        adapter_id="adapter.external-fixture",
        implementation_id="implementation.external-fixture-v1",
        adapter_artifact_sha256="2" * 64,
        adapter_config_sha256="3" * 64,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        source_revision=REVISION,
    )
    registry = build_provider_invocation_registry_manifest(
        registry_id="provider-invocation-registry",
        source_revision=REVISION,
        descriptors=(identity,),
    )
    invocation_subject = ProviderInvocationSubject(
        provider_id=identity.provider_id,
        adapter_id=identity.adapter_id,
        adapter_artifact_sha256=identity.adapter_artifact_sha256,
        adapter_config_sha256=identity.adapter_config_sha256,
        entrypoint_id=identity.entrypoint_id,
        runtime_id=identity.runtime_id,
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
    )
    observation_authority = issue_provider_observation_authority(
        authority_id=AUTHORITY_ID,
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-target-binding",
        provider_id=identity.provider_id,
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id=identity.entrypoint_id,
        runtime_id=identity.runtime_id,
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    invocation_authority = issue_provider_invocation_observation_authority(
        observation_authority=observation_authority,
        invocation_subject=invocation_subject,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=registry.digest,
        authority_secret=AUTHORITY_SECRET,
    )
    target_descriptor = ProviderExecutableTargetDescriptor(
        provider_id=identity.provider_id,
        adapter_id=identity.adapter_id,
        implementation_id=identity.implementation_id,
        entrypoint_id=identity.entrypoint_id,
        runtime_id=identity.runtime_id,
        source_revision=REVISION,
        identity_descriptor_sha256=identity.digest,
        adapter_artifact_sha256=identity.adapter_artifact_sha256,
        adapter_config_sha256=identity.adapter_config_sha256,
        invoke_target="daedalus.demo_provider:invoke",
        invoke_source_sha256=source_sha256,
        output_digests_target="daedalus.demo_provider:output_digests",
        output_digests_source_sha256=source_sha256,
    )
    manifest = build_provider_executable_target_manifest(
        manifest_id="provider-executable-targets",
        source_revision=REVISION,
        identity_registry_sha256=registry.digest,
        descriptors=(target_descriptor,),
    )
    target_authority = issue_provider_executable_target_authority(
        invocation_authority,
        registry,
        execution,
        manifest,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        authority_secret=AUTHORITY_SECRET,
        at=NOW,
    )
    return {
        "root": tmp_path,
        "execution": execution,
        "registry": registry,
        "invocation_authority": invocation_authority,
        "manifest": manifest,
        "target_authority": target_authority,
    }


def _verify(values: dict[str, Any]):
    return verify_provider_executable_structure(
        values["root"],
        values["target_authority"],
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        values["manifest"],
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )


def _reverify(values: dict[str, Any], receipt) -> None:
    verify_provider_executable_structure_receipt(
        values["root"],
        values["target_authority"],
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        values["manifest"],
        receipt,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )


def test_authenticates_authority_before_resolving_without_import(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)

    receipt = _verify(values)

    assert receipt.target_authority_sha256 == values["target_authority"].digest
    assert receipt.invocation_authority_sha256 == (
        values["invocation_authority"].digest
    )
    assert receipt.target_contract_id == TARGET_CONTRACT_ID
    assert receipt.execution_id == values["execution"].execution_id
    assert receipt.lease_sha256 == LEASE_SHA256
    assert receipt.invoke.target == "daedalus.demo_provider:invoke"
    assert receipt.output_digests.target == (
        "daedalus.demo_provider:output_digests"
    )
    assert receipt.to_dict()["target_authority_authenticated"] is True
    assert receipt.to_dict()["repository_bytes_executed"] is False
    assert receipt.to_dict()["provider_execution_allowed"] is False


def test_receipt_round_trip_and_authenticated_live_reverification(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    receipt = _verify(values)

    parsed = ProviderExecutableStructureReceipt.from_dict(receipt.to_dict())

    assert parsed == receipt
    assert parsed.digest == receipt.digest
    _reverify(values, parsed)


def test_invalid_target_authority_refuses_before_repository_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    values["target_authority"] = dataclasses.replace(
        values["target_authority"],
        signature_sha256="f" * 64,
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("repository target resolution ran before authority")

    monkeypatch.setattr(subject, "resolve_python_target_structure", forbidden)

    with pytest.raises(
        ProviderExecutableStructureBindingError,
        match="did not authenticate",
    ):
        _verify(values)


def test_changed_source_refuses_after_authentication(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    (tmp_path / "daedalus" / "demo_provider.py").write_bytes(
        SOURCE.replace(b'return "ok"', b'return "changed"')
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_missing_output_target_refuses(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    changed = SOURCE.replace(
        b"def output_digests",
        b"def renamed_output_digests",
    )
    path = tmp_path / "daedalus" / "demo_provider.py"
    path.write_bytes(changed)
    digest = hashlib.sha256(changed).hexdigest()
    descriptor = dataclasses.replace(
        values["manifest"].descriptors[0],
        invoke_source_sha256=digest,
        output_digests_source_sha256=digest,
    )
    manifest = build_provider_executable_target_manifest(
        manifest_id=values["manifest"].manifest_id,
        source_revision=REVISION,
        identity_registry_sha256=values["registry"].digest,
        descriptors=(descriptor,),
    )
    values["manifest"] = manifest
    values["target_authority"] = issue_provider_executable_target_authority(
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        manifest,
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        authority_secret=AUTHORITY_SECRET,
        at=NOW,
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_manifest_substitution_refuses_before_repository_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    values["manifest"] = build_provider_executable_target_manifest(
        manifest_id="substituted-targets",
        source_revision=REVISION,
        identity_registry_sha256=values["registry"].digest,
        descriptors=values["manifest"].descriptors,
    )

    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: pytest.fail(
            "repository target resolution ran before manifest authentication"
        ),
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_target_authority_substitution_invalidates_retained_receipt(
    tmp_path: Path,
) -> None:
    values = _fixture(tmp_path)
    receipt = _verify(values)
    values["target_authority"] = dataclasses.replace(
        values["target_authority"],
        signature_sha256="f" * 64,
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _reverify(values, receipt)


def test_detached_receipt_authority_digest_refuses(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    receipt = _verify(values)
    detached = dataclasses.replace(
        receipt,
        target_authority_sha256="f" * 64,
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _reverify(values, detached)


def test_wire_authority_escalations_refuse(tmp_path: Path) -> None:
    values = _fixture(tmp_path)
    receipt = _verify(values)

    for field, value in (
        ("target_authority_authenticated", False),
        ("repository_bytes_executed", True),
        ("provider_execution_allowed", True),
        ("source_revision_verified_against_git_head", True),
    ):
        payload = receipt.to_dict()
        payload[field] = value
        with pytest.raises(ProviderExecutableStructureShapeError):
            ProviderExecutableStructureReceipt.from_dict(payload)


def test_exact_authority_subjects_are_required_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    projection = project_provider_executable_targets(
        values["target_authority"],
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        values["manifest"],
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )
    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: pytest.fail(
            "repository resolution ran for unauthenticated projection"
        ),
    )

    values["target_authority"] = projection
    with pytest.raises(ProviderExecutableStructureShapeError):
        _verify(values)


def test_resolver_cannot_substitute_invoke_structure_for_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    projection = project_provider_executable_targets(
        values["target_authority"],
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        values["manifest"],
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )
    invoke = resolve_python_target_structure(
        values["root"],
        projection.invoke_target,
        expected_source_sha256=projection.invoke_source_sha256,
    )

    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: invoke,
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_resolver_cannot_detach_invoke_source_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    projection = project_provider_executable_targets(
        values["target_authority"],
        values["invocation_authority"],
        values["registry"],
        values["execution"],
        values["manifest"],
        target_contract_id=TARGET_CONTRACT_ID,
        authority_id=AUTHORITY_ID,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        at=NOW,
    )
    invoke = resolve_python_target_structure(
        values["root"],
        projection.invoke_target,
        expected_source_sha256=projection.invoke_source_sha256,
    )
    output = resolve_python_target_structure(
        values["root"],
        projection.output_digests_target,
        expected_source_sha256=projection.output_digests_source_sha256,
    )
    detached = dataclasses.replace(invoke, source_sha256="f" * 64)
    structures = iter((detached, output))
    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: next(structures),
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_nonexact_authenticated_projection_refuses_before_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    values = _fixture(tmp_path)
    monkeypatch.setattr(
        subject,
        "project_provider_executable_targets",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        subject,
        "resolve_python_target_structure",
        lambda *args, **kwargs: pytest.fail(
            "repository resolution ran for nonexact authenticated projection"
        ),
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        _verify(values)


def test_repository_root_must_be_pathlib_path(tmp_path: Path) -> None:
    values = _fixture(tmp_path)

    with pytest.raises(ProviderExecutableStructureShapeError):
        verify_provider_executable_structure(
            str(values["root"]),
            values["target_authority"],
            values["invocation_authority"],
            values["registry"],
            values["execution"],
            values["manifest"],
            target_contract_id=TARGET_CONTRACT_ID,
            authority_id=AUTHORITY_ID,
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            at=NOW,
        )
