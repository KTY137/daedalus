from __future__ import annotations

import time
from hashlib import sha256
from pathlib import Path

import pytest

from daedalus.integrations.hermes.configuration import HermesRuntimeConfig
from daedalus.integrations.hermes.context_provider import ExplicitContextProvider
from daedalus.integrations.hermes.kernel_provider import (
    HermesKernelProvider,
    HermesKernelProviderError,
    build_hermes_runtime_metadata,
    register_hermes_runtime_operation,
)
from daedalus.integrations.hermes.memory_provider import ReadOnlyMemoryProvider
from daedalus.integrations.hermes.protocol import canonical_sha256
from daedalus.integrations.hermes.runtime_adapter import HermesRuntimeRequest
from daedalus.integrations.hermes.tool_gateway import HermesGatewayDescriptor
from daedalus.runtimes.provider.executable_object_registry import ProviderExecutableObjectRegistry
from daedalus.runtimes.provider.executable_pre_admission import ProviderExecutablePreAdmissionReceipt


def _sha(label: str) -> str:
    return canonical_sha256({"label": label})


def _pre_admission() -> ProviderExecutablePreAdmissionReceipt:
    from daedalus.integrations.hermes import kernel_provider

    source = Path(kernel_provider.__file__).read_bytes()
    source_sha256 = sha256(source).hexdigest()
    return ProviderExecutablePreAdmissionReceipt(
        source_revision="a" * 40,
        resolution_sha256=_sha("resolution"),
        verification_sha256=_sha("verification"),
        structure_sha256=_sha("structure"),
        completed_retention_sha256=_sha("retention"),
        retention_effect_terminal_sha256=_sha("retention-terminal"),
        repository_head_sha256=_sha("repository-head"),
        provider_id="provider-hermes",
        adapter_id="daedalus-hermes",
        implementation_id="hermes-oneshot-v1",
        entrypoint_id=HermesKernelProvider.operation_id,
        runtime_id="hermes-agent",
        execution_id="execution-hermes",
        idempotency_key="idempotency-hermes",
        invocation_authority_sha256=_sha("invocation-authority"),
        invocation_contract_sha256=_sha("invocation-contract"),
        invocation_subject_sha256=_sha("invocation-subject"),
        invocation_identity_projection_sha256=_sha("identity-projection"),
        identity_registry_sha256=_sha("identity-registry"),
        identity_descriptor_sha256=_sha("identity-descriptor"),
        target_authority_sha256=_sha("target-authority"),
        target_projection_sha256=_sha("target-projection"),
        target_manifest_sha256=_sha("target-manifest"),
        target_descriptor_sha256=_sha("target-descriptor"),
        adapter_artifact_sha256=_sha("adapter-artifact"),
        adapter_config_sha256=_sha("adapter-config"),
        lease_sha256=_sha("lease"),
        invoke_target="daedalus.integrations.hermes.kernel_provider:_invoke_hermes_payload",
        invoke_source_sha256=source_sha256,
        output_digests_target="daedalus.integrations.hermes.kernel_provider:_hermes_output_digests",
        output_digests_source_sha256=source_sha256,
    )


def _request() -> HermesRuntimeRequest:
    scope_digest = canonical_sha256([])
    descriptor = HermesGatewayDescriptor.create(
        host="127.0.0.1",
        port=31337,
        token_file="/tmp/daedalus-hermes-test-token",
        request_id="request-kernel",
        task_id="task-kernel",
        tool_scope_digest=scope_digest,
        max_calls=0,
        expires_at_ns=time.time_ns() + 60_000_000_000,
    )
    return HermesRuntimeRequest(
        request_id="request-kernel",
        task_id="task-kernel",
        workspace="/tmp/daedalus-hermes-workspace",
        system_prompt="system",
        user_prompt="user",
        config=HermesRuntimeConfig(
            checkout_root="/tmp/daedalus-hermes-checkout",
            python_executable="python",
        ),
        context=ExplicitContextProvider(),
        memory=ReadOnlyMemoryProvider(),
        tools=(),
        gateway=descriptor,
    )


def test_runtime_metadata_is_owned_by_daedalus_kernel() -> None:
    request = _request()
    metadata = build_hermes_runtime_metadata(request, existing={"caller": "test"})
    assert metadata["caller"] == "test"
    assert metadata["hermes_authority_owner"] == "daedalus-kernel"
    assert metadata["hermes_runtime_request"] == request.to_metadata()
    with pytest.raises(HermesKernelProviderError):
        build_hermes_runtime_metadata(request, existing=metadata)


def test_provider_facade_rejects_callback_bypass_before_broker() -> None:
    with pytest.raises(HermesKernelProviderError, match="callback-bearing"):
        HermesKernelProvider.invoke_authenticated(callback=lambda: None)


def test_real_07d4_registry_accepts_fixed_closure_free_operation() -> None:
    from daedalus.integrations.hermes import kernel_provider

    registry = ProviderExecutableObjectRegistry(Path(__file__).resolve().parents[2])
    pre_admission = _pre_admission()
    assert register_hermes_runtime_operation(registry, pre_admission=pre_admission) is registry
    entry = next(iter(registry._entries.values()))
    assert entry.invoke is kernel_provider._invoke_hermes_payload
    assert entry.output_digests is kernel_provider._hermes_output_digests
    assert entry.invoke.__closure__ is None
    assert entry.output_digests.__closure__ is None
