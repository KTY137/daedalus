"""Measure full relation-block rebuild amplification for one tiny semantic delta.

This is a bounded diagnostic, not a production delta engine.  It keeps the
existing KnowledgeForest/Fourfold authorities and ``compile_relation_blocks``
as the only projection owner, then asks a narrower question: when one retained
same-plane relation fact changes while axis membership stays fixed, how much
canonical work is repeated by the required full rebuild today?

The probe deliberately does not implement or simulate a trusted incremental
constructor.  It reports the exact changed-coordinate scope, deterministic
input/output amplification, and ordinary full-rebuild wall timing.  Partial
endpoint planes are also exercised fail-closed so a future incremental design
cannot quietly reinterpret unknown sparse zeroes as complete facts.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
from pathlib import Path
from typing import Any, Sequence

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot, fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import CompiledRelationBlocks, compile_relation_blocks
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import write_report
    from .cpu_bitset_baseline import MAX_REPEATS, MAX_WARMUP, _measure_repeated
else:  # direct ``python experiments/tensor_gpu/relation_delta_rebuild_probe.py``
    from boolean_probe_contract import write_report
    from cpu_bitset_baseline import MAX_REPEATS, MAX_WARMUP, _measure_repeated

SCHEMA = "daedalus-tensor-relation-delta-rebuild/1"
MAX_NODES = 2_048
BASE_REVISION = "a" * 40
DELTA_REVISION = "b" * 40
CREATED_AT = "2026-09-08T19:02:06Z"
SIGNATURE = RelationSignature("code", "imports", "code")


def _validate_case(*, nodes: int, row_width: int, repeats: int, warmup: int) -> None:
    if type(nodes) is not int or not 4 <= nodes <= MAX_NODES:
        raise ValueError(f"nodes must be an integer from 4 to {MAX_NODES}")
    if type(row_width) is not int or not 1 <= row_width < nodes - 1:
        raise ValueError("row_width must be an integer from 1 to nodes - 2")
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(warmup) is not int or not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")


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


def _snapshot(forest: KnowledgeForest, *, revision: str, complete_code: bool = True) -> FourfoldSnapshot:
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


def _compile(forest: KnowledgeForest, snapshot: FourfoldSnapshot) -> CompiledRelationBlocks[bool]:
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


def run_probe(*, nodes: int = 512, row_width: int = 16, repeats: int = 7, warmup: int = 2) -> dict[str, Any]:
    _validate_case(nodes=nodes, row_width=row_width, repeats=repeats, warmup=warmup)

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

    partial_snapshot = _snapshot(delta_forest, revision=DELTA_REVISION, complete_code=False)
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
        "semantic_scope": "one retained same-plane Boolean relation with fixed axis membership and one added fact",
        "measurement_contract": (
            "Measure only the existing compile_relation_blocks full-rebuild owner. "
            "No production delta path, trusted constructor, cache, second graph authority, "
            "backend registry or validation bypass is introduced or simulated."
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
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_probe(
        nodes=args.nodes,
        row_width=args.row_width,
        repeats=args.repeats,
        warmup=args.warmup,
    )
    if args.output is not None:
        write_report(args.output, report)
    else:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
