from __future__ import annotations

import cProfile
import importlib

_PROBE = importlib.import_module("experiments.tensor_gpu.relation_delta_rebuild_probe")


def test_probe_snapshot_reuses_adapter_owned_forest_digest() -> None:
    """Keep probe setup from rehashing the same immutable Forest redundantly.

    The legacy adapter remains the authority owner that computes the Forest
    digest for the derived Fourfold snapshot. The probe-only completeness
    wrapper may reuse that exact immutable digest, but the later relation
    compiler still performs its own independent Forest/Fourfold verification.
    This test pins call scope only; it is not a performance claim.
    """

    forest = _PROBE._forest(
        nodes=12,
        row_width=2,
        revision=_PROBE.DELTA_REVISION,
        add_delta=True,
    )

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        snapshot = _PROBE._snapshot(
            forest,
            revision=_PROBE.DELTA_REVISION,
        )
    finally:
        profiler.disable()

    stats = tuple(profiler.getstats())
    forest_digest_code = _PROBE.KnowledgeForest.content_sha256.fget.__code__
    total_digest = _PROBE._code_metrics(stats, (forest_digest_code,))
    adapter_digest = _PROBE._direct_callee_metrics(
        stats,
        caller_code=_PROBE.fourfold_from_knowledge_forest.__code__,
        callee_codes=(forest_digest_code,),
    )
    wrapper_digest = _PROBE._direct_callee_metrics(
        stats,
        caller_code=_PROBE._snapshot.__code__,
        callee_codes=(forest_digest_code,),
    )

    assert total_digest["calls"] == 1
    assert adapter_digest["calls"] == 1
    assert wrapper_digest["calls"] == 0
    assert snapshot.source_forest_sha256 in snapshot.provenance.input_digests
    assert all(
        snapshot.source_forest_sha256 in plane.evidence_sha256s
        for plane in snapshot.planes
    )

    compiled = _PROBE._compile(forest, snapshot)
    assert compiled.source_forest_sha256 == snapshot.source_forest_sha256
    assert compiled.subject.source_fourfold_sha256 == snapshot.digest
