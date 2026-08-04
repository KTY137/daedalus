from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_authority import (
    ProviderInvocationAuthorityBindingError,
    ProviderInvocationAuthoritySignatureError,
    ProviderInvocationObservationAuthority,
    issue_provider_invocation_observation_authority,
    verify_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_observation import (
    issue_provider_observation_authority,
)


NOW = datetime(2026, 8, 4, 22, 0, tzinfo=timezone.utc)
REVISION = "0c437da95838f34b0cc1eb038d6886aa614e7548"
LEASE_SHA256 = "1" * 64
REGISTRY_SHA256 = "2" * 64
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


def _subject(
    execution: EffectExecutionRequest,
    **changes: str,
) -> ProviderInvocationSubject:
    values = {
        "provider_id": "provider.external-fixture",
        "adapter_id": "adapter.external-fixture",
        "adapter_artifact_sha256": "3" * 64,
        "adapter_config_sha256": "4" * 64,
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


def _authority(execution: EffectExecutionRequest):
    return issue_provider_invocation_observation_authority(
        observation_authority=_observation(execution),
        invocation_subject=_subject(execution),
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=REGISTRY_SHA256,
        authority_secret=AUTHORITY_SECRET,
    )


def _verify(
    authority: ProviderInvocationObservationAuthority,
    execution: EffectExecutionRequest,
    *,
    subject: ProviderInvocationSubject | None = None,
    contract_id: str = "provider-invocation-contract",
    registry_sha256: str = REGISTRY_SHA256,
    authority_keyring=AUTHORITY_KEYRING,
) -> None:
    verify_provider_invocation_observation_authority(
        authority,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=authority_keyring,
        observation_keyring=OBSERVATION_KEYRING,
        invocation_subject=subject or _subject(execution),
        invocation_contract_id=contract_id,
        invocation_registry_sha256=registry_sha256,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        at=NOW,
    )


def test_exact_composite_authority_round_trips_and_verifies() -> None:
    execution = _execution()
    authority = _authority(execution)

    _verify(authority, execution)
    restored = ProviderInvocationObservationAuthority.from_dict(
        authority.to_dict()
    )

    assert restored == authority
    assert restored.digest == authority.digest
    assert restored.invocation_subject.provider_id == (
        restored.observation_authority.provider_id
    )
    assert len(restored.invocation_contract_sha256) == 64


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("adapter_id", "adapter.foreign"),
        ("adapter_artifact_sha256", "5" * 64),
        ("adapter_config_sha256", "6" * 64),
        ("entrypoint_id", "provider.foreign"),
        ("runtime_id", "runtime-foreign"),
        ("execution_id", "foreign-execution"),
        ("idempotency_key", "foreign-idempotency"),
        ("execution_request_sha256", "7" * 64),
        ("lease_sha256", "8" * 64),
        ("source_revision", "9" * 40),
    ],
)
def test_expected_invocation_subject_substitution_refuses(
    field: str,
    value: str,
) -> None:
    execution = _execution()
    authority = _authority(execution)
    expected = _subject(execution, **{field: value})

    with pytest.raises(ProviderInvocationAuthorityBindingError):
        _verify(authority, execution, subject=expected)


@pytest.mark.parametrize(
    ("dimension", "expected_error"),
    [
        ("signature", ProviderInvocationAuthoritySignatureError),
        ("registry", ProviderInvocationAuthoritySignatureError),
        ("contract", ProviderInvocationAuthoritySignatureError),
        ("nested-signature", ProviderInvocationAuthorityBindingError),
    ],
)
def test_signed_composite_substitution_refuses(
    dimension: str,
    expected_error: type[Exception],
) -> None:
    execution = _execution()
    authority = _authority(execution)
    if dimension == "signature":
        candidate = dataclasses.replace(authority, signature_sha256="0" * 64)
    elif dimension == "registry":
        candidate = dataclasses.replace(
            authority,
            invocation_registry_sha256="a" * 64,
        )
    elif dimension == "contract":
        candidate = dataclasses.replace(
            authority,
            invocation_contract_id="provider-foreign-contract",
        )
    else:
        nested = dataclasses.replace(
            authority.observation_authority,
            signature_sha256="0" * 64,
        )
        candidate = dataclasses.replace(
            authority,
            observation_authority=nested,
        )

    with pytest.raises(expected_error):
        _verify(candidate, execution)


def test_registry_and_contract_expectation_mismatch_refuses() -> None:
    execution = _execution()
    authority = _authority(execution)

    with pytest.raises(ProviderInvocationAuthorityBindingError):
        _verify(authority, execution, registry_sha256="b" * 64)
    with pytest.raises(ProviderInvocationAuthorityBindingError):
        _verify(authority, execution, contract_id="provider-other-contract")


def test_shared_observation_and_invocation_subject_must_match_before_signing() -> None:
    execution = _execution()
    observation = _observation(execution)
    stale = _subject(execution, source_revision="c" * 40)

    with pytest.raises(
        ProviderInvocationAuthorityBindingError,
        match="source_revision",
    ):
        issue_provider_invocation_observation_authority(
            observation_authority=observation,
            invocation_subject=stale,
            invocation_contract_id="provider-invocation-contract",
            invocation_registry_sha256=REGISTRY_SHA256,
            authority_secret=AUTHORITY_SECRET,
        )


def test_contract_digest_is_sensitive_to_adapter_and_registry_identity() -> None:
    execution = _execution()
    authority = _authority(execution)
    changed_adapter = issue_provider_invocation_observation_authority(
        observation_authority=authority.observation_authority,
        invocation_subject=_subject(execution, adapter_id="adapter.second"),
        invocation_contract_id=authority.invocation_contract_id,
        invocation_registry_sha256=authority.invocation_registry_sha256,
        authority_secret=AUTHORITY_SECRET,
    )
    changed_registry = issue_provider_invocation_observation_authority(
        observation_authority=authority.observation_authority,
        invocation_subject=authority.invocation_subject,
        invocation_contract_id=authority.invocation_contract_id,
        invocation_registry_sha256="d" * 64,
        authority_secret=AUTHORITY_SECRET,
    )

    assert changed_adapter.invocation_contract_sha256 != (
        authority.invocation_contract_sha256
    )
    assert changed_registry.invocation_contract_sha256 != (
        authority.invocation_contract_sha256
    )


def test_from_dict_requires_exact_nested_fields() -> None:
    authority = _authority(_execution())
    payload = authority.to_dict()
    payload["unexpected"] = True

    with pytest.raises(ProviderInvocationAuthorityBindingError):
        ProviderInvocationObservationAuthority.from_dict(payload)

    payload = authority.to_dict()
    del payload["invocation_subject"]["adapter_id"]
    with pytest.raises(ProviderInvocationAuthorityBindingError):
        ProviderInvocationObservationAuthority.from_dict(payload)


def test_malformed_or_unknown_authority_keyring_stays_inside_boundary() -> None:
    execution = _execution()
    authority = _authority(execution)

    with pytest.raises(ProviderInvocationAuthorityBindingError):
        _verify(
            authority,
            execution,
            authority_keyring={"provider-authority-key": b"short"},
        )
    with pytest.raises(ProviderInvocationAuthorityBindingError):
        _verify(
            authority,
            execution,
            authority_keyring={
                "foreign-authority-key":
                    b"foreign-authority-secret-material-at-least-32-bytes"
            },
        )
