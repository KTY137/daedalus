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
from .evidence_io import load_gate_evidence_index, parse_gate_evidence_index
from .evidence_verifier import (
    assert_strict_exact_head,
    evidence_requirements_sha256,
    strict_mechanical_blockers,
)
from .release import Gate0ReleaseReport, assemble_gate0_release_report
from .release_verifier import (
    assert_gate0_release_report,
    gate0_release_verification_blockers,
)
from .report import GateReport, build_gate0_report, load_gate_report

__all__ = [
    "ArtifactEvidence",
    "FaultMatrixEvidence",
    "Gate0ReleaseReport",
    "GateEvidenceIndex",
    "GateReport",
    "OwnerDecisionEvidence",
    "ReviewEvidence",
    "RuntimeEnvelopeEvidence",
    "WorkflowRunEvidence",
    "assemble_gate0_release_report",
    "assert_gate0_release_report",
    "assert_strict_exact_head",
    "build_gate0_report",
    "evidence_requirements_sha256",
    "gate0_release_verification_blockers",
    "load_gate_evidence_index",
    "load_gate_report",
    "parse_gate_evidence_index",
    "strict_mechanical_blockers",
]
