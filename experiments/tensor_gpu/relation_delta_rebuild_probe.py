"""Measure full relation-block rebuild amplification for one tiny semantic delta.

This is a bounded diagnostic, not a production delta engine. It keeps the
existing KnowledgeForest/Fourfold authorities and ``compile_relation_blocks``
as the only projection owner, then asks two narrow questions: when one retained
same-plane relation fact changes while axis membership stays fixed, how much
canonical work is repeated by the required full rebuild today, and where does
that rebuild spend its profiled time inside the existing compiler front half?

The probe deliberately does not implement or simulate a trusted incremental
constructor. It reports exact changed-coordinate scope, deterministic
input/output amplification, ordinary full-rebuild wall timing, and cProfile
attribution from the unchanged compiler. The front-half split observes only
direct Python callees of ``compile_relation_blocks`` so it cannot accidentally
charge nested digest work to the selected same-plane edge-admission seam.
Partial endpoint planes are exercised fail-closed so a future incremental design
cannot quietly reinterpret unknown sparse zeroes as complete facts.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import platform
import statistics
import time
from pathlib import Path
from typing import Any, Sequence

import daedalus.twin.relation_compiler as _relation_compiler
from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot, fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature, TypedRelationBlock
from daedalus.twin.relation_compiler import CompiledRelationBlocks, compile_relation_blocks
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import write_report
    from .cpu_bitset_baseline import MAX_REPEATS, MAX_WARMUP, _measure_repeated
else:  # direct ``python experiments/tensor_gpu/relation_delta_rebuild_probe.py``
    from boolean_probe_contract import write_report
    from cpu_bitset_baseline import MAX_REPEATS, MAX_WARMUP, _measure_repeated

SCHEMA = "daedalus-tensor-relation-delta-rebuild/3"
MAX_NODES = 2_048
MAX_PROFILE_REPEATS = 5
BASE_REVISION = "a" * 40
DELTA_REVISION = "b" * 40
CREATED_AT = "2026-09-08T19:02:06Z"
SIGNATURE = RelationSignature("code", "imports", "code")


def _validate_case(
    *,
    nodes: int,
    row_width: int,
    repeats: int,
    warmup: int,
    profile_repeats: int,
) -> None:
    if type(nodes) is not int or not 4 <= nodes <= MAX_NODES:
        raise ValueError(f"nodes must be an integer from 4 to {MAX_NODES}")
    if type(row_width) is not int or not 1 <= row_width < nodes - 1:
        raise ValueError("row_width must be an integer from 1 to nodes - 2")
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(warmup) is not int or not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")
    if type(profile_repeats) is not int or not 1 <= profile_repeats <= MAX_PROFILE_REPEATS:
        raise ValueError(
            f"profile_repeats must be an integer from 1 to {MAX_PROFILE_REPEATS}"
        )


def _node_id(index: int) -> str:
    return f"src/node_{index:04d}.py"


def _forest(*, nodes: int, row_width: int, revision: str, add_delta: bool) -> KnowledgeForest:
    forest_nodes = tuple(ForestNode(_node_id(index), "source_file") for index in range(nodes))
    edges = [
        ForestEdge(
            _node_id(source),
            _node_id((source + offset) % nodes),
            "imports",
            True,
            evidence=(f"probe.imports.{source}.{offset}",),
        )
        for source in range(nodes)
        for offset in range(1, row_width + 1)
    ]
    if add_delta:
        edges.append(
            ForestEdge(
                _node_id(0),
                _node_id(row_width + 1),
                "imports",
                True,
                evidence=("probe.delta.single-edge",),
            )
        )
    return KnowledgeForest(
        root="/synthetic/relation-delta",
        nodes=forest_nodes,
        edges=tuple(edges),
        hyperedges=(),
        provenance={
            "origin": "experiments.tensor_gpu.relation_delta_rebuild_probe",
            "source_revision": revision,
        },
    )


def _snapshot(
    forest: KnowledgeForest,
    *,
    revision: str,
    complete_code: bool = True,
) -> FourfoldSnapshot:
    legacy = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus:synthetic-relation-delta",
        source_revision=revision,
        created_at=CREATED_AT,
        trace_id=f"relation-delta-{revision[0]}",
    )
    planes = tuple(
        (
            PlaneSnapshot(
                plane="code",
                source_revision=revision,
                status="complete" if complete_code else "partial",
                node_ids=plane.node_ids,
                relation_sha256s=plane.relation_sha256s,
                evidence_sha256s=plane.evidence_sha256s,
                reason=None if complete_code else "bounded probe marks code plane partial",
            )
            if plane.plane == "code"
            else plane
        )
        for plane in legacy.planes
    )
    provenance = ContractProvenance(
        origin="experiments.tensor_gpu.relation_delta_rebuild_probe",
        source_revision=revision,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in legacy.bindings),
        ),
        trace_id=f"relation-delta-complete-{revision[0]}",
    )
    return FourfoldSnapshot(
        repository_id=legacy.repository_id,
        source_revision=revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=legacy.bindings,
        provenance=provenance,
    )


def _compile(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> CompiledRelationBlocks[bool]:
    return compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(SIGNATURE,),
        include_verified_bindings=False,
    )


def _entries(compiled: CompiledRelationBlocks[bool]) -> frozenset[tuple[str, str, bool]]:
    if len(compiled.blocks) != 1:
        raise AssertionError("bounded probe expected exactly one compiled relation")
    return frozenset(compiled.blocks[0][1].iter_entries())


def _timing_summary(samples: Sequence[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("timing samples must not be empty")
    return {
        "samples": len(samples),
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
    }


def _entry_metrics(entries: Sequence[Any]) -> dict[str, float | int]:
    return {
        "calls": sum(int(entry.callcount) for entry in entries),
        "self_ms": sum(float(entry.inlinetime) for entry in entries) * 1_000.0,
        "cumulative_ms": sum(float(entry.totaltime) for entry in entries) * 1_000.0,
    }


def _code_metrics(stats: Sequence[Any], codes: Sequence[Any]) -> dict[str, float | int]:
    code_ids = {id(code) for code in codes}
    return _entry_metrics(tuple(entry for entry in stats if id(entry.code) in code_ids))


def _direct_callee_metrics(
    stats: Sequence[Any],
    *,
    caller_code: Any,
    callee_codes: Sequence[Any],
) -> dict[str, float | int]:
    """Attribute only direct profiled calls from one existing owner.

    ``cProfile`` exposes caller-local subentries through ``entry.calls``. Using
    those subentries keeps the GPU-102 front-half split bounded to the real
    ``compile_relation_blocks`` call site instead of counting the same helper
    when it is reached through nested Forest/Fourfold digest construction.
    """

    callee_ids = {id(code) for code in callee_codes}
    direct_entries: list[Any] = []
    for entry in stats:
        if id(entry.code) != id(caller_code) or not entry.calls:
            continue
        direct_entries.extend(
            call for call in entry.calls if id(call.code) in callee_ids
        )
    return _entry_metrics(tuple(direct_entries))


def _profile_compile_once(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
) -> tuple[CompiledRelationBlocks[bool], float, dict[str, dict[str, float | int]]]:
    profiler = cProfile.Profile()
    started = time.perf_counter_ns()
    profiler.enable()
    try:
        compiled = _compile(forest, snapshot)
    finally:
        profiler.disable()
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    stats = tuple(profiler.getstats())
    compiler_code = compile_relation_blocks.__code__
    return compiled, wall_ms, {
        "compiler_total": _code_metrics(stats, (compiler_code,)),
        "selected_block_reconstruction": _code_metrics(
            stats,
            (TypedRelationBlock._from_indexed.__func__.__code__,),
        ),
        "typed_block_post_init": _code_metrics(
            stats,
            (TypedRelationBlock.__post_init__.__code__,),
        ),
        "fact_aggregation": _code_metrics(
            stats,
            (_relation_compiler._record_fact.__code__,),
        ),
        "forest_partition_validation": _code_metrics(
            stats,
            (_relation_compiler._forest_node_partition.__code__,),
        ),
        "edge_signature_construction": _direct_callee_metrics(
            stats,
            caller_code=compiler_code,
            callee_codes=(RelationSignature.__init__.__code__,),
        ),
        "edge_wire_materialization": _direct_callee_metrics(
            stats,
            caller_code=compiler_code,
            callee_codes=(ForestEdge.to_dict.__code__,),
        ),
        "retained_relation_digest": _direct_callee_metrics(
            stats,
            caller_code=compiler_code,
            callee_codes=(_relation_compiler.canonical_sha.__code__,),
        ),
        "fact_aggregation_direct": _direct_callee_metrics(
            stats,
            caller_code=compiler_code,
            callee_codes=(_relation_compiler._record_fact.__code__,),
        ),
    }


def _median_profile_metrics(
    samples: Sequence[dict[str, dict[str, float | int]]],
) -> dict[str, dict[str, float | int]]:
    if not samples:
        raise ValueError("profile samples must not be empty")
    names = tuple(samples[0])
    if any(tuple(sample) != names for sample in samples[1:]):
        raise AssertionError("profile metric surface drifted inside one case")
    output: dict[str, dict[str, float | int]] = {}
    for name in names:
        calls = {int(sample[name]["calls"]) for sample in samples}
        if len(calls) != 1:
            raise AssertionError(f"profile call count for {name} drifted inside one case")
        output[name] = {
            "calls": calls.pop(),
            "self_ms_median": float(
                statistics.median(float(sample[name]["self_ms"]) for sample in samples)
            ),
            "cumulative_ms_median": float(
                statistics.median(float(sample[name]["cumulative_ms"]) for sample in samples)
            ),
        }
    return output


def run_probe(
    *,
    nodes: int = 512,
    row_width: int = 16,
    repeats: int = 7,
    warmup: int = 2,
    profile_repeats: int = 3,
) -> dict[str, Any]:
    _validate_case(
        nodes=nodes,
        row_width=row_width,
        repeats=repeats,
        warmup=warmup,
        profile_repeats=profile_repeats,
    )

    base_forest = _forest(
        nodes=nodes,
        row_width=row_width,
        revision=BASE_REVISION,
        add_delta=False,
    )
    delta_forest = _forest(
        nodes=nodes,
        row_width=row_width,
        revision=DELTA_REVISION,
        add_delta=True,
    )
    base_snapshot = _snapshot(base_forest, revision=BASE_REVISION)
    delta_snapshot = _snapshot(delta_forest, revision=DELTA_REVISION)

    base_compiled, base_samples = _measure_repeated(
        lambda: _compile(base_forest, base_snapshot),
        repeats=repeats,
        warmup=warmup,
    )
    delta_compiled, delta_samples = _measure_repeated(
        lambda: _compile(delta_forest, delta_snapshot),
        repeats=repeats,
        warmup=warmup,
    )

    profiled = tuple(
        _profile_compile_once(delta_forest, delta_snapshot)
        for _ in range(profile_repeats)
    )
    if any(compiled.digest != delta_compiled.digest for compiled, _, _ in profiled):
        raise AssertionError("profiling changed canonical compiler output")
    profile_metrics = _median_profile_metrics(
        tuple(metrics for _, _, metrics in profiled)
    )
    profiled_wall = tuple(wall_ms for _, wall_ms, _ in profiled)
    compiler_cumulative = float(
        profile_metrics["compiler_total"]["cumulative_ms_median"]
    )
    block_reconstruction_cumulative = float(
        profile_metrics["selected_block_reconstruction"]["cumulative_ms_median"]
    )
    non_block_residual = max(
        0.0,
        compiler_cumulative - block_reconstruction_cumulative,
    )
    observed_edge_admission_cumulative = sum(
        float(profile_metrics[name]["cumulative_ms_median"])
        for name in (
            "edge_signature_construction",
            "edge_wire_materialization",
            "retained_relation_digest",
        )
    )
    fact_aggregation_direct_cumulative = float(
        profile_metrics["fact_aggregation_direct"]["cumulative_ms_median"]
    )
    remaining_non_block = max(
        0.0,
        non_block_residual
        - observed_edge_admission_cumulative
        - fact_aggregation_direct_cumulative,
    )

    base_entries = _entries(base_compiled)
    delta_entries = _entries(delta_compiled)
    added = tuple(sorted(delta_entries - base_entries))
    removed = tuple(sorted(base_entries - delta_entries))
    changed_count = len(added) + len(removed)
    if changed_count != 1 or len(added) != 1 or removed:
        raise AssertionError("bounded fixture must produce exactly one added coordinate")

    delta_block = delta_compiled.blocks[0][1]
    if delta_block.entry_count != len(delta_forest.edges):
        raise AssertionError("every bounded same-plane Forest edge must compile exactly once")

    delta_edge_count = len(delta_forest.edges)
    for metric_name in (
        "edge_signature_construction",
        "edge_wire_materialization",
        "retained_relation_digest",
        "fact_aggregation_direct",
    ):
        if int(profile_metrics[metric_name]["calls"]) != delta_edge_count:
            raise AssertionError(
                f"direct compiler attribution for {metric_name} lost one-call-per-edge scope"
            )

    partial_snapshot = _snapshot(
        delta_forest,
        revision=DELTA_REVISION,
        complete_code=False,
    )
    try:
        _compile(delta_forest, partial_snapshot)
    except ValueError as exc:
        partial_refusal = str(exc)
    else:
        raise AssertionError("partial endpoint plane unexpectedly compiled")
    if "complete endpoint planes" not in partial_refusal or "code=partial" not in partial_refusal:
        raise AssertionError("partial-plane refusal lost the canonical compiler contract")

    rebuild_entries_per_changed_coordinate = delta_block.entry_count / changed_count
    edge_scan_per_changed_coordinate = len(delta_forest.edges) / changed_count
    changed_fraction = changed_count / delta_block.entry_count
    base_median = statistics.median(base_samples)
    delta_median = statistics.median(delta_samples)

    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": (
            "one retained same-plane Boolean relation with fixed axis membership "
            "and one added fact"
        ),
        "measurement_contract": (
            "Measure only the existing compile_relation_blocks full-rebuild owner. "
            "No production delta path, trusted constructor, cache, second graph authority, "
            "backend registry or validation bypass is introduced or simulated. Profiling "
            "observes the real selected-block reconstruction and direct compiler callees for "
            "the same-plane edge-admission seam, then leaves all inline and unobserved work "
            "inside an explicit residual rather than inventing a second projection path."
        ),
        "case": {
            "nodes": nodes,
            "row_width": row_width,
            "base_revision": BASE_REVISION,
            "delta_revision": DELTA_REVISION,
            "base_forest_edges": len(base_forest.edges),
            "delta_forest_edges": len(delta_forest.edges),
            "base_output_entries": base_compiled.semantic_fact_count,
            "delta_output_entries": delta_compiled.semantic_fact_count,
            "changed_coordinate_count": changed_count,
            "added_entries": [list(item) for item in added],
            "removed_entries": [list(item) for item in removed],
            "base_compiled_digest": base_compiled.digest,
            "delta_compiled_digest": delta_compiled.digest,
        },
        "full_rebuild": {
            "base_compile_ms": _timing_summary(base_samples),
            "delta_compile_ms": _timing_summary(delta_samples),
            "delta_to_base_median_ratio": delta_median / base_median if base_median else None,
            "rebuild_entries_per_changed_coordinate": rebuild_entries_per_changed_coordinate,
            "forest_edges_scanned_per_changed_coordinate": edge_scan_per_changed_coordinate,
            "changed_coordinate_fraction_of_delta_output": changed_fraction,
            "interpretation": (
                "The amplification ratios are deterministic work-scope evidence, not an "
                "incremental-speedup claim. Wall timings describe ordinary full rebuilds only."
            ),
        },
        "full_rebuild_attribution": {
            "profile_repeats": profile_repeats,
            "profiled_compile_wall_ms": _timing_summary(profiled_wall),
            "profile_metrics": profile_metrics,
            "compiler_cumulative_ms_median": compiler_cumulative,
            "selected_block_reconstruction_cumulative_ms_median": (
                block_reconstruction_cumulative
            ),
            "non_block_compiler_residual_cumulative_ms_median": non_block_residual,
            "observed_same_plane_edge_admission_cumulative_ms_median": (
                observed_edge_admission_cumulative
            ),
            "fact_aggregation_direct_cumulative_ms_median": (
                fact_aggregation_direct_cumulative
            ),
            "remaining_non_block_after_observed_edge_and_fact_cumulative_ms_median": (
                remaining_non_block
            ),
            "selected_block_fraction_of_profiled_compiler_cumulative": (
                block_reconstruction_cumulative / compiler_cumulative
                if compiler_cumulative > 0.0
                else None
            ),
            "non_block_residual_fraction_of_profiled_compiler_cumulative": (
                non_block_residual / compiler_cumulative
                if compiler_cumulative > 0.0
                else None
            ),
            "observed_same_plane_edge_admission_fraction_of_profiled_compiler_cumulative": (
                observed_edge_admission_cumulative / compiler_cumulative
                if compiler_cumulative > 0.0
                else None
            ),
            "fact_aggregation_direct_fraction_of_profiled_compiler_cumulative": (
                fact_aggregation_direct_cumulative / compiler_cumulative
                if compiler_cumulative > 0.0
                else None
            ),
            "remaining_non_block_fraction_of_profiled_compiler_cumulative": (
                remaining_non_block / compiler_cumulative
                if compiler_cumulative > 0.0
                else None
            ),
            "interpretation": (
                "cProfile inclusive attribution only. selected_block_reconstruction is the "
                "real TypedRelationBlock._from_indexed call made by compile_relation_blocks. "
                "The observed same-plane edge-admission component is a conservative lower "
                "bound formed only from direct compiler calls to RelationSignature.__init__, "
                "ForestEdge.to_dict and canonical_sha; endpoint dictionary lookup, retained-set "
                "membership, branching, list append and other inline compiler work remain in "
                "the residual. fact_aggregation_direct is the direct _record_fact call from the "
                "same owner. These selected direct callees are disjoint at the compiler call "
                "site, but the remaining non-block value is still a broad compiler-envelope "
                "residual, not a pure edge-scan wall time. Profiled timings are diagnostic, "
                "distorted by profiling, and not additive to the unprofiled medians."
            ),
        },
        "fail_closed": {
            "partial_endpoint_plane": "refused",
            "message": partial_refusal,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "claim_boundaries": {
            "incremental_backend_implemented": False,
            "performance_superiority": False,
            "memory_superiority": False,
            "gpu_tensor_core_superiority": False,
            "tensor_vs_forest_superiority": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=512)
    parser.add_argument("--row-width", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--profile-repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_probe(
        nodes=args.nodes,
        row_width=args.row_width,
        repeats=args.repeats,
        warmup=args.warmup,
        profile_repeats=args.profile_repeats,
    )
    if args.output is not None:
        write_report(args.output, report)
    else:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
