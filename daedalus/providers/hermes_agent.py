"""Public provider seam for the pinned Hermes Agent userspace runtime.

This module deliberately re-exports only the fixed, callback-free registration
and caller facade. It does not register the operation or start a worker on
import.
"""

from daedalus.integrations.hermes.configuration import HERMES_OPERATION_ID, HERMES_RUNTIME_ID
from daedalus.integrations.hermes.kernel_provider import (
    HermesKernelProvider,
    build_hermes_runtime_metadata,
    register_hermes_runtime_operation,
)

__all__ = [
    "HERMES_OPERATION_ID",
    "HERMES_RUNTIME_ID",
    "HermesKernelProvider",
    "build_hermes_runtime_metadata",
    "register_hermes_runtime_operation",
]
