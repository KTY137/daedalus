from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from daedalus.runtimes.provider_invocation import ProviderInvocationSubject
from daedalus.runtimes.provider_invocation_abi import (
    ProviderInvocationABIBindingError,
    ProviderInvocationABIContract,
    ProviderInvocationABIShapeError,
    ProviderInvocationABISignatureError,
    issue_provider_invocation_abi_contract,
    verify_provider_invocation_abi_contract,
)
from daedalus.runtimes.provider_invocation_authority import (
    issue_provider_invocation_observation_authority,
)
from daedalus.runtimes.provider_invocation_payload import (
    build_provider_invocation_payload,
)
from daedalus.runtimes.provider_observation import issue_provider_observation_authority
from daedalus.spine.envelope import canonical_sha


NOW = datetime(2026, 8, 30, 6, 30, tzinfo=timezone.utc)
REVISION = "a" * 40
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="ikarus-provider-execution",
        idempotency_key="ikarus-provider-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="ikarus-provider-kill-switch",
        kill_switch_generation=1,
    )


def _subject(execution: EffectExecutionRequest, *, adapter_id: str = "claude-cli"):
    return ProviderInvocationSubject(
        provider_id="claude",
        adapter_id=adapter_id,
        adapter_artifact_sha256=_sha("adapter-artifact"),
        adapter_config_sha256=_sha("adapter-config"),
        entrypoint_id="ikarus-one-shot",
        runtime_id="claude-runtime",
        execution_id=execution.execution_id,
        idempotency_key=execution.idempotency_key,
        execution_request_sha256=execution.digest,
        lease_sha256=_sha("runtime-lease"),
        source_revision=REVISION,
    )


def _authority(execution: EffectExecutionRequest):
    subject = _subject(execution)
    observation = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="ikarus-provider-binding",
        provider_id=subject.provider_id,
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution=execution,
        lease_sha256=subject.lease_sha256,
        source_revision=subject.source_revision,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    return issue_provider_invocation_observation_authority(
        observation_authority=observation,
        invocation_subject=subject,
        invocation_contract_id="provider-invocation-contract",
        invocation_registry_sha256=_sha("invocation-registry"),
        authority_secret=AUTHORITY_SECRET,
    )


def _payload(execution: EffectExecutionRequest, *, objective: str = "solve task"):
    return build_provider_invocation_payload(
        _subject(execution),
        payload_schema_id="claude-cli-one-shot-v1",
        body={
            "objective": objective,
            "workspace": "/tmp/ikarus-workspace",
            "model": "claude-sonnet",
            "timeout_seconds": 120,
            "paths": ["src", "tests"],
        },
    )


def _pre_admission(authority) -> ProviderExecutablePreAdmissionReceipt:
    subject = authority.invocation_subject
    return ProviderExecutablePreAdmissionReceipt(
        source_revision=subject.source_revision,
        resolution_sha256=_sha("resolution"),
        verification_sha256=_sha("verification"),
        structure_sha256=_sha("structure"),
        completed_retention_sha256=_sha("completed-retention"),
        retention_effect_terminal_sha256=_sha("retention-terminal"),
        repository_head_sha256=_sha("repository-head"),
        provider_id=subject.provider_id,
        adapter_id=subject.adapter_id,
        implementation_id="claude-cli-v1",
        entrypoint_id=subject.entrypoint_id,
        runtime_id=subject.runtime_id,
        execution_id=subject.execution_id,
        idempotency_key=subject.idempotency_key,
        invocation_authority_sha256=authority.digest,
        invocation_contract_sha256=authority.invocation_contract_sha256,
        invocation_subject_sha256=subject.digest,
        invocation_identity_projection_sha256=_sha("identity-projection"),
        identity_registry_sha256=authority.invocation_registry_sha256,
        identity_descriptor_sha256=_sha("identity-descriptor"),
        target_authority_sha256=_sha("target-authority"),
        target_projection_sha256=_sha("target-projection"),
        target_manifest_sha256=_sha("target-manifest"),
        target_descriptor_sha256=_sha("target-descriptor"),
        adapter_artifact_sha256=subject.adapter_artifact_sha256,
        adapter_config_sha256=subject.adapter_config_sha256,
        lease_sha256=subject.lease_sha256,
        invoke_target="daedalus.providers.claude_cli:invoke",
        invoke_source_sha256=_sha("invoke-source"),
        output_digests_target="daedalus.providers.claude_cli:output_digests",
        output_digests_source_sha256=_sha("output-source"),
    )


