"""Trust-kernel contracts introduced through strangler-style package boundaries."""

from .approvals import (
    NominationReceipt,
    OwnerApproval,
    PromotionReceipt,
    validate_owner_approval,
)

__all__ = [
    "NominationReceipt",
    "OwnerApproval",
    "PromotionReceipt",
    "validate_owner_approval",
]
