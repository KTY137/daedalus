"""Machine-readable delivery gate reporting.

The gate package is a projection over canonical contracts and registries. It
must never become a second policy or workflow authority.
"""

from . import trust_bundle as _trust_bundle
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
from .release import (
    Gate0ReleaseBindingError,
    Gate0ReleaseBlocked,
    Gate0ReleaseError,
    Gate0ReleaseReceipt,
    Gate0ReleaseSignatureError,
    issue_gate0_release_receipt,
    load_gate0_release_receipt,
    load_strict_gate_report,
    parse_gate0_release_receipt,
    strict_gate_report_sha256,
    validate_strict_gate_report_payload,
    verify_gate0_release_receipt,
)
from .report import GateReport, build_gate0_report, load_gate_report
from .trust_bundle import (
    EvidenceTrustBundle,
    EvidenceTrustBundleBindingError,
    EvidenceTrustBundleError,
    EvidenceTrustBundleSignatureError,
    WorkflowDefinitionAnchor,
    assert_strict_exact_head_with_bundle,
    issue_evidence_trust_bundle,
    verify_evidence_trust_bundle,
    workflow_definition_sha256,
)
from .trust_bundle_io import (
    load_evidence_trust_bundle,
    parse_evidence_trust_bundle,
)

# Compatibility strangler: importing ``daedalus.gates.trust_bundle`` still
# exposes the historical parser/loader names, but normal package initialization
# replaces their permissive wire behavior with the strict supported boundary.
_trust_bundle.parse_evidence_trust_bundle = parse_evidence_trust_bundle
_trust_bundle.load_evidence_trust_bundle = load_evidence_trust_bundle

__all__ = [
    "ArtifactEvidence",
    "EvidenceTrustBundle",
    "EvidenceTrustBundleBindingError",
    "EvidenceTrustBundleError",
    "EvidenceTrustBundleSignatureError",
    "FaultMatrixEvidence",
    "Gate0ReleaseBindingError",
    "Gate0ReleaseBlocked",
    "Gate0ReleaseError",
    "Gate0ReleaseReceipt",
    "Gate0ReleaseSignatureError",
    "GateEvidenceIndex",
    "GateReport",
    "OwnerDecisionEvidence",
    "ReviewEvidence",
    "RuntimeEnvelopeEvidence",
    "WorkflowDefinitionAnchor",
    "WorkflowRunEvidence",
    "assert_strict_exact_head",
    "assert_strict_exact_head_with_bundle",
    "build_gate0_report",
    "evidence_requirements_sha256",
    "issue_evidence_trust_bundle",
    "issue_gate0_release_receipt",
    "load_evidence_trust_bundle",
    "load_gate0_release_receipt",
    "load_gate_evidence_index",
    "load_gate_report",
    "load_strict_gate_report",
    "parse_evidence_trust_bundle",
    "parse_gate0_release_receipt",
    "parse_gate_evidence_index",
    "strict_gate_report_sha256",
    "strict_mechanical_blockers",
    "validate_strict_gate_report_payload",
    "verify_evidence_trust_bundle",
    "verify_gate0_release_receipt",
    "workflow_definition_sha256",
]
