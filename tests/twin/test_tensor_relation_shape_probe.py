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
    assert report["aggregate"]["project_count"] == 2
    assert report["aggregate"]["relation_count"] > 0
    assert report["aggregate"]["semantic_fact_count"] > 0

    for project in report["projects"]:
        assert project["subject"]["source_revision"] == _REVISION
        assert project["subject"]["source_fourfold_sha256"] == project["fourfold_sha256"]
        assert project["subject_digest"]
        assert project["relation_count"] == len(project["relations"])
        assert project["composable_pair_count"] == len(project["composable_pairs"])
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

    assert report["gardener_boundary"] == {
        "production_backend_added": False,
        "adaptive_matmul_path_added": False,
        "persistent_index_or_cache_added": False,
        "parallel_graph_authority_added": False,
    }
    assert not any(report["claim_boundaries"].values())


def test_reference_matmul_operation_count_matches_csr_nested_loop() -> None:
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
        manual = 0
        for position in range(left.entry_count):
            middle = left.column_indices[position]
            manual += right.row_offsets[middle + 1] - right.row_offsets[middle]
        assert pair["reference_operations"] == manual


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
