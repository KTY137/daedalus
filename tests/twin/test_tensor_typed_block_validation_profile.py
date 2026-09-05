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


def test_probe_pairs_support_decode_constructor_and_csr_validation_ab() -> None:
    report = _PROFILE.run_probe((_case(),), profile_repeats=2)

    assert report["schema"] == "daedalus-tensor-typed-block-validation-profile/6"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["semantic_scope"] == "canonical Boolean TypedRelationBlock materialization only"
    assert "unchanged packed-support decoder and canonical constructor" in report["measurement_contract"]
    assert "one bounded alternating same-process A/B" in report["measurement_contract"]
    assert "retired pre-GPU-19" in report["measurement_contract"]
    assert "microstage-only" in report["measurement_contract"]
    assert "does not bypass product validation" in report["measurement_contract"]
    assert "does not" in report["measurement_contract"]

    result = report["cases"][0]
    assert result["status"] == "verified"
    assert result["claim"] == "none"
    assert result["unprofiled_construct_ms"]["samples"] == 2
    assert result["profiled_construct_wall_ms"]["samples"] == 2
    assert result["support_decode"]["unprofiled_ms"]["samples"] == 2
    assert "scalar_admission" not in result
    assert result["support_decode"]["entry_count"] == result["output_entries"]
    assert result["support_decode"]["unprofiled_ms"]["median"] >= 0.0
    assert result["unprofiled_construct_ms"]["median"] >= 0.0
    assert result["profiled_construct_wall_ms"]["median"] >= 0.0
    assert set(result["profile_metrics"]) == EXPECTED_METRICS
    assert result["profile_metrics"]["typed_block_post_init"]["calls"] == 1
    assert result["profile_metrics"]["stored_scalar_admission"]["calls"] == result["output_entries"]
    assert result["profile_metrics"]["bounded_sequence_admission"]["calls"] == 3
    assert result["unprofiled_comparison"]["support_decode_to_constructor_ratio"] is None or result["unprofiled_comparison"]["support_decode_to_constructor_ratio"] >= 0.0
    assert "independently sampled decoder and constructor medians" in result["unprofiled_comparison"]["interpretation"]
    assert "non-additive" in result["unprofiled_comparison"]["interpretation"]
    assert "scalar_to_constructor_ratio" not in result["unprofiled_comparison"]
    assert result["profile_attribution"]["post_init_cumulative_ms_median"] >= 0.0
    assert result["profile_attribution"]["stored_cumulative_ms_median"] >= 0.0
    assert result["profile_attribution"]["post_init_less_stored_cumulative_ms_median"] >= 0.0
    assert "real canonical constructor" in result["profile_attribution"]["interpretation"]
    assert "no duplicate scalar wall-time probe" in result["profile_attribution"]["interpretation"]
    assert "not a pure structural wall-time" in result["profile_attribution"]["interpretation"]

    ab = result["csr_column_validation_ab"]
    assert ab["authority"] == "microstage-diagnostic-only"
    assert _PROFILE.PRE_GPU19_RELATION_BLOCK_BLOB in ab["control"]
    assert "GPU-19 matched-count row-span" in ab["candidate"]
    assert ab["valid_outcome_parity"] is True
    assert ab["ordering"] == "alternating AB/BA in one process"
    assert ab["control_ms"]["samples"] == 2
    assert ab["candidate_ms"]["samples"] == 2
    assert ab["control_ms"]["median"] >= 0.0
    assert ab["candidate_ms"]["median"] >= 0.0
    assert ab["candidate_to_control_ratio"] is None or ab["candidate_to_control_ratio"] >= 0.0
    assert "already decoded canonical CSR support" in ab["interpretation"]
    assert "cannot mint" in ab["interpretation"]


def test_csr_validation_ab_matches_valid_and_invalid_outcomes() -> None:
    validators = (
        _PROFILE._pre_gpu19_column_validation,
        _PROFILE._gpu19_column_validation,
    )

    valid = {
        "row_offsets": (0, 2, 2, 4),
        "column_indices": (0, 2, 1, 3),
        "row_count": 3,
        "column_count": 4,
        "entry_count": 4,
    }
    for validator in validators:
        assert validator(**valid) is None

    invalid_cases = (
        (
            {
                "row_offsets": (0, 2),
                "column_indices": (1, 0),
                "row_count": 1,
                "column_count": 2,
                "entry_count": 2,
            },
            "strictly increasing",
        ),
        (
            {
                "row_offsets": (0, 2),
                "column_indices": (2, 0),
                "row_count": 1,
                "column_count": 2,
                "entry_count": 1,
            },
            "out-of-range",
        ),
        (
            {
                "row_offsets": (0, 2),
                "column_indices": (1, 0),
                "row_count": 1,
                "column_count": 2,
                "entry_count": 1,
            },
            "common entry count",
        ),
        (
            {
                "row_offsets": (0, 2),
                "column_indices": ("bad", 0),
                "row_count": 1,
                "column_count": 2,
                "entry_count": 1,
            },
            "contain integers",
        ),
    )
    for kwargs, message in invalid_cases:
        for validator in validators:
            with pytest.raises(ValueError, match=message):
                validator(**kwargs)


def test_csr_validation_ab_is_bounded_and_rejects_non_callables() -> None:
    noop = lambda: None
    for repeats, warmup in ((0, 0), (_PROFILE.MAX_REPEATS + 1, 0), (True, 0)):
        with pytest.raises(ValueError, match="repeats"):
            _PROFILE._measure_validation_ab(noop, noop, repeats=repeats, warmup=warmup)
    for repeats, warmup in ((1, -1), (1, _PROFILE.MAX_WARMUP + 1), (1, True)):
        with pytest.raises(ValueError, match="warmup"):
            _PROFILE._measure_validation_ab(noop, noop, repeats=repeats, warmup=warmup)
    with pytest.raises(ValueError, match="validators must be callable"):
        _PROFILE._measure_validation_ab(None, noop, repeats=1, warmup=0)  # type: ignore[arg-type]


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


def test_duplicate_and_retired_profiler_paths_are_removed() -> None:
    assert not hasattr(_PROFILE, "_scalar_admission")
    assert not hasattr(_PROFILE, "_nested_codes")
    assert not hasattr(_PROFILE, "_builtin_metrics")


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
