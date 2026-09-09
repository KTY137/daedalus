"""Measure the authority cost of mapping Fourfold relation-digest deltas back to Forest edges.

This diagnostic reuses the existing relation-delta fixture and canonical
``compile_relation_blocks`` owner.  It does not implement an incremental
compiler, cache, digest index, trusted constructor, or second graph authority.
The probe asks a narrower question: once an existing before/after owner has two
authoritative Forest/Fourfold pairs, how much canonical Forest work is still
required to turn changed ``PlaneSnapshot.relation_sha256s`` into concrete
changed-edge/signature scope?
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Sequence

from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, KnowledgeForest
from daedalus.twin.projection_verifier import _forest_node_partition
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import write_report
    from . import relation_delta_rebuild_probe as _base
else:  # direct ``python experiments/tensor_gpu/relation_delta_authority_probe.py``
    from boolean_probe_contract import write_report
    import relation_delta_rebuild_probe as _base

SCHEMA = "daedalus-tensor-relation-delta-authority/1"
MAX_SCAN_REPEATS = 10


def _validate_scan_repeats(value: int) -> None:
    if type(value) is not int or not 1 <= value <= MAX_SCAN_REPEATS:
        raise ValueError(f"scan_repeats must be an integer from 1 to {MAX_SCAN_REPEATS}")


def _plane_relation_digests(snapshot: Any) -> dict[str, frozenset[str]]:
    return {
        plane.plane: frozenset(plane.relation_sha256s)
        for plane in snapshot.planes
    }


def _relation_digest_delta(base_snapshot: Any, candidate_snapshot: Any) -> dict[str, dict[str, tuple[str, ...]]]:
    base = _plane_relation_digests(base_snapshot)
    candidate = _plane_relation_digests(candidate_snapshot)
    planes = tuple(sorted(set(base) | set(candidate)))
    return {
        plane: {
            "added": tuple(sorted(candidate.get(plane, frozenset()) - base.get(plane, frozenset()))),
            "removed": tuple(sorted(base.get(plane, frozenset()) - candidate.get(plane, frozenset()))),
        }
        for plane in planes
    }


def _locate_changed_edges(
    forest: KnowledgeForest,
    snapshot: Any,
    target_digests: frozenset[str],
) -> tuple[tuple[tuple[str, ForestEdge], ...], tuple[RelationSignature, ...], int, int]:
    """Locate target same-plane digests without inventing a persistent digest index.

    The scan stops as soon as every requested digest is found.  Because the
    bounded fixture appends its one changed edge last, this exposes the actual
    worst-position rehash count without forcing a synthetic full scan when an
    earlier match would have been sufficient.
    """

    if not target_digests:
        return (), (), 0, 0

    node_plane = _forest_node_partition(forest, snapshot)
    remaining = set(target_digests)
    matches: list[tuple[str, ForestEdge]] = []
    signatures: set[RelationSignature] = set()
    examined = 0
    hashed = 0

    for edge in forest.edges:
        examined += 1
        source_plane = node_plane.get(edge.source)
        target_plane = node_plane.get(edge.target)
        if source_plane is None or target_plane is None or source_plane != target_plane:
            continue
        hashed += 1
        digest = canonical_sha(edge.to_dict())
        if digest not in remaining:
            continue
        matches.append((digest, edge))
        signatures.add(RelationSignature(source_plane, edge.relation, target_plane))
        remaining.remove(digest)
        if not remaining:
            break

    if remaining:
        raise AssertionError(
            "changed Fourfold relation digests were not present in the supplied authoritative Forest"
        )
    return tuple(matches), tuple(sorted(signatures)), examined, hashed


def _timed_locate(
    forest: KnowledgeForest,
    snapshot: Any,
    target_digests: frozenset[str],
    *,
    repeats: int,
) -> tuple[tuple[tuple[str, ForestEdge], ...], tuple[RelationSignature, ...], dict[str, float | int]]:
    samples: list[float] = []
    result: tuple[tuple[tuple[str, ForestEdge], ...], tuple[RelationSignature, ...], int, int] | None = None
    for _ in range(repeats):
        started = time.perf_counter_ns()
        current = _locate_changed_edges(forest, snapshot, target_digests)
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
        if result is None:
            result = current
        elif current[0] != result[0] or current[1:] != result[1:]:
            raise AssertionError("changed-edge scan drifted inside one frozen case")
    assert result is not None
    matches, signatures, examined, hashed = result
    return matches, signatures, {
        "samples": len(samples),
        "median_ms": statistics.median(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "forest_edges_examined": examined,
        "same_plane_edges_hashed": hashed,
    }


def _signature_payload(signatures: Sequence[RelationSignature]) -> list[list[str]]:
    return [
        [signature.source_plane, signature.relation, signature.target_plane]
        for signature in signatures
    ]


def run_probe(
    *,
    nodes: int = 512,
    row_width: int = 16,
    scan_repeats: int = 5,
) -> dict[str, Any]:
    _base._validate_case(
        nodes=nodes,
        row_width=row_width,
        repeats=1,
        warmup=0,
        profile_repeats=1,
    )
    _validate_scan_repeats(scan_repeats)

    base_forest = _base._forest(
        nodes=nodes,
        row_width=row_width,
        revision=_base.BASE_REVISION,
        add_delta=False,
    )
    candidate_forest = _base._forest(
        nodes=nodes,
        row_width=row_width,
        revision=_base.DELTA_REVISION,
        add_delta=True,
    )
    base_snapshot = _base._snapshot(base_forest, revision=_base.BASE_REVISION)
    candidate_snapshot = _base._snapshot(candidate_forest, revision=_base.DELTA_REVISION)

    digest_delta = _relation_digest_delta(base_snapshot, candidate_snapshot)
    added_digests = frozenset(
        digest
        for plane in digest_delta.values()
        for digest in plane["added"]
    )
    removed_digests = frozenset(
        digest
        for plane in digest_delta.values()
        for digest in plane["removed"]
    )

    added_matches, added_signatures, added_scan = _timed_locate(
        candidate_forest,
        candidate_snapshot,
        added_digests,
        repeats=scan_repeats,
    )
    removed_matches, removed_signatures, removed_scan = _timed_locate(
        base_forest,
        base_snapshot,
        removed_digests,
        repeats=scan_repeats,
    )
    affected_signatures = tuple(sorted(set(added_signatures) | set(removed_signatures)))
    if not affected_signatures:
        raise AssertionError("bounded fixture unexpectedly produced no affected relation signature")

    oracle = _base._compile(candidate_forest, candidate_snapshot)
    selected = compile_relation_blocks(
        candidate_forest,
        candidate_snapshot,
        BooleanSemiring(),
        signatures=affected_signatures,
        include_verified_bindings=False,
    )
    if selected.digest != oracle.digest:
        raise AssertionError("affected-signature selection diverged from ordinary full compiler oracle")

    changed_digest_count = len(added_digests) + len(removed_digests)
    located_digest_count = len(added_matches) + len(removed_matches)
    if changed_digest_count != located_digest_count:
        raise AssertionError("changed relation digest scope did not map one-for-one to Forest edges")

    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "case": {
            "nodes": nodes,
            "row_width": row_width,
            "base_revision": base_snapshot.source_revision,
            "candidate_revision": candidate_snapshot.source_revision,
            "base_forest_sha256": base_snapshot.source_forest_sha256,
            "candidate_forest_sha256": candidate_snapshot.source_forest_sha256,
            "base_forest_edges": len(base_forest.edges),
            "candidate_forest_edges": len(candidate_forest.edges),
        },
        "relation_digest_delta": {
            plane: {
                "added": list(delta["added"]),
                "removed": list(delta["removed"]),
            }
            for plane, delta in digest_delta.items()
        },
        "changed_digest_count": changed_digest_count,
        "affected_signatures": _signature_payload(affected_signatures),
        "mapping_cost": {
            "added": added_scan,
            "removed": removed_scan,
            "candidate_hashes_per_added_digest": (
                added_scan["same_plane_edges_hashed"] / len(added_digests)
                if added_digests
                else 0.0
            ),
            "base_hashes_per_removed_digest": (
                removed_scan["same_plane_edges_hashed"] / len(removed_digests)
                if removed_digests
                else 0.0
            ),
            "interpretation": (
                "The snapshot delta identifies changed canonical relation digests cheaply, but the "
                "current authority surface has no digest-to-ForestEdge map. This diagnostic therefore "
                "rehashes same-plane Forest edges until every changed digest is located. Timings are "
                "diagnostic only; deterministic examined/hash counts are the primary evidence."
            ),
        },
        "oracle": {
            "full_compile_digest": oracle.digest,
            "affected_signature_compile_digest": selected.digest,
            "equal": selected.digest == oracle.digest,
        },
        "gardener_boundary": {
            "production_incremental_backend_added": False,
            "digest_index_added": False,
            "compiler_cache_added": False,
            "parallel_graph_authority_added": False,
            "trusted_constructor_added": False,
        },
        "claim_boundaries": {
            "performance_superiority": False,
            "memory_superiority": False,
            "tensor_vs_forest_superiority": False,
            "gpu_tensor_core_superiority": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=512)
    parser.add_argument("--row-width", type=int, default=16)
    parser.add_argument("--scan-repeats", type=int, default=5)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_probe(
        nodes=args.nodes,
        row_width=args.row_width,
        scan_repeats=args.scan_repeats,
    )
    if args.output is not None:
        write_report(args.output, report)
    else:
        print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
