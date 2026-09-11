"""Chip-owned adapters injected into the neutral Effect-Lease issuer."""

from __future__ import annotations

from daedalus.kernel.offload_lease import ChipExecutionPlanBinding

from .execution_plan import EdaExecutionPlan


def validate_eda_execution_plan(
    operation_plan: object,
    /,
) -> ChipExecutionPlanBinding:
    """Validate the existing exact EDA plan type and expose neutral fields."""

    if type(operation_plan) is not EdaExecutionPlan:
        raise TypeError(
            "acquire_chip_eda_lease() requires an exact EdaExecutionPlan"
        )
    return ChipExecutionPlanBinding(
        source_root=str(operation_plan.source_root),
        cwd=str(operation_plan.cwd),
        digest=operation_plan.digest,
    )

__all__ = ["validate_eda_execution_plan"]
