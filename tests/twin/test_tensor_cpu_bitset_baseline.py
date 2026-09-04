from __future__ import annotations

import importlib

import pytest

_BASELINE = importlib.import_module("experiments.tensor_gpu.cpu_bitset_baseline")
_CONTRACT = importlib.import_module("experiments.tensor_gpu.boolean_probe_contract")
ProbeCase = _BASELINE.ProbeCase
_block_from_csr_support = _BASELINE._block_from_csr_support
_block_from_masks = _BASELINE._block_from_masks
_csr_support_from_masks = _BASELINE._csr_support_from_masks
_measure_repeated = _BASELINE._measure_repeated
build_boolean_case = _BASELINE.build_boolean_case
compose_packed_rows = _BASELINE.compose_packed_rows
execute_bitset = _BASELINE.execute_bitset
pack_rows = _BASELINE.pack_rows
run_probe = _BASELINE.run_probe
BooleanSemiring = _BASELINE.BooleanSemiring
MAX_REPEATS = _BASELINE.MAX_REPEATS
MAX_WARMUP = _BASELINE.MAX_WARMUP


def _case() -> object:
    return ProbeCase(
        size=8,
        density=0.25,
        repeats=2,
        warmup=1,
        max_device_mib=64,
    )


def test_baseline_uses_the_shared_probe_case_contract() -> None:
    assert _BASELINE.ProbeCase is _CONTRACT.ProbeCase
    assert _BASELINE.build_boolean_case is _CONTRACT.build_boolean_case
    assert _BASELINE.estimate_dense_device_bytes is _CONTRACT.estimate_dense_device_bytes
    assert _BASELINE.exact_reference_operation_count is _CONTRACT.exact_reference_operation_count


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
    operations = _BASELINE.exact_reference_operation_count(left, right)
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
    assert execution.support_decode_ms >= 0.0
    assert execution.block_construct_ms >= 0.0
    assert execution.canonicalize_ms == (
        execution.support_decode_ms + execution.block_construct_ms
    )
    assert len(execution.kernel_ms) == case.repeats
    assert all(value >= 0.0 for value in execution.kernel_ms)


def test_repeated_measurement_uses_equal_warmup_and_sample_counts() -> None:
    calls = 0

    def operation() -> int:
        nonlocal calls
        calls += 1
        return calls

    result, samples = _measure_repeated(operation, repeats=4, warmup=3)

    assert calls == 7
    assert result == 7
    assert len(samples) == 4
    assert all(value >= 0.0 for value in samples)


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


def test_repeated_measurement_reuses_probe_repeat_and_warmup_bounds() -> None:
    for repeats, warmup in (
        (0, 0),
        (MAX_REPEATS + 1, 0),
        (1, -1),
        (1, MAX_WARMUP + 1),
    ):
        with pytest.raises(ValueError):
            _measure_repeated(lambda: 1, repeats=repeats, warmup=warmup)


def test_support_decode_rebuilds_exact_boolean_csr_without_value_accumulator() -> None:
    case = _case()
    left, right, _ = build_boolean_case(case)
    masks = compose_packed_rows(pack_rows(left), pack_rows(right))

    row_offsets, column_indices = _csr_support_from_masks(left, right, masks)
    rebuilt = _block_from_csr_support(
        left,
        right,
        row_offsets,
        column_indices,
        relation="cpu_bitset_composed",
    )
    direct = _block_from_masks(
        left,
        right,
        masks,
        relation="cpu_bitset_composed",
    )

    assert rebuilt.row_offsets == row_offsets
    assert rebuilt.column_indices == column_indices
    assert rebuilt.values == (True,) * len(column_indices)
    assert rebuilt.digest == direct.digest


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

    assert report["schema"] == "daedalus-tensor-cpu-bitset-baseline/3"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["semantic_scope"] == "Boolean relation support only"
    assert "same warmup/repeat policy" in report["measurement_contract"]
    assert report["runtime"]["int_bits_per_digit"] > 0
    assert len(report["cases"]) == 1

    result = report["cases"][0]
    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["correctness"] == {
        "cpu_oracle_executed": True,
        "boolean_support_equal": True,
    }
    assert result["cpu_reference"]["samples"] == 2
    assert result["cpu_reference"]["elapsed_ms_median"] >= 0.0
    assert result["cpu_reference"]["elapsed_ms_min"] >= 0.0
    assert result["cpu_reference"]["elapsed_ms_max"] >= result["cpu_reference"]["elapsed_ms_min"]
    assert result["cpu_bitset"]["samples"] == 2
    assert result["cpu_bitset"]["validate_ms"] >= 0.0
    assert result["cpu_bitset"]["support_decode_ms"] >= 0.0
    assert result["cpu_bitset"]["block_construct_ms"] >= 0.0
    assert result["cpu_bitset"]["canonicalize_ms"] == (
        result["cpu_bitset"]["support_decode_ms"]
        + result["cpu_bitset"]["block_construct_ms"]
    )
    assert result["cpu_bitset"]["output_entries"] == result["cpu_reference"]["output_entries"]
    assert result["cpu_bitset"]["digest"] == result["cpu_reference"]["digest"]
    assert set(result["diagnostic_ratios"]) == {
        "csr_full_operation_over_resident_bitset_kernel",
        "csr_full_operation_over_bitset_one_shot",
    }


def test_probe_bounds_case_collection() -> None:
    case = _case()
    for cases in ((), (case,) * 33):
        with pytest.raises(ValueError):
            run_probe(cases)
