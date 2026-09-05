from __future__ import annotations

import inspect

from daedalus.twin.relation_blocks import TypedRelationBlock
from experiments.tensor_gpu.csr_exact_int_predicate_gate import (
    SOURCE_BLOB_SHA,
    run_equivalence_gate,
)


def test_gate_is_bound_to_the_current_pre_fusion_constructor_shape() -> None:
    source = inspect.getsource(TypedRelationBlock.__post_init__)

    assert SOURCE_BLOB_SHA == "5911f42485fc1683c02686cdb7af908beab23f07"
    assert "if type(item) is not int:" in source
    assert "if previous_column < item < column_count:" in source
    assert "type(item) is int and previous_column < item < column_count" not in source


def test_exact_int_common_path_candidate_is_exhaustively_classification_equivalent() -> None:
    report = run_equivalence_gate(max_entries=5, column_count=3)

    assert report["status"] == "verified"
    assert report["claim"] == "semantic-equivalence-only"
    assert report["cases"] == 114_381
    assert report["mismatch_count"] == 0
    assert report["mismatches"] == []
