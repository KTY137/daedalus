"""Compatibility import for the canonical runtime fault matrix contracts.

The implementation moved to :mod:`daedalus.runtimes.fault_matrix` so the
responsibility is explicit while existing imports remain stable during the
strangler migration.
"""
from .fault_matrix import (
    RUNTIME_FAULT_CATALOG,
    RuntimeFaultCatalog,
    RuntimeFaultMatrix,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
    RuntimeFaultVerification,
    build_runtime_fault_matrix,
    verify_runtime_fault_matrix,
)

__all__ = [
    "RUNTIME_FAULT_CATALOG",
    "RuntimeFaultCatalog",
    "RuntimeFaultMatrix",
    "RuntimeFaultObservation",
    "RuntimeFaultScenario",
    "RuntimeFaultVerification",
    "build_runtime_fault_matrix",
    "verify_runtime_fault_matrix",
]
