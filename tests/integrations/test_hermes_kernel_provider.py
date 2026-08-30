from __future__ import annotations

import time

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
from daedalus.runtimes.provider_executable_object_registry import ProviderExecutableObjectRegistry


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
    request = _request()
    payload = {"metadata": build_hermes_runtime_metadata(request)}
    with pytest.raises(HermesKernelProviderError, match="callback-bearing"):
        HermesKernelProvider.invoke_authenticated(payload=payload, callback=lambda: None)


def test_real_07d4_registry_accepts_fixed_closure_free_operation() -> None:
    registry = ProviderExecutableObjectRegistry()
    assert register_hermes_runtime_operation(registry) is registry
