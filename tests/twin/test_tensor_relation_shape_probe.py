from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_PROBE = importlib.import_module("experiments.tensor_gpu.relation_shape_probe")
_REPO = Path(__file__).resolve().parents[2]
_WIKI = _REPO / "examples" / "fourfold_wiki_app"
_IGNITION = _REPO / "tests" / "fixtures" / "ignition" / "voltage"
_REVISION = "f" * 64
_CREATED_AT = "2026-09-11T00:00:00Z"
_EXPECTED_REAL_SHAPES = {
    "daedalus/fourfold-wiki-reference": {
        "relation_count": 11,
        "semantic_fact_count": 67,
        "composable_pair_count": 27,
        "observed_max_out_degree": 9,
        "observed_max_reference_operations": 24,
    },
    "daedalus/ignition-field-fixture": {
        "relation_count": 10,
        "semantic_fact_count": 18,
        "composable_pair_count": 23,
        "observed_max_out_degree": 2,
        "observed_max_reference_operations": 2,
    },
}
_EXPECTED_AGGREGATE = {
    "project_count": 2,
    "relation_count": 21,
    "semantic_fact_count": 85,
    "composable_pair_count": 50,
    "observed_max_out_degree": 9,
    "observed_max_reference_operations": 24,
}


def test_real_reference_projects_expose_revision_bound_relation_shapes() -> None:
    report = _PROBE.run_probe(
        (_WIKI, _IGNITION),
        source_revision=_REVISION,
        created_at=_CREATED_AT,
    )

    assert report["schema"] == _PROBE.SCHEMA
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"
    assert report["aggregate"] == _EXPECTED_AGGREGATE

    by_repository = {project["repository_id"]: project for project in report["projects"]}
    assert set(by_repository) == set(_EXPECTED_REAL_SHAPES)
    for repository_id, expected in _EXPECTED_REAL_SHAPES.items():
        project = by_repository[repository_id]
        for field, value in expected.items():
            assert project[field] == value
        assert project["subject"]["source_revision"] == _REVISION
        assert project["subject"]["source_fourfold_sha256"] == project["fourfold_sha256"]
        assert project["subject_digest"]
        assert project["relation_count"] == len(project["relations"])
        assert project["composable_pair_count"] == len(project["composable_pairs"])
        assert project["composable_pair_count"] <= _PROBE.MAX_PROFILED_COMPOSABLE_PAIRS
        assert sum(
            pair["reference_operations"] for pair in project["composable_pairs"]
        ) <= _PROBE.MAX_PROFILE_REFERENCE_OPERATIONS
        assert project["semantic_fact_count"] == sum(
            relation["entries"] for relation in project["relations"]
        )
        for relation in project["relations"]:
            assert 0.0 <= relation["density"] <= 1.0
            degree = relation["out_degree"]
            assert 0 <= degree["p50"] <= degree["max"]
            assert 0 <= degree["p95"] <= degree["max"]
            assert 0 <= relation["nonempty_rows"] <= relation["rows"]
        for pair in project["composable_pairs"]:
            assert pair["reference_operations"] >= 0
            assert 0 <= pair["reference_peak_accumulator_entries"] <= pair["right_entries"]

    assert report["gardener_boundary"] == {
        "production_backend_added": False,
        "adaptive_matmul_path_added": False,
        "persistent_index_or_cache_added": False,
        "parallel_graph_authority_added": False,
    }
    assert not any(report["claim_boundaries"].values())


def test_reference_matmul_shape_matches_csr_nested_loop() -> None:
    project = _PROBE.profile_reference_project(
        _WIKI,
        source_revision=_REVISION,
        created_at=_CREATED_AT,
    )
    assert project["composable_pairs"]

    compiled_reference = _PROBE.compile_reference_project(
        _WIKI,
        source_revision=_REVISION,
        created_at=_CREATED_AT,
        trace_id="tensor-relation-shape-probe-test",
    )
    compiled = _PROBE.compile_relation_blocks(
        compiled_reference.forest,
        compiled_reference.snapshot,
        _PROBE.BooleanSemiring(),
    )
    block_map = dict(compiled.blocks)

    for pair in project["composable_pairs"]:
        left = block_map[pair["left"]]
        right = block_map[pair["right"]]
        manual_operations = 0
        manual_peak_accumulator_entries = 0
        for row in range(len(left.row_axis.labels)):
            accumulator_columns: set[int] = set()
            for position in range(left.row_offsets[row], left.row_offsets[row + 1]):
                middle = left.column_indices[position]
                for right_position in range(
                    right.row_offsets[middle],
                    right.row_offsets[middle + 1],
                ):
                    manual_operations += 1
                    accumulator_columns.add(right.column_indices[right_position])
            manual_peak_accumulator_entries = max(
                manual_peak_accumulator_entries,
                len(accumulator_columns),
            )
        assert pair["reference_operations"] == manual_operations
        assert (
            pair["reference_peak_accumulator_entries"]
            == manual_peak_accumulator_entries
        )


def test_probe_rejects_duplicate_or_unbounded_project_sets() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        _PROBE.run_probe(
            (_WIKI, _WIKI),
            source_revision=_REVISION,
            created_at=_CREATED_AT,
        )

    with pytest.raises(ValueError):
        _PROBE.run_probe(
            tuple(_WIKI for _ in range(_PROBE.MAX_PROJECTS + 1)),
            source_revision=_REVISION,
            created_at=_CREATED_AT,
        )


def test_probe_fails_closed_at_composable_pair_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_PROBE, "MAX_PROFILED_COMPOSABLE_PAIRS", 0)

    with pytest.raises(ValueError, match="composable pair limit"):
        _PROBE.profile_reference_project(
            _WIKI,
            source_revision=_REVISION,
            created_at=_CREATED_AT,
        )


def test_probe_fails_closed_at_reference_operation_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_PROBE, "MAX_PROFILE_REFERENCE_OPERATIONS", 0)

    with pytest.raises(ValueError, match="reference-operation limit"):
        _PROBE.profile_reference_project(
            _WIKI,
            source_revision=_REVISION,
            created_at=_CREATED_AT,
        )
