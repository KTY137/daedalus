from __future__ import annotations

import importlib

import pytest

_PROBE = importlib.import_module("experiments.tensor_gpu.relation_delta_rebuild_probe")


def test_probe_measures_one_fact_delta_without_second_projection_owner() -> None:
    report = _PROBE.run_probe(
        nodes=12,
        row_width=2,
        repeats=2,
        warmup=0,
        profile_repeats=2,
    )

    assert report["schema"] == "daedalus-tensor-relation-delta-rebuild/3"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert "compile_relation_blocks" in report["measurement_contract"]
    assert "No production delta path" in report["measurement_contract"]
    assert "direct compiler callees" in report["measurement_contract"]

    case = report["case"]
    assert case["base_forest_edges"] == 24
    assert case["delta_forest_edges"] == 25
    assert case["base_output_entries"] == 24
    assert case["delta_output_entries"] == 25
    assert case["changed_coordinate_count"] == 1
    assert case["added_entries"] == [["src/node_0000.py", "src/node_0003.py", True]]
    assert case["removed_entries"] == []
    assert case["base_compiled_digest"] != case["delta_compiled_digest"]

    rebuild = report["full_rebuild"]
    assert rebuild["rebuild_entries_per_changed_coordinate"] == 25.0
    assert rebuild["forest_edges_scanned_per_changed_coordinate"] == 25.0
    assert rebuild["changed_coordinate_fraction_of_delta_output"] == 1 / 25
    assert rebuild["base_compile_ms"]["samples"] == 2
    assert rebuild["delta_compile_ms"]["samples"] == 2
    assert rebuild["base_compile_ms"]["median_ms"] >= 0.0
    assert rebuild["delta_compile_ms"]["median_ms"] >= 0.0

    attribution = report["full_rebuild_attribution"]
    assert attribution["profile_repeats"] == 2
    assert attribution["profiled_compile_wall_ms"]["samples"] == 2
    assert attribution["compiler_cumulative_ms_median"] >= 0.0
    assert attribution["selected_block_reconstruction_cumulative_ms_median"] >= 0.0
    assert attribution["non_block_compiler_residual_cumulative_ms_median"] >= 0.0
    assert attribution["observed_same_plane_edge_admission_cumulative_ms_median"] >= 0.0
    assert attribution["fact_aggregation_direct_cumulative_ms_median"] >= 0.0
    assert (
        attribution[
            "remaining_non_block_after_observed_edge_and_fact_cumulative_ms_median"
        ]
        >= 0.0
    )
    metrics = attribution["profile_metrics"]
    assert metrics["compiler_total"]["calls"] == 1
    assert metrics["selected_block_reconstruction"]["calls"] == 1
    assert metrics["typed_block_post_init"]["calls"] == 1
    assert metrics["fact_aggregation"]["calls"] == 25
    assert metrics["forest_partition_validation"]["calls"] == 1
    assert metrics["edge_signature_construction"]["calls"] == 25
    assert metrics["edge_wire_materialization"]["calls"] == 25
    assert metrics["retained_relation_digest"]["calls"] == 25
    assert metrics["fact_aggregation_direct"]["calls"] == 25
    assert "conservative lower bound" in attribution["interpretation"]
    assert "direct compiler calls" in attribution["interpretation"]
    assert "not a pure edge-scan wall time" in attribution["interpretation"]

    assert report["fail_closed"]["partial_endpoint_plane"] == "refused"
    assert "code=partial" in report["fail_closed"]["message"]
    assert report["claim_boundaries"]["incremental_backend_implemented"] is False
    assert report["claim_boundaries"]["performance_superiority"] is False


def test_fixture_keeps_axis_membership_fixed_across_the_delta() -> None:
    base_forest = _PROBE._forest(
        nodes=10,
        row_width=2,
        revision=_PROBE.BASE_REVISION,
        add_delta=False,
    )
    delta_forest = _PROBE._forest(
        nodes=10,
        row_width=2,
        revision=_PROBE.DELTA_REVISION,
        add_delta=True,
    )
    base_snapshot = _PROBE._snapshot(base_forest, revision=_PROBE.BASE_REVISION)
    delta_snapshot = _PROBE._snapshot(delta_forest, revision=_PROBE.DELTA_REVISION)

    base_code = next(plane for plane in base_snapshot.planes if plane.plane == "code")
    delta_code = next(plane for plane in delta_snapshot.planes if plane.plane == "code")
    assert base_code.node_ids == delta_code.node_ids
    assert base_code.status == delta_code.status == "complete"
    assert len(delta_forest.edges) == len(base_forest.edges) + 1


def test_partial_endpoint_contract_fails_closed_before_sparse_zero_interpretation() -> None:
    forest = _PROBE._forest(
        nodes=8,
        row_width=2,
        revision=_PROBE.DELTA_REVISION,
        add_delta=True,
    )
    partial = _PROBE._snapshot(
        forest,
        revision=_PROBE.DELTA_REVISION,
        complete_code=False,
    )

    with pytest.raises(
        ValueError,
        match=r"relation compilation requires complete endpoint planes; code=partial",
    ):
        _PROBE._compile(forest, partial)


def test_probe_bounds_are_strict_and_reject_bool_aliases() -> None:
    invalid = (
        {
            "nodes": True,
            "row_width": 1,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": 1,
        },
        {
            "nodes": 4,
            "row_width": 3,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": 1,
        },
        {
            "nodes": 8,
            "row_width": True,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": 1,
        },
        {
            "nodes": 8,
            "row_width": 2,
            "repeats": 0,
            "warmup": 0,
            "profile_repeats": 1,
        },
        {
            "nodes": 8,
            "row_width": 2,
            "repeats": 1,
            "warmup": -1,
            "profile_repeats": 1,
        },
        {
            "nodes": 8,
            "row_width": 2,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": True,
        },
        {
            "nodes": 8,
            "row_width": 2,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": 0,
        },
        {
            "nodes": 8,
            "row_width": 2,
            "repeats": 1,
            "warmup": 0,
            "profile_repeats": _PROBE.MAX_PROFILE_REPEATS + 1,
        },
    )
    for case in invalid:
        with pytest.raises(ValueError):
            _PROBE.run_probe(**case)
