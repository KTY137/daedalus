"""Fixed 07D4 provider operation for the pinned Hermes runtime.

No callback is accepted by the sealed operation. Nested tool effects traverse
the authenticated loopback descriptor embedded in the provider payload and are
executed by the caller-owned :class:`HermesToolGatewayServer`.
"""

from __future__ import annotations

from typing import Mapping

from .configuration import HERMES_OPERATION_ID
from .runtime_adapter import HermesRuntimeRequest, HermesRuntimeResult, execute_from_metadata


class HermesKernelProviderError(RuntimeError):
    pass


def _payload_dict(payload: object) -> object:
    """Accept the current broker's already-canonical payload body only."""

    if not callable(getattr(payload, "get", None)):
        raise RuntimeError("provider payload body is not an object")
    return payload


def _request_metadata(payload: object) -> object:
    value = _payload_dict(payload)
    request = value.get("hermes_runtime_request")
    if not callable(getattr(request, "get", None)):
        raise RuntimeError("authenticated Hermes runtime request is absent")
    runtime_adapter = __import__(
        "daedalus.integrations.hermes.runtime_adapter",
        fromlist=("HermesRuntimeRequest",),
    )
    getattr(runtime_adapter, "HermesRuntimeRequest").from_metadata(request)
    return request


def _invoke_hermes_payload(payload: object) -> Mapping[str, object]:
    """Closure-free operation entrypoint resolved by the sealed registry."""

    runtime_adapter = __import__(
        "daedalus.integrations.hermes.runtime_adapter",
        fromlist=("execute_from_metadata",),
    )
    return getattr(runtime_adapter, "execute_from_metadata")(_request_metadata(payload))


def _hermes_output_digests(value: object, payload: object) -> tuple[str, ...]:
    """Closure-free output verifier resolved independently by the registry."""

    if not callable(getattr(value, "get", None)):
        raise RuntimeError("Hermes operation output is not an object")
    runtime_adapter = __import__(
        "daedalus.integrations.hermes.runtime_adapter",
        fromlist=("HermesRuntimeRequest", "HermesRuntimeResult"),
    )
    result = getattr(runtime_adapter, "HermesRuntimeResult").from_dict(value)
    request = getattr(runtime_adapter, "HermesRuntimeRequest").from_metadata(
        _request_metadata(payload)
    )
    if result.request_id != request.request_id or result.task_id != request.task_id:
        raise RuntimeError("Hermes operation output identity mismatch")
    return result.output_digests


def register_hermes_runtime_operation(
    registry: object,
    *,
    pre_admission: object,
) -> object:
    """Bind fixed Hermes functions to the current receipt-backed registry.

    The 07D4 executable registry owns the operation identity through the
    pre-admission receipt; this helper deliberately cannot manufacture that
    receipt or inject a callback.
    """

    from daedalus.runtimes.provider_executable_object_registry import (
        ProviderExecutableObjectRegistry,
    )
    from daedalus.runtimes.provider_executable_pre_admission import (
        ProviderExecutablePreAdmissionReceipt,
    )

    if type(registry) is not ProviderExecutableObjectRegistry:
        raise HermesKernelProviderError(
            "provider executable registry must be exact ProviderExecutableObjectRegistry"
        )
    if type(pre_admission) is not ProviderExecutablePreAdmissionReceipt:
        raise HermesKernelProviderError(
            "Hermes operation requires an exact executable pre-admission receipt"
        )
    if pre_admission.entrypoint_id != HERMES_OPERATION_ID:
        raise HermesKernelProviderError("Hermes pre-admission names a different entrypoint")
    registry.register(
        pre_admission,
        invoke=_invoke_hermes_payload,
        output_digests=_hermes_output_digests,
    )
    return registry


def build_hermes_runtime_metadata(
    request: HermesRuntimeRequest,
    *,
    existing: Mapping[str, object] | None = None,
) -> dict[str, object]:
    metadata = dict(existing or {})
    if "hermes_runtime_request" in metadata:
        raise HermesKernelProviderError("Hermes runtime request metadata already exists")
    metadata["hermes_runtime_request"] = request.to_metadata()
    metadata["hermes_operation_id"] = HERMES_OPERATION_ID
    metadata["hermes_authority_owner"] = "daedalus-kernel"
    return metadata


class HermesKernelProvider:
    """Thin caller facade over the callback-free canonical broker.

    The facade neither issues runtime authority nor creates leases. Callers
    must pass the same authenticated subjects required by ``run_runtime_provider``.
    """

    operation_id = HERMES_OPERATION_ID

    @staticmethod
    def invoke_authenticated(**broker_arguments: object) -> object:
        banned = {"invoke", "callback", "output_digests", "tool_invoker"} & set(broker_arguments)
        if banned:
            raise HermesKernelProviderError(
                f"callback-bearing arguments are forbidden by the sealed Hermes provider: {sorted(banned)}"
            )
        entrypoint_id = broker_arguments.pop("entrypoint_id", HERMES_OPERATION_ID)
        if entrypoint_id != HERMES_OPERATION_ID:
            raise HermesKernelProviderError("Hermes provider targets a different entrypoint")
        payload = broker_arguments.get("invocation_payload")
        if payload is None:
            raise HermesKernelProviderError("authenticated provider payload is required")
        from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload

        if type(payload) is not ProviderInvocationPayload:
            raise HermesKernelProviderError(
                "authenticated provider payload must be exact ProviderInvocationPayload"
            )
        _request_metadata(payload.body)
        from daedalus.runtimes.broker import run_runtime_provider

        return run_runtime_provider(entrypoint_id, **broker_arguments)
