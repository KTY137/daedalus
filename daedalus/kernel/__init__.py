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
    issue_effect_lease,
    verify_effect_lease,
)

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
    "issue_effect_lease",
    "verify_effect_lease",
]
