"""Measured storage receipts must distinguish exactness from compression."""
from __future__ import annotations

from experiments.forest_v2.tensor_embeddings.encoding import TensorProductEncoder, default_spec
from experiments.forest_v2.tensor_embeddings.storage import (
    compare_exact_storage,
    numeric_scalar_count,
    storage_receipt,
)


def _tensor():
    return TensorProductEncoder(default_spec()).encode_candidate(
        "src/parser.py",
        "class Parser:\n    def parse_record(self, value): return value\n",
        blob="blob-parser",
        revision="r1",
    ).tensor


def test_receipts_count_actual_numeric_scalars_and_canonical_bytes() -> None:
    cp = _tensor()
    dense = cp.to_dense()
    tt = cp.to_tensor_train()
    assert numeric_scalar_count(dense) == 512
    assert numeric_scalar_count(cp) == cp.rank * (1 + 4 + 4 + 32)
    assert numeric_scalar_count(tt) == sum(
        left * mode * right for left, mode, right in tt.core_shapes
    )
    for tensor in (cp, dense, tt):
        receipt = storage_receipt(tensor)
        assert receipt.canonical_bytes == len(tensor.canonical_bytes())
        assert receipt.dense_equivalent_scalars == 512
        assert receipt.scalar_ratio_to_dense == receipt.numeric_scalars / 512


def test_exact_storage_comparison_reports_zero_error_without_compression_claim() -> None:
    result = compare_exact_storage(_tensor())
    assert result["same_tensor_claim"] == "exact-representation-equivalence-only"
    assert result["automatic_promotions"] == 0
    assert result["max_abs_error"]["cp_to_dense"] == 0.0
    assert result["max_abs_error"]["tt_to_dense"] <= 1e-12
    assert {item["representation"] for item in result["receipts"]} == {
        "cp",
        "dense",
        "tt",
    }
