from __future__ import annotations

import importlib

import pytest

_PROBE = importlib.import_module("experiments.tensor_gpu.relation_delta_authority_probe")
_BASE = importlib.import_module("experiments.tensor_gpu.relation_delta_rebuild_probe")


def test_probe_maps_one_digest_delta_without_new_authority() -> None:
    report = _PROBE.run_probe(nodes=12, row_width=2, scan_repeats=2)

    assert report["schema"] == "daedalus-tensor-relation-delta-authority/1"
    assert report["status"] == "completed"
    assert report["authority"] == "diagnostic-only"
    assert report["claim"] == "none"

    case = report["case"]
    assert case["base_forest_edges"] == 24
    assert case["candidate_forest_edges"] == 25
    assert case["base_revision"] == _BASE.BASE_REVISION
    assert case["candidate_revision"] == _BASE.DELTA_REVISION
    assert case["base_forest_sha256"] != case["candidate_forest_sha256"]

    delta = report["relation_digest_delta"]
    assert len(delta["code"]["added"]) == 1
    assert delta["code"]["removed"] == []
    assert all(
        plane_delta["added"] == [] and plane_delta["removed"] == []
        for plane, plane_delta in delta.items()
        if plane != "code"
    )
    assert report["changed_digest_count"] == 1
    assert report["affected_signatures"] == [["code", "imports", "code"]]

    mapping = report["mapping_cost"]
    assert mapping["added"]["samples"] == 2
    assert mapping["added"]["forest_edges_examined"] == 25
    assert mapping["added"]["same_plane_edges_hashed"] == 25
    assert mapping["candidate_hashes_per_added_digest"] == 25.0
    assert mapping["removed"]["forest_edges_examined"] == 0
    assert mapping["removed"]["same_plane_edges_hashed"] == 0
    assert mapping["base_hashes_per_removed_digest"] == 0.0
    assert mapping["added"]["median_ms"] >= 0.0

    assert report["oracle"]["equal"] is True
    assert report["oracle"]["full_compile_digest"] == report["oracle"][
        "affected_signature_compile_digest"
    ]
    assert report["gardener_boundary"] == {
        "production_incremental_backend_added": False,
        "digest_index_added": False,
        "compiler_cache_added": False,
        "parallel_graph_authority_added": False,
        "trusted_constructor_added": False,
    }
    assert report["claim_boundaries"]["performance_superiority"] is False


def test_changed_digest_locator_fails_closed_when_digest_is_not_in_forest() -> None:
    forest = _BASE._forest(
        nodes=8,
        row_width=2,
        revision=_BASE.DELTA_REVISION,
        add_delta=True,
    )
    snapshot = _BASE._snapshot(forest, revision=_BASE.DELTA_REVISION)

    with pytest.raises(
        AssertionError,
        match="changed Fourfold relation digests were not present",
    ):
        _PROBE._locate_changed_edges(forest, snapshot, frozenset({"0" * 64}))


def test_empty_digest_scope_does_not_scan_or_hash_forest() -> None:
    forest = _BASE._forest(
        nodes=8,
        row_width=2,
        revision=_BASE.DELTA_REVISION,
        add_delta=True,
    )
    snapshot = _BASE._snapshot(forest, revision=_BASE.DELTA_REVISION)

    matches, signatures, examined, hashed = _PROBE._locate_changed_edges(
        forest,
        snapshot,
        frozenset(),
    )
    assert matches == ()
    assert signatures == ()
    assert examined == 0
    assert hashed == 0


def test_scan_repeat_bounds_reject_bool_aliases() -> None:
    for value in (0, True, _PROBE.MAX_SCAN_REPEATS + 1):
        with pytest.raises(ValueError):
            _PROBE.run_probe(nodes=8, row_width=2, scan_repeats=value)
