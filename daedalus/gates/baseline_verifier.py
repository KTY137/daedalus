"""Independent recomputation for Gate-0 monotonicity receipts."""
from __future__ import annotations

from .baseline import (
    GateBaseline,
    GateBaselineBindingError,
    GateMonotonicityReceipt,
    assess_gate0_monotonicity,
)
from .report import GateReport


class GateMonotonicityBlocked(GateBaselineBindingError):
    """The current report introduced one or more baseline regressions."""


def verify_gate0_monotonicity_receipt(
    receipt: GateMonotonicityReceipt,
    baseline: GateBaseline,
    current: GateReport,
    *,
    expected_baseline_sha256: str,
    current_source_tree_revision: str,
    require_monotonic: bool = False,
) -> GateMonotonicityReceipt:
    """Recompute every receipt field from the pinned baseline and report."""
    if not isinstance(receipt, GateMonotonicityReceipt):
        raise GateBaselineBindingError(
            "receipt must be GateMonotonicityReceipt"
        )
    recomputed = assess_gate0_monotonicity(
        baseline,
        current,
        expected_baseline_sha256=expected_baseline_sha256,
        current_source_tree_revision=current_source_tree_revision,
        assessment_id=receipt.assessment_id,
        assessed_at=receipt.assessed_at,
    )
    if receipt != recomputed:
        raise GateBaselineBindingError(
            "monotonicity receipt does not match recomputed evidence"
        )
    if require_monotonic and receipt.status != "passed":
        raise GateMonotonicityBlocked(
            "new Gate blockers: " + ", ".join(receipt.new_blockers)
        )
    return receipt


__all__ = [
    "GateMonotonicityBlocked",
    "verify_gate0_monotonicity_receipt",
]
