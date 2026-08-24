"""Frozen executable arm census for the diagnostic tensor experiment.

This tiny module contains names only.  Keeping the census independent of the
rankers and report validator avoids a dependency from candidate code into the
sealed evaluator while still giving the executable harness one exact contract.
The sealed evaluator intentionally owns its own copy; tests require equality.
"""
from __future__ import annotations


TENSOR_ARM_NAMES = (
    "flattened_cosine_same_scalars",
    "identity_contraction",
    "structured_contraction",
    "flattened_bilinear_same_kernel",
    "tensor_late_interaction",
    "plane_label_permutation",
    "role_label_permutation",
    "uniform_kernel",
)

BASELINE_ARM_NAMES = (
    "bm25",
    "random_uniform",
    "path_lexical",
    "recency_prior",
    "fusion_rrf",
)

REQUIRED_ARM_NAMES = TENSOR_ARM_NAMES + BASELINE_ARM_NAMES

REFERENCE_ARM_NAME = "flattened_cosine_same_scalars"
PRIMARY_ARM_NAME = "structured_contraction"
NEGATIVE_CONTROL_NAMES = (
    "plane_label_permutation",
    "role_label_permutation",
    "uniform_kernel",
)
REQUIRED_COMPARISON_KEYS = tuple(
    (name, REFERENCE_ARM_NAME, "reciprocal_rank")
    for name in REQUIRED_ARM_NAMES
    if name != REFERENCE_ARM_NAME
) + tuple(
    (PRIMARY_ARM_NAME, control, "reciprocal_rank")
    for control in NEGATIVE_CONTROL_NAMES
)


__all__ = [
    "BASELINE_ARM_NAMES",
    "NEGATIVE_CONTROL_NAMES",
    "PRIMARY_ARM_NAME",
    "REFERENCE_ARM_NAME",
    "REQUIRED_ARM_NAMES",
    "REQUIRED_COMPARISON_KEYS",
    "TENSOR_ARM_NAMES",
]
