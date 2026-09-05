from __future__ import annotations

import importlib

import pytest

_PROFILE = importlib.import_module("experiments.tensor_gpu.typed_block_validation_profile")
ProbeCase = _PROFILE.ProbeCase


EXPECTED_METRICS = {
    "bitset_block_factory",
    "typed_block_post_init",
    "stored_scalar_admission",
    "bounded_sequence_admission",
    "semiring_resolution",
    "identifier_admission",
}


def _case() -> object:
    return ProbeCase(
        size=8,
        density=0.25,
        repeats=2,
        warmup=1,
        max_device_mib=64,
    )


def test_profile_executes_the_existing_canonical_constructor() -> None:
    case = _case()
    left, right, _ = _PROFILE.build_boolean_case(case)
    masks = _PROFILE.compose_packed_rows(_PROFILE.pack_rows(left), _PROFILE.pack_rows(right))
    row_offsets, column_indices = _PROFILE._csr_support_from_masks(left, right, masks)

    canonical = _PROFILE._block_from_csr_support(
        left,
        right,
        row_offsets,
        column_indices,
        relation="cpu_bitset_composed",
    )
    sample = _PROFILE._profile_once(
        lambda: _PROFILE._block_from_csr_support(
            left,
            right,
            row_offsets,
            column_indices,
            relation="cpu_bitset_composed",
        )
    )

    assert sample.block.digest == canonical.digest
    assert sample.wall_ms >= 0.0
    assert set(sample.metrics) == EXPECTED_METRICS
    assert sample.metrics["bitset_block_factory"]["calls"] == 1
    assert sample.metrics["typed_block_post_init"]["calls"] == 1
    assert sample.metrics["stored_scalar_admission"]["calls"] == canonical.entry_count
    assert sample.metrics["bounded_sequence_admission"]["calls"] == 3
    for metric in sample.metrics.values():
        assert metric["self_ms"] >= 0.0
        assert metric["cumulative_ms"] >= 0.0


def test_probe_pairs_support_decode_with_constructor_native_profile_only() -> None:
    report = _PROFILE.run_probe((_case(),), profile_repeats=2)

    assert report["schema"] == "daedalus-tensor-typed-block-validation-profile/7"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["semantic_scope"] == "canonical Boolean TypedRelationBlock materialization only"
    assert "unchanged packed-support decoder and canonical constructor" in report["measurement_contract"]
    assert "constructor-native cProfile attribution" in report["measurement_contract"]
    assert "Retired one-shot A/B controls" in report["measurement_contract"]
    assert "does not bypass product validation" in report["measurement_contract"]

    result = report["cases"][0]
    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["unprofiled_construct_ms"]["samples"] == 2
    assert result["profiled_construct_wall_ms"]["samples"] == 2
    assert result["support_decode"]["unprofiled_ms"]["samples"] == 2
    assert "scalar_admission" not in result
    assert "csr_column_validation_ab" not in result
    assert result["support_decode"]["entry_count"] == result["output_entries"]
    assert result["support_decode"]["unprofiled_ms"]["median"] >= 0.0
    assert result["unprofiled_construct_ms"]["median"] >= 0.0
    assert result["profiled_construct_wall_ms"]["median"] >= 0.0
    assert set(result["profile_metrics"]) == EXPECTED_METRICS
    assert result["profile_metrics"]["typed_block_post_init"]["calls"] == 1
    assert result["profile_metrics"]["stored_scalar_admission"]["calls"] == result["output_entries"]
    assert result["profile_metrics"]["bounded_sequence_admission"]["calls"] == 3
    ratio = result["unprofiled_comparison"]["support_decode_to_constructor_ratio"]
    assert ratio is None or ratio >= 0.0
    assert "independently sampled decoder and constructor medians" in result["unprofiled_comparison"]["interpretation"]
    assert "non-additive" in result["unprofiled_comparison"]["interpretation"]
    assert "scalar_to_constructor_ratio" not in result["unprofiled_comparison"]
    assert result["profile_attribution"]["post_init_cumulative_ms_median"] >= 0.0
    assert result["profile_attribution"]["stored_cumulative_ms_median"] >= 0.0
    assert result["profile_attribution"]["post_init_less_stored_cumulative_ms_median"] >= 0.0
    assert "real canonical constructor" in result["profile_attribution"]["interpretation"]
    assert "no duplicate scalar wall-time probe" in result["profile_attribution"]["interpretation"]
    assert "not a pure structural wall-time" in result["profile_attribution"]["interpretation"]


def test_support_decode_measurement_reuses_exact_existing_decoder() -> None:
    case = _case()
    left, right, _ = _PROFILE.build_boolean_case(case)
    masks = _PROFILE.compose_packed_rows(_PROFILE.pack_rows(left), _PROFILE.pack_rows(right))

    expected = _PROFILE._csr_support_from_masks(left, right, masks)
    report = _PROFILE.run_probe((case,), profile_repeats=1)
    result = report["cases"][0]

    assert result["support_decode"]["contract"].endswith("._csr_support_from_masks")
    assert result["support_decode"]["row_count"] == len(expected[0]) - 1
    assert result["support_decode"]["entry_count"] == len(expected[1])


def test_retired_profiler_paths_are_not_live_code() -> None:
    for name in (
        "_scalar_admission",
        "_nested_codes",
        "_builtin_metrics",
        "_pre_gpu19_column_validation",
        "_gpu19_column_validation",
        "_measure_validation_ab",
        "PRE_GPU19_RELATION_BLOCK_BLOB",
    ):
        assert not hasattr(_PROFILE, name)


def test_profile_repeat_bound_is_strict_and_rejects_bool() -> None:
    for value in (0, _PROFILE.MAX_PROFILE_REPEATS + 1, True):
        with pytest.raises(ValueError, match="profile_repeats"):
            _PROFILE._validate_profile_repeats(value)


def test_probe_bounds_case_collection_without_parallel_harness() -> None:
    case = _case()
    for cases in ((), (case,) * (_PROFILE.MAX_CASES + 1)):
        with pytest.raises(ValueError, match="cases must contain"):
            _PROFILE.run_probe(cases, profile_repeats=1)


def test_profile_once_rejects_non_callable_factory() -> None:
    with pytest.raises(ValueError, match="factory must be callable"):
        _PROFILE._profile_once(None)  # type: ignore[arg-type]
