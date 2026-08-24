"""Measured scalar/byte receipts for exact tensor storage representations."""
from __future__ import annotations

import math
from dataclasses import dataclass

from .algebra import to_dense
from .contracts import CPTensor, DenseTensor, TensorLike, TensorTrain


STORAGE_RECEIPT_SCHEMA = "forest-v2.tensor-storage-receipt/1"


def representation_name(tensor: TensorLike) -> str:
    if isinstance(tensor, CPTensor):
        return "cp"
    if isinstance(tensor, DenseTensor):
        return "dense"
    if isinstance(tensor, TensorTrain):
        return "tt"
    raise TypeError("unsupported tensor representation")


def numeric_scalar_count(tensor: TensorLike) -> int:
    """Count persisted floating-point values, excluding shape/JSON metadata."""

    if isinstance(tensor, DenseTensor):
        return len(tensor.flat_values)
    if isinstance(tensor, CPTensor):
        return sum(
            1 + len(term.plane) + len(term.role) + len(term.feature)
            for term in tensor.terms
        )
    if isinstance(tensor, TensorTrain):
        return sum(
            len(core) * len(core[0]) * len(core[0][0]) for core in tensor.cores
        )
    raise TypeError("unsupported tensor representation")


@dataclass(frozen=True)
class StorageReceipt:
    tensor_id: str
    spec_id: str
    representation: str
    numeric_scalars: int
    dense_equivalent_scalars: int
    canonical_bytes: int
    schema: str = STORAGE_RECEIPT_SCHEMA

    @property
    def scalar_ratio_to_dense(self) -> float:
        return self.numeric_scalars / self.dense_equivalent_scalars

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "tensor_id": self.tensor_id,
            "spec_id": self.spec_id,
            "representation": self.representation,
            "numeric_scalars": self.numeric_scalars,
            "dense_equivalent_scalars": self.dense_equivalent_scalars,
            "scalar_ratio_to_dense": self.scalar_ratio_to_dense,
            "canonical_bytes": self.canonical_bytes,
        }


def storage_receipt(tensor: TensorLike) -> StorageReceipt:
    if not isinstance(tensor, (CPTensor, DenseTensor, TensorTrain)):
        raise TypeError("unsupported tensor representation")
    return StorageReceipt(
        tensor_id=tensor.tensor_id,
        spec_id=tensor.spec_id,
        representation=representation_name(tensor),
        numeric_scalars=numeric_scalar_count(tensor),
        dense_equivalent_scalars=tensor.spec.dense_scalar_count,
        canonical_bytes=len(tensor.canonical_bytes()),
    )


def compare_exact_storage(tensor: CPTensor) -> dict[str, object]:
    """Receipt all exact forms and measure their dense reconstruction error."""

    if not isinstance(tensor, CPTensor):
        raise TypeError("compare_exact_storage expects a CPTensor")
    dense = tensor.to_dense()
    tt = tensor.to_tensor_train()
    dense_values = dense.flat_values
    tt_values = tt.to_dense().flat_values
    cp_values = to_dense(tensor).flat_values
    cp_error = max(
        (abs(left - right) for left, right in zip(cp_values, dense_values)),
        default=0.0,
    )
    tt_error = max(
        (abs(left - right) for left, right in zip(tt_values, dense_values)),
        default=0.0,
    )
    if not math.isfinite(cp_error) or not math.isfinite(tt_error):
        raise ValueError("storage comparison produced non-finite error")
    return {
        "schema": "forest-v2.tensor-storage-comparison/1",
        "same_tensor_claim": "exact-representation-equivalence-only",
        "receipts": [
            storage_receipt(value).to_dict() for value in (tensor, dense, tt)
        ],
        "max_abs_error": {"cp_to_dense": cp_error, "tt_to_dense": tt_error},
        "automatic_promotions": 0,
    }


__all__ = [
    "STORAGE_RECEIPT_SCHEMA",
    "StorageReceipt",
    "compare_exact_storage",
    "numeric_scalar_count",
    "representation_name",
    "storage_receipt",
]
