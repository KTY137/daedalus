"""Fixed 07D4 provider operation for the pinned Hermes runtime.

No callback is accepted by the sealed operation. Nested tool effects traverse
the authenticated loopback descriptor embedded in the provider payload and are
executed by the caller-owned :class:`HermesToolGatewayServer`.
"""

from __future__ import annotations

from typing import Mapping, TypeVar

from .configuration import HERMES_OPERATION_ID
from .runtime_adapter import HermesRuntimeRequest, HermesRuntimeResult, execute_from_metadata


class HermesKernelProviderError(RuntimeError):
    pass


_T = TypeVar("_T")


def _payload_dict(payload: object) -> Mapping[str, object]:
    if hasattr(payload, "to_dict"):
        value = payload.to_dict()  # type: ignore[attr-defined]
    elif isinstance(payload, Mapping):
        value = payload
    else:
        raise HermesKernelProviderError("provider payload is not serializable")
    if not isinstance(value, Mapping):
        raise HermesKernelProviderError("provider payload projection is not an object")
    return value


def _request_metadata(payload: object) -> Mapping[str, object]:
    value = _payload_dict(payload)
    metadata = value.get("metadata")
    if not isinstance(metadata, Mapping):
        raise HermesKernelProviderError("provider payload metadata is absent")
    request = metadata.get("hermes_runtime_request")
    if not isinstance(request, Mapping):
        raise HermesKernelProviderError("authenticated Hermes runtime request is absent")
    HermesRuntimeRequest.from_metadata(request)
    return request


def _invoke_hermes_payload(payload: object) -> Mapping[str, object]:
    """Closure-free operation entrypoint resolved by the sealed registry."""

    return execute_from_metadata(_request_metadata(payload))


def _hermes_output_digests(value: object, payload: object) -> tuple[str, ...]:
    """Closure-free output verifier resolved independently by the registry."""

    if not isinstance(value, Mapping):
        raise HermesKernelProviderError("Hermes operation output is not an object")
    result = HermesRuntimeResult.from_dict(value)
    request = HermesRuntimeRequest.from_metadata(_request_metadata(payload))
    if result.request_id != request.request_id or result.task_id != request.task_id:
        raise HermesKernelProviderError("Hermes operation output identity mismatch")
    return result.output_digests


def register_hermes_runtime_operation(registry: _T) -> _T:
    """Register exactly one fixed Hermes operation on an existing registry."""

    from daedalus.runtimes.provider_executable_object_registry import ProviderRuntimeOperation

    operation = ProviderRuntimeOperation(
        operation_id=HERMES_OPERATION_ID,
        invoke=_invoke_hermes_payload,
        output_digests=_hermes_output_digests,
    )
    register = getattr(registry, "register", None)
    if not callable(register):
        raise HermesKernelProviderError("provider executable registry has no register method")
    register(operation)
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
        payload = broker_arguments.get("payload")
        if payload is None:
            raise HermesKernelProviderError("authenticated provider payload is required")
        _request_metadata(payload)
        from daedalus.runtimes.broker import run_runtime_provider

        return run_runtime_provider(**broker_arguments)
