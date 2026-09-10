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


def test_adapter_then_compiler_keeps_two_distinct_forest_digest_owners() -> None:
    """Reject cross-owner digest reuse unless a trust boundary can be deleted.

    The adapter must hash the supplied Forest to bind the Fourfold snapshot.
    The relation compiler must independently hash the supplied Forest again to
    prove that it is the object bound by that snapshot before relation
    admission. Across the real adapter -> compiler chain that is therefore two
    aggregate digest calls owned by two different authority boundaries, not a
    duplicate inside either owner.

    Replacing the compiler call with ``snapshot.source_forest_sha256`` would
    remove the mismatch check; passing a caller-trusted digest would add a new
    trust/receipt surface. This call-scope contract intentionally records the
    negative gardener result instead of introducing either abstraction. It is
    not a latency or performance-superiority claim.
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
        compiled = _PROBE._compile(forest, snapshot)
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
    compiler_digest = _PROBE._direct_callee_metrics(
        stats,
        caller_code=_PROBE.compile_relation_blocks.__code__,
        callee_codes=(forest_digest_code,),
    )
    wrapper_digest = _PROBE._direct_callee_metrics(
        stats,
        caller_code=_PROBE._snapshot.__code__,
        callee_codes=(forest_digest_code,),
    )

    assert total_digest["calls"] == 2
    assert adapter_digest["calls"] == 1
    assert compiler_digest["calls"] == 1
    assert wrapper_digest["calls"] == 0
    assert adapter_digest["calls"] + compiler_digest["calls"] == total_digest["calls"]
    assert compiled.source_forest_sha256 == snapshot.source_forest_sha256
    assert compiled.subject.source_fourfold_sha256 == snapshot.digest


def test_compiler_keeps_single_partition_and_axis_setup_owners() -> None:
    """Reject a second partition/axis cache when setup is already single-owner.

    GPU-137 audits the remaining compiler setup path before changing production
    code. In this frozen one-plane selected relation case the compiler must call
    the canonical Forest/Fourfold partition verifier exactly once and construct
    exactly one TypedAxis for the selected code plane. A separate partition
    cache or parallel axis registry would therefore duplicate an existing owner
    rather than delete repeated setup work. This is call-scope evidence only;
    it is deliberately not a latency or performance-superiority claim.
    """

    forest = _PROBE._forest(
        nodes=12,
        row_width=2,
        revision=_PROBE.DELTA_REVISION,
        add_delta=True,
    )
    snapshot = _PROBE._snapshot(forest, revision=_PROBE.DELTA_REVISION)

    profiler = cProfile.Profile()
    profiler.enable()
    try:
        compiled = _PROBE._compile(forest, snapshot)
    finally:
        profiler.disable()

    stats = tuple(profiler.getstats())
    compiler_code = _PROBE.compile_relation_blocks.__code__
    partition_metric = _PROBE._direct_callee_metrics(
        stats,
        caller_code=compiler_code,
        callee_codes=(_PROBE._relation_compiler._forest_node_partition.__code__,),
    )
    axis_metric = _PROBE._direct_callee_metrics(
        stats,
        caller_code=compiler_code,
        callee_codes=(_PROBE._relation_compiler.TypedAxis.__init__.__code__,),
    )
    axis_post_init_metric = _PROBE._code_metrics(
        stats,
        (_PROBE._relation_compiler.TypedAxis.__post_init__.__code__,),
    )

    assert partition_metric["calls"] == 1
    assert axis_metric["calls"] == 1
    assert axis_post_init_metric["calls"] == 1
    assert partition_metric["cumulative_ms"] >= partition_metric["self_ms"] >= 0.0
    assert axis_metric["cumulative_ms"] >= axis_metric["self_ms"] >= 0.0
    assert len(compiled.blocks) == 1
    block = compiled.blocks[0][1]
    assert block.row_axis is block.column_axis
    assert block.row_axis.plane == "code"
