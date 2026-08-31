"""Pinned Hermes Agent userspace runtime behind Daedalus kernel authority.

Importing this package performs no I/O, opens no model connection and registers
no provider operation. Callers must explicitly construct exact source,
containment, gateway and broker subjects.
"""

from .configuration import (
    DEFAULT_HERMES_SOURCE,
    HERMES_ADAPTER_ID,
    HERMES_ADAPTER_VERSION,
    HERMES_OPERATION_ID,
    HERMES_RUNTIME_ID,
    HermesRuntimeConfig,
    HermesSandboxProfile,
)
from .context_provider import ContextFragment, ExplicitContextProvider
from .kernel_provider import HermesKernelProvider, build_hermes_runtime_metadata, register_hermes_runtime_operation
from .memory_provider import MemoryRecord, ReadOnlyMemoryProvider
from .runtime_adapter import HermesRuntimeAdapter, HermesRuntimeRequest, HermesRuntimeResult
from .session import hermes_runtime_session
from .tool_gateway import HermesGatewayDescriptor, HermesToolGatewayServer
from .tool_provider import DaedalusToolProvider, ToolOutcome, ToolSpec

__all__ = [
    "ContextFragment",
    "DEFAULT_HERMES_SOURCE",
    "DaedalusToolProvider",
    "ExplicitContextProvider",
    "HERMES_ADAPTER_ID",
    "HERMES_ADAPTER_VERSION",
    "HERMES_OPERATION_ID",
    "HERMES_RUNTIME_ID",
    "HermesGatewayDescriptor",
    "HermesKernelProvider",
    "HermesRuntimeAdapter",
    "HermesRuntimeConfig",
    "HermesRuntimeRequest",
    "HermesRuntimeResult",
    "HermesSandboxProfile",
    "HermesToolGatewayServer",
    "MemoryRecord",
    "ReadOnlyMemoryProvider",
    "ToolOutcome",
    "ToolSpec",
    "build_hermes_runtime_metadata",
    "register_hermes_runtime_operation",
    "hermes_runtime_session",
]
