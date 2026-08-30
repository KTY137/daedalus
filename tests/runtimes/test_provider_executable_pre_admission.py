from __future__ import annotations

import dataclasses

import pytest

from daedalus.gates.repository_head_revision import RepositoryHeadRevisionReceipt
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionBindingError,
    ProviderExecutablePreAdmissionReceipt,
    ProviderExecutablePreAdmissionShapeError,
    build_provider_executable_pre_admission,
)
from daedalus.runtimes.provider_executable_structure import (
    ProviderExecutableStructureReceipt,
    VerifiedProviderExecutableTarget,
)
from daedalus.runtimes.provider_invocation_resolution import (
    ProviderInvocationResolutionReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceReceipt,
)
from daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence import (
    ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    VerifiedPythonTarget,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "a" * 40
NOW = "2026-08-30T01:00:00.000000+00:00"
LATER = "2026-08-30T01:00:01.000000+00:00"


def _sha(label: str) -> str:
    return canonical_sha({"label": label})


def _resolution() -> ProviderInvocationResolutionReceipt:
    values = {
        "registry_id": "provider-registry",
        "registry_sha256": _sha("registry"),
        "source_revision": REVISION,
        "authority_sha256": _sha("invocation-authority"),
        "observation_authority_sha256": _sha("observation-authority"),
        "invocation_contract_id": "provider-invocation-contract",
        "invocation_contract_sha256": _sha("invocation-contract"),
        "invocation_subject_sha256": _sha("invocation-subject"),
        "descriptor_sha256": _sha("identity-descriptor"),
        "provider_id": "claude",
        "adapter_id": "claude-cli",
        "implementation_id": "claude-cli-v1",
        "adapter_artifact_sha256": _sha("adapter-artifact"),
        "adapter_config_sha256": _sha("adapter-config"),
        "entrypoint_id": "ikarus-one-shot",
        "runtime_id": "claude-runtime",
        "execution_id": "execution-1",
        "idempotency_key": "idempotency-1",
        "execution_request_sha256": _sha("execution-request"),
        "lease_sha256": _sha("runtime-lease"),
        "verified_at": NOW,
    }
    return ProviderInvocationResolutionReceipt(
        **values,
        receipt_sha256=canonical_sha(values),
    )


def _identity_projection_sha(
    resolution: ProviderInvocationResolutionReceipt,
) -> str:
    return canonical_sha(
        {
            "schema": "daedalus-provider-invocation-identity/1",
            "provider_id": resolution.provider_id,
            "adapter_id": resolution.adapter_id,
            "implementation_id": resolution.implementation_id,
            "entrypoint_id": resolution.entrypoint_id,
            "runtime_id": resolution.runtime_id,
            "execution_id": resolution.execution_id,
            "idempotency_key": resolution.idempotency_key,
            "source_revision": resolution.source_revision,
            "authority_sha256": resolution.authority_sha256,
            "observation_authority_sha256": (
                resolution.observation_authority_sha256
            ),
            "invocation_contract_sha256": resolution.invocation_contract_sha256,
            "invocation_subject_sha256": resolution.invocation_subject_sha256,
            "registry_sha256": resolution.registry_sha256,
            "descriptor_sha256": resolution.descriptor_sha256,
            "execution_request_sha256": resolution.execution_request_sha256,
            "lease_sha256": resolution.lease_sha256,
            "adapter_artifact_sha256": resolution.adapter_artifact_sha256,
            "adapter_config_sha256": resolution.adapter_config_sha256,
            "runtime_effect_authorized": False,
            "provider_execution_allowed": False,
        }
    )


def _verified_target(
    target: str,
    *,
    source_sha256: str,
    line: int,
) -> VerifiedPythonTarget:
    return VerifiedPythonTarget(
        target=target,
        repository_path="daedalus/providers/claude_cli.py",
        source_sha256=source_sha256,
        source_size=512,
        qualified_name=target.split(":", 1)[1],
        node_kind="function",
        line=line,
        end_line=line + 3,
    )


def _structure_target(
    target: str,
    *,
    source_sha256: str,
    line: int,
) -> VerifiedProviderExecutableTarget:
    subject = {
        "target": target,
        "source_path": "daedalus/providers/claude_cli.py",
        "source_sha256": source_sha256,
        "source_size": 512,
        "definition_kind": "function",
        "line": line,
        "column": 0,
        "end_line": line + 3,
        "end_column": 0,
        "chain_kinds": ["function"],
        "structural_target_verified": True,
        "behavior_verified": False,
        "executed": False,
    }
    return VerifiedProviderExecutableTarget(
        role=("invoke" if target.endswith(":invoke") else "output_digests"),
        target=target,
        source_path=subject["source_path"],
        source_sha256=source_sha256,
        source_size=512,
        definition_kind="function",
        line=line,
        column=0,
        end_line=line + 3,
        end_column=0,
        chain_kinds=("function",),
        structure_sha256=canonical_sha(subject),
    )


def _components():
    resolution = _resolution()
    invoke_sha = _sha("invoke-source")
    output_sha = _sha("output-source")
    invoke_target = "daedalus.providers.claude_cli:invoke"
    output_target = "daedalus.providers.claude_cli:output_digests"
    invoke = _verified_target(invoke_target, source_sha256=invoke_sha, line=10)
    output = _verified_target(output_target, source_sha256=output_sha, line=30)
    target_authority_sha = _sha("target-authority")
    target_projection_sha = _sha("target-projection")
    target_manifest_sha = _sha("target-manifest")
    target_descriptor_sha = _sha("target-descriptor")
    tree_sha = _sha("source-tree")
    verification = ProviderExecutableTargetVerificationReceipt(
        verifier_id="provider-target-verifier",
        verifier_key_id="verifier-key",
        source_revision=REVISION,
        source_tree_id="source-tree-1",
        source_tree_sha256=tree_sha,
        source_tree_locator=ArtifactRef.from_sha256(tree_sha).locator,
        target_authority_sha256=target_authority_sha,
        target_projection_sha256=target_projection_sha,
        target_manifest_sha256=target_manifest_sha,
        target_descriptor_sha256=target_descriptor_sha,
        provider_id=resolution.provider_id,
        adapter_id=resolution.adapter_id,
        implementation_id=resolution.implementation_id,
        entrypoint_id=resolution.entrypoint_id,
        runtime_id=resolution.runtime_id,
        execution_id=resolution.execution_id,
        idempotency_key=resolution.idempotency_key,
        lease_sha256=resolution.lease_sha256,
        invoke=invoke,
        output_digests=output,
        signature_sha256=_sha("verification-signature"),
    )
    structure = ProviderExecutableStructureReceipt(
        provider_id=resolution.provider_id,
        adapter_id=resolution.adapter_id,
        implementation_id=resolution.implementation_id,
        entrypoint_id=resolution.entrypoint_id,
        runtime_id=resolution.runtime_id,
        execution_id=resolution.execution_id,
        idempotency_key=resolution.idempotency_key,
        source_revision=REVISION,
        target_contract_id="provider-executable-target-contract",
        lease_sha256=resolution.lease_sha256,
        target_authority_sha256=target_authority_sha,
        invocation_authority_sha256=resolution.authority_sha256,
        invocation_contract_sha256=resolution.invocation_contract_sha256,
        identity_sha256=_identity_projection_sha(resolution),
        identity_registry_sha256=resolution.registry_sha256,
        identity_descriptor_sha256=resolution.descriptor_sha256,
        target_projection_sha256=target_projection_sha,
        target_manifest_sha256=target_manifest_sha,
        target_descriptor_sha256=target_descriptor_sha,
        adapter_artifact_sha256=resolution.adapter_artifact_sha256,
        adapter_config_sha256=resolution.adapter_config_sha256,
        invoke=_structure_target(invoke_target, source_sha256=invoke_sha, line=10),
        output_digests=_structure_target(
            output_target,
            source_sha256=output_sha,
            line=30,
        ),
    )
    completed = ProviderTargetReceiptRetentionCompletedEvidenceReceipt(
        source_revision=REVISION,
        admission_sha256=_sha("retention-admission"),
        recovery_decision_sha256=_sha("recovery-decision"),
        provider_target_receipt_sha256=verification.digest,
        target_projection_sha256=target_projection_sha,
        receipt_artifact_sha256=verification.digest,
        retention_intent_id=1,
        retention_intent_payload_sha256=_sha("retention-intent"),
        retention_event_evidence_sha256=_sha("retention-event"),
        retention_topology_identity_sha256=_sha("retention-topology"),
        receipt_artifact_file_identity_sha256=_sha("retained-file"),
        start_receipt_sha256=_sha("retention-start"),
        terminal_receipt_sha256=_sha("retention-terminal"),
        event_store_path="/tmp/daedalus-event-store.db",
        receipt_cas_path="/tmp/daedalus-receipt-cas",
    )
    terminal = ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt(
        source_revision=REVISION,
        completed_evidence_sha256=completed.digest,
        provider_target_receipt_sha256=verification.digest,
        retention_execution_request_sha256=_sha("retention-execution"),
        retention_effect_lease_sha256=_sha("retention-effect-lease"),
        start_receipt_sha256=completed.start_receipt_sha256,
        terminal_receipt_sha256=completed.terminal_receipt_sha256,
        terminal_output_set_sha256=_sha("terminal-output-set"),
        effect_execution_evidence_sha256=_sha("effect-execution-evidence"),
        effect_lease_store_identity_sha256=_sha("effect-store-identity"),
        effect_lease_store_path="/tmp/daedalus-effects.db",
        terminal_finished_at=LATER,
    )
    head = RepositoryHeadRevisionReceipt(
        expected_revision=REVISION,
        resolved_revision=REVISION,
        head_mode="detached",
        head_ref=None,
        resolution_source="head",
        head_sha256=_sha("git-head"),
        head_size=41,
        reference_path=None,
        reference_sha256=None,
        reference_size=None,
    )
    return resolution, verification, structure, completed, terminal, head


def _build(components=None) -> ProviderExecutablePreAdmissionReceipt:
    values = _components() if components is None else components
    return build_provider_executable_pre_admission(*values)


def test_pre_admission_binds_every_prerequisite_without_execution_authority():
    receipt = _build()

    payload = receipt.to_dict()
    assert payload["invocation_identity_bound"] is True
    assert payload["retention_effect_completed"] is True
    assert payload["source_revision_verified_against_git_head"] is True
    assert payload["broker_binding_prerequisites_composed"] is True
    assert payload["repository_bytes_executed"] is False
    assert payload["provider_execution_allowed"] is False
    assert payload["callback_seam_removed"] is False
    assert payload["broker_invocation_performed"] is False
    assert ProviderExecutablePreAdmissionReceipt.from_dict(payload) == receipt
    assert len(receipt.digest) == 64


def test_pre_admission_refuses_adapter_config_substitution():
    resolution, verification, structure, completed, terminal, head = _components()
    structure = dataclasses.replace(
        structure,
        adapter_config_sha256=_sha("substituted-config"),
    )

    with pytest.raises(
        ProviderExecutablePreAdmissionBindingError,
        match="adapter_config_sha256",
    ):
        _build((resolution, verification, structure, completed, terminal, head))


def test_pre_admission_refuses_identity_projection_substitution():
    resolution, verification, structure, completed, terminal, head = _components()
    structure = dataclasses.replace(
        structure,
        identity_sha256=_sha("substituted-identity-projection"),
    )

    with pytest.raises(
        ProviderExecutablePreAdmissionBindingError,
        match="identity_projection_sha256",
    ):
        _build((resolution, verification, structure, completed, terminal, head))


def test_pre_admission_refuses_stale_repository_head():
    resolution, verification, structure, completed, terminal, _head = _components()
    stale = "b" * 40
    head = RepositoryHeadRevisionReceipt(
        expected_revision=stale,
        resolved_revision=stale,
        head_mode="detached",
        head_ref=None,
        resolution_source="head",
        head_sha256=_sha("stale-head"),
        head_size=41,
        reference_path=None,
        reference_sha256=None,
        reference_size=None,
    )

    with pytest.raises(
        ProviderExecutablePreAdmissionBindingError,
        match="source revision mismatch",
    ):
        _build((resolution, verification, structure, completed, terminal, head))


def test_pre_admission_refuses_retained_receipt_substitution():
    resolution, verification, structure, completed, terminal, head = _components()
    other = _sha("other-provider-target-receipt")
    completed = dataclasses.replace(
        completed,
        provider_target_receipt_sha256=other,
        receipt_artifact_sha256=other,
    )

    with pytest.raises(
        ProviderExecutablePreAdmissionBindingError,
        match="retained provider target receipt mismatch",
    ):
        _build((resolution, verification, structure, completed, terminal, head))


def test_pre_admission_refuses_target_source_substitution():
    resolution, verification, structure, completed, terminal, head = _components()
    invoke = _structure_target(
        structure.invoke.target,
        source_sha256=_sha("substituted-invoke-source"),
        line=10,
    )
    structure = dataclasses.replace(structure, invoke=invoke)

    with pytest.raises(
        ProviderExecutablePreAdmissionBindingError,
        match="invoke target structure mismatch",
    ):
        _build((resolution, verification, structure, completed, terminal, head))


def test_pre_admission_from_dict_refuses_authority_escalation():
    payload = _build().to_dict()
    payload["provider_execution_allowed"] = True

    with pytest.raises(
        ProviderExecutablePreAdmissionShapeError,
        match="escalated claim: provider_execution_allowed",
    ):
        ProviderExecutablePreAdmissionReceipt.from_dict(payload)


def test_pre_admission_refuses_subclassed_component():
    resolution, verification, structure, completed, terminal, head = _components()

    class SubclassedResolution(ProviderInvocationResolutionReceipt):
        pass

    resolution = SubclassedResolution(**dataclasses.asdict(resolution))
    with pytest.raises(
        ProviderExecutablePreAdmissionShapeError,
        match="resolution must be exact ProviderInvocationResolutionReceipt",
    ):
        _build((resolution, verification, structure, completed, terminal, head))