def _issue(execution: EffectExecutionRequest):
    authority = _authority(execution)
    payload = _payload(execution)
    pre_admission = _pre_admission(authority)
    contract = issue_provider_invocation_abi_contract(
        authority,
        payload,
        pre_admission,
        authority_id="authority.runtime-provider-observation",
        authority_secret=AUTHORITY_SECRET,
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        execution=execution,
        at=NOW,
    )
    return contract, authority, payload, pre_admission


def _verify(contract, authority, payload, pre_admission, execution) -> None:
    verify_provider_invocation_abi_contract(
        contract,
        authority,
        payload,
        pre_admission,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        execution=execution,
        at=NOW,
    )


def test_authenticated_invocation_abi_round_trips_and_verifies() -> None:
    execution = _execution()
    contract, authority, payload, pre_admission = _issue(execution)

    _verify(contract, authority, payload, pre_admission, execution)
    restored = ProviderInvocationABIContract.from_dict(contract.to_dict())

    assert restored == contract
    assert restored.invocation_payload_sha256 == payload.digest
    assert restored.parent_authority_sha256 == authority.digest
    assert restored.pre_admission_sha256 == pre_admission.digest
    assert restored.invoke_target == pre_admission.invoke_target
    assert restored.output_evidence_target == pre_admission.output_digests_target
    assert restored.to_dict()["provider_execution_allowed"] is False
    assert restored.to_dict()["effect_start_authorized"] is False


def test_payload_semantics_change_authenticated_abi_identity() -> None:
    execution = _execution()
    contract, authority, payload, pre_admission = _issue(execution)
    changed = _payload(execution, objective="different task")

    assert changed.digest != payload.digest
    with pytest.raises(ProviderInvocationABIBindingError):
        _verify(contract, authority, changed, pre_admission, execution)


def test_payload_for_other_adapter_refuses_before_contract_issue() -> None:
    execution = _execution()
    authority = _authority(execution)
    foreign_payload = build_provider_invocation_payload(
        _subject(execution, adapter_id="foreign-adapter"),
        payload_schema_id="foreign-v1",
        body={"objective": "foreign"},
    )

    with pytest.raises(ProviderInvocationABIBindingError, match="adapter_id"):
        issue_provider_invocation_abi_contract(
            authority,
            foreign_payload,
            _pre_admission(authority),
            authority_id="authority.runtime-provider-observation",
            authority_secret=AUTHORITY_SECRET,
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            execution=execution,
            at=NOW,
        )


def test_target_or_payload_digest_substitution_breaks_signature() -> None:
    execution = _execution()
    contract, authority, payload, pre_admission = _issue(execution)

    for candidate in (
        dataclasses.replace(contract, invocation_payload_sha256=_sha("other-payload")),
        dataclasses.replace(contract, invoke_target="foreign.module:invoke"),
        dataclasses.replace(
            contract,
            output_evidence_source_sha256=_sha("other-output-source"),
        ),
    ):
        with pytest.raises(ProviderInvocationABISignatureError):
            _verify(candidate, authority, payload, pre_admission, execution)


def test_parent_authority_or_pre_admission_substitution_refuses() -> None:
    execution = _execution()
    contract, authority, payload, pre_admission = _issue(execution)

    forged_pre_admission = dataclasses.replace(
        pre_admission,
        invocation_authority_sha256=_sha("foreign-authority"),
    )
    with pytest.raises(ProviderInvocationABIBindingError):
        _verify(contract, authority, payload, forged_pre_admission, execution)

    foreign_execution = dataclasses.replace(
        execution,
        execution_id="foreign-execution",
    )
    with pytest.raises(ProviderInvocationABIBindingError):
        _verify(contract, authority, payload, pre_admission, foreign_execution)


def test_serialized_claim_escalation_and_subclass_smuggling_refuse() -> None:
    execution = _execution()
    contract, authority, payload, pre_admission = _issue(execution)
    raw = contract.to_dict()
    raw["provider_execution_allowed"] = True
    with pytest.raises(ProviderInvocationABIShapeError):
        ProviderInvocationABIContract.from_dict(raw)

    class ForgedContract(ProviderInvocationABIContract):
        pass

    forged = ForgedContract(**dataclasses.asdict(contract))
    with pytest.raises(ProviderInvocationABIShapeError):
        _verify(forged, authority, payload, pre_admission, execution)
