"""Machine-readable delivery gate reporting.

The gate package is a projection over canonical contracts and registries. It
must never become a second policy or workflow authority.
"""

from .evidence import (
    ArtifactEvidence,
    FaultMatrixEvidence,
    GateEvidenceIndex,
    OwnerDecisionEvidence,
    ReviewEvidence,
    RuntimeEnvelopeEvidence,
    WorkflowRunEvidence,
)
from .evidence_verifier import (
    assert_strict_exact_head,
    evidence_requirements_sha256,
    strict_mechanical_blockers,
)
from .report import GateReport, build_gate0_report, load_gate_report

__all__ = [
    "ArtifactEvidence",
    "FaultMatrixEvidence",
    "GateEvidenceIndex",
    "GateReport",
    "OwnerDecisionEvidence",
    "ReviewEvidence",
    "RuntimeEnvelopeEvidence",
    "WorkflowRunEvidence",
    "assert_strict_exact_head",
    "build_gate0_report",
    "evidence_requirements_sha256",
    "load_gate_report",
    "strict_mechanical_blockers",
]
