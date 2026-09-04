from __future__ import annotations

import runpy
from pathlib import Path

import pytest

BASELINE_PATH = (
    Path(__file__).parents[2]
    / "experiments"
    / "tensor_gpu"
    / "cpu_bitset_baseline.py"
)
_NAMESPACE = runpy.run_path(str(BASELINE_PATH))
ProbeCase = _NAMESPACE["ProbeCase"]
_block_from_masks = _NAMESPACE["_block_from_masks"]
build_boolean_case = _NAMESPACE["build_boolean_case"]
compose_packed_rows = _NAMESPACE["compose_packed_rows"]
execute_bitset = _NAMESPACE["execute_bitset"]
pack_rows = _NAMESPACE["pack_rows"]
run_probe = _NAMESPACE["run_probe"]
BooleanSemiring = _NAMESPACE["BooleanSemiring"]
MAX_REPEATS = _NAMESPACE["MAX_REPEATS"]
MAX_WARMUP = _NAMESPACE["MAX_WARMUP"]


def _case() -> object:
    return ProbeCase(
        size=8,
        density=0.25,
        repeats=2,
        warmup=1,
        max_device_mib=64,
    )


def test_pack_rows_preserves_exact_csr_support() -> None:
    left, _, _ = build_boolean_case(_case())
    masks = pack_rows(left)

    assert len(masks) == len(left.row_axis.labels)
    for row, mask in enumerate(masks):
        expected = {
            left.column_indices[position]
            for position in range(left.row_offsets[row], left.row_offsets[row + 1])
        }
        actual = {
            column
            for column in range(len(left.column_axis.labels))
            if mask & (1 << column)
        }
        assert actual == expected


def test_packed_boolean_composition_matches_stdlib_oracle() -> None:
    case = _case()
    left, right, _ = build_boolean_case(case)
    operations = _NAMESPACE["exact_reference_operation_count"](left, right)
    oracle = left.matmul(
        right,
        BooleanSemiring(),
        relation="cpu_bitset_composed",
        max_operations=operations,
    )
    execution = execute_bitset(
        left,
        right,
        repeats=case.repeats,
        warmup=case.warmup,
    )

    assert tuple(execution.block.iter_entries()) == tuple(oracle.iter_entries())
    assert execution.block.digest == oracle.digest
    assert execution.validate_ms >= 0.0
    assert len(execution.kernel_ms) == case.repeats
    assert all(value >= 0.0 for value in execution.kernel_ms)


def test_execute_bitset_validates_packed_rows_once_outside_timed_kernel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = ProbeCase(
        size=8,
        density=0.25,
        repeats=5,
        warmup=3,
        max_device_mib=64,
    )
    left, right, _ = build_boolean_case(case)
    globals_map = execute_bitset.__globals__
    original = globals_map["_validate_packed_rows"]
    calls = 0

    def counted(left_rows: object, right_rows: object) -> None:
        nonlocal calls
        calls += 1
        original(left_rows, right_rows)

    monkeypatch.setitem(globals_map, "_validate_packed_rows", counted)
    execution = execute_bitset(
        left,
        right,
        repeats=case.repeats,
        warmup=case.warmup,
    )

    assert calls == 1
    assert len(execution.kernel_ms) == 5


def test_compose_packed_rows_keeps_strict_direct_call_validation() -> None:
    with pytest.raises(ValueError, match="non-negative integers"):
        compose_packed_rows((-1,), (1,))
    with pytest.raises(ValueError, match="missing right row"):
        compose_packed_rows((1 << 3,), (1, 2, 4))


def test_execute_bitset_reuses_probe_repeat_and_warmup_bounds() -> None:
    left, right, _ = build_boolean_case(_case())
    for repeats, warmup in (
        (0, 0),
        (MAX_REPEATS + 1, 0),
        (1, -1),
        (1, MAX_WARMUP + 1),
    ):
        with pytest.raises(ValueError):
            execute_bitset(left, right, repeats=repeats, warmup=warmup)


def test_block_reconstruction_refuses_out_of_range_bits() -> None:
    case = _case()
    left, right, _ = build_boolean_case(case)
    with pytest.raises(ValueError, match="out-of-range"):
        _block_from_masks(
            left,
            right,
            (1 << case.size,) + (0,) * (case.size - 1),
            relation="cpu_bitset_composed",
        )


def test_probe_is_diagnostic_only_and_verifies_small_case() -> None:
    report = run_probe((_case(),))

    assert report["schema"] == "daedalus-tensor-cpu-bitset-baseline/1"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["semantic_scope"] == "Boolean relation support only"
    assert report["runtime"]["int_bits_per_digit"] > 0
    assert len(report["cases"]) == 1

    result = report["cases"][0]
    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["correctness"] == {
        "cpu_oracle_executed": True,
        "boolean_support_equal": True,
    }
    assert result["cpu_bitset"]["validate_ms"] >= 0.0
    assert result["cpu_bitset"]["output_entries"] == result["cpu_reference"]["output_entries"]
    assert result["cpu_bitset"]["digest"] == result["cpu_reference"]["digest"]


def test_probe_bounds_case_collection() -> None:
    case = _case()
    for cases in ((), (case,) * 33):
        with pytest.raises(ValueError):
            run_probe(cases)
