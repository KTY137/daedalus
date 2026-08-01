"""Machine-readable delivery gate reporting.

The gate package is a projection over canonical contracts and registries. It
must never become a second policy or workflow authority.
"""

from .report import GateReport, build_gate0_report, load_gate_report

__all__ = ["GateReport", "build_gate0_report", "load_gate_report"]
