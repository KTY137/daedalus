"""Vendor-neutral runtime contracts and conformance surfaces.

Legacy runtime discovery remains import-compatible in
:mod:`daedalus.runtime_registry` while Gate-0 runtime responsibilities migrate
here strangler-style.
"""

from daedalus.schemas import (
    ConformanceCheck,
    RuntimeCapabilities,
    RuntimeConformanceReceipt,
    RuntimeManifest,
)

from .conformance import (
    EvidenceWriter,
    PythonFixtureRuntimeAdapter,
    RuntimeBindingError,
    RuntimeConformanceError,
    RuntimeEvidenceError,
    RuntimeFixtureAdapter,
    RuntimeProbeEvent,
    RuntimeProbeRequest,
    RuntimeProbeSession,
    RuntimeProbeTimeout,
    SubprocessRuntimeSession,
    run_runtime_conformance,
)

__all__ = [
    "ConformanceCheck",
    "EvidenceWriter",
    "PythonFixtureRuntimeAdapter",
    "RuntimeBindingError",
    "RuntimeCapabilities",
    "RuntimeConformanceError",
    "RuntimeConformanceReceipt",
    "RuntimeEvidenceError",
    "RuntimeFixtureAdapter",
    "RuntimeManifest",
    "RuntimeProbeEvent",
    "RuntimeProbeRequest",
    "RuntimeProbeSession",
    "RuntimeProbeTimeout",
    "SubprocessRuntimeSession",
    "run_runtime_conformance",
]
