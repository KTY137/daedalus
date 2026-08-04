"""Trust-kernel capabilities introduced through Gate-0 work packets.

Legacy modules remain import-compatible while new security boundaries are
added here incrementally. This package is not a second contract authority;
canonical wire contracts remain in :mod:`daedalus.schemas`.
"""

from .contracts import OwnerApproval
from .approvals import (
    ApprovalBindingMismatch,
    ApprovalExpired,
    ConsumedOwnerApproval,
    ApprovalLedger,
    ApprovalReplay,
    ApprovalSignatureError,
    ApprovalStateError,
    ApprovalExpectation,
    VerifiedOwnerApproval,
    issue_owner_approval,
    verify_owner_approval,
)

__all__ = [
    "ApprovalBindingMismatch",
    "ApprovalExpired",
    "ConsumedOwnerApproval",
    "ApprovalExpectation",
    "ApprovalLedger",
    "ApprovalReplay",
    "ApprovalSignatureError",
    "ApprovalStateError",
    "OwnerApproval",
    "VerifiedOwnerApproval",
    "issue_owner_approval",
    "verify_owner_approval",
]

from .contracts import EffectLease, EffectLeaseRequest
from .effects import (
    EffectExecutionRequest,
    EffectLeaseBindingMismatch,
    EffectLeaseConcurrencyError,
    EffectLeaseError,
    EffectLeaseExpired,
    EffectLeaseLedger,
    EffectLeaseReplay,
    EffectLeaseScopeError,
    EffectLeaseSignatureError,
    EffectLeaseStateError,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
    LeasedEffectAuthorization,
    issue_effect_lease,
    verify_effect_lease,
)
from .authorization import NonRuntimeEffectAuthorization

__all__ += [
    "EffectExecutionRequest",
    "EffectLease",
    "EffectLeaseBindingMismatch",
    "EffectLeaseConcurrencyError",
    "EffectLeaseError",
    "EffectLeaseExpired",
    "EffectLeaseLedger",
    "EffectLeaseReplay",
    "EffectLeaseRequest",
    "EffectLeaseScopeError",
    "EffectLeaseSignatureError",
    "EffectLeaseStateError",
    "EffectStartResult",
    "EffectTerminalReceipt",
    "LeasedEffectStartReceipt",
    "LeasedEffectAuthorization",
    "NonRuntimeEffectAuthorization",
    "issue_effect_lease",
    "verify_effect_lease",
]

from .fourfold_evidence import (
    FOURFOLD_EVIDENCE_SCHEMA,
    FOURFOLD_EVALUATOR,
    FourfoldEvidenceExpectation,
    FourfoldEvidenceMismatch,
    assemble_fourfold_evidence_packet,
    verify_fourfold_evidence_packet,
)

__all__ += [
    "FOURFOLD_EVIDENCE_SCHEMA",
    "FOURFOLD_EVALUATOR",
    "FourfoldEvidenceExpectation",
    "FourfoldEvidenceMismatch",
    "assemble_fourfold_evidence_packet",
    "verify_fourfold_evidence_packet",
]

from .promotion import (
    PromotionAuthorization,
    PromotionAuthorizationError,
    authorize_persisted_promotion,
    authorize_promotion,
    candidate_batch_sha256,
    resolve_live_target_revision,
)
from .promotion_effects import (
    PROMOTION_EFFECTS,
    PROMOTION_ENTRYPOINT_ID,
    PROMOTION_GUARD_CONTRACTS,
    PROMOTION_TARGET,
    PromotionEffectBindingMismatch,
    PromotionEffectCapability,
)
from .promotion_effect_replay import (
    PromotionEffectReplayError,
    PromotionEffectReplayResult,
    inspect_promotion_effect_execution,
)
from .promotion_execution import (
    PromotionExecutionBeginResult,
    PromotionExecutionBindingMismatch,
    PromotionExecutionCompletion,
    PromotionExecutionError,
    PromotionExecutionLedger,
    PromotionExecutionReceipt,
    PromotionExecutionReplay,
    PromotionExecutionStart,
    PromotionExecutionStateError,
)
from .promotion_reconciliation import (
    ExpectedPromotionEffectTerminal,
    PromotionReconciliationDisposition,
    PromotionReconciliationError,
    PromotionReconciliationProjection,
    inspect_promotion_reconciliation,
)
from .promotion_replay import (
    PromotionReplayProjectionMismatch,
    inspect_promotion_execution,
)
from .runtime_conformance import (
    RecordedObservation,
    RuntimeConformanceError,
    assemble_recorded_conformance,
    verify_current_conformance,
)
from .sandbox import (
    DockerSandboxPolicy,
    SandboxExecutionReceipt,
    SandboxMount,
    SandboxPolicyError,
    run_in_docker_sandbox,
)
from .source_trees import (
    MANDATORY_IGNORED_ROOTS,
    SourceTreeCaptureError,
    SourceTreeCorruptionError,
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
    StoredSourceTree,
)
from .attempts import (
    AttemptBeginResult,
    AttemptBindingMismatch,
    AttemptCompletion,
    AttemptLedger,
    AttemptLifecycleError,
    AttemptReplay,
    AttemptStartRecord,
    AttemptStateError,
    AttemptTerminalReceipt,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
    PreparedAttempt,
)

__all__ += [
    "PromotionAuthorization",
    "PromotionAuthorizationError",
    "authorize_persisted_promotion",
    "authorize_promotion",
    "candidate_batch_sha256",
    "resolve_live_target_revision",
    "PROMOTION_EFFECTS",
    "PROMOTION_ENTRYPOINT_ID",
    "PROMOTION_GUARD_CONTRACTS",
    "PROMOTION_TARGET",
    "PromotionEffectBindingMismatch",
    "PromotionEffectCapability",
    "PromotionEffectReplayError",
    "PromotionEffectReplayResult",
    "inspect_promotion_effect_execution",
    "PromotionExecutionBeginResult",
    "PromotionExecutionBindingMismatch",
    "PromotionExecutionCompletion",
    "PromotionExecutionError",
    "PromotionExecutionLedger",
    "PromotionExecutionReceipt",
    "PromotionExecutionReplay",
    "PromotionExecutionStart",
    "PromotionExecutionStateError",
    "ExpectedPromotionEffectTerminal",
    "PromotionReconciliationDisposition",
    "PromotionReconciliationError",
    "PromotionReconciliationProjection",
    "inspect_promotion_reconciliation",
    "PromotionReplayProjectionMismatch",
    "inspect_promotion_execution",
    "RecordedObservation",
    "RuntimeConformanceError",
    "assemble_recorded_conformance",
    "verify_current_conformance",
    "DockerSandboxPolicy",
    "SandboxExecutionReceipt",
    "SandboxMount",
    "SandboxPolicyError",
    "run_in_docker_sandbox",
    "MANDATORY_IGNORED_ROOTS",
    "SourceTreeCaptureError",
    "SourceTreeCorruptionError",
    "SourceTreeEntry",
    "SourceTreeManifest",
    "SourceTreeStore",
    "SourceTreeStoreError",
    "StoredSourceTree",
    "AttemptBeginResult",
    "AttemptBindingMismatch",
    "AttemptCompletion",
    "AttemptLedger",
    "AttemptLifecycleError",
    "AttemptReplay",
    "AttemptStartRecord",
    "AttemptStateError",
    "AttemptTerminalReceipt",
    "AttemptWorkspaceError",
    "IsolatedAttemptCoordinator",
    "PreparedAttempt",
]
