"""One-shot valid-path probe for removing duplicate Fourfold label admission.

This experiment compares the canonical ``boolean_relation_block_from_fourfold``
adapter with a bounded candidate that keeps the adapter's exact Fourfold subject
and final ``TypedRelationBlock`` validation, but maps already-verified cross-plane
binding endpoints directly to the existing indexed block owner.  It is decision
evidence only: it does not create production authority, a trusted constructor,
or a second relation validator.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestNode, KnowledgeForest
from daedalus.twin.contracts import FOURFOLD_PLANES, CrossPlaneBinding, FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring

SCHEMA = "daedalus-fourfold-projection-index-probe/1"
REVISION = "a" * 40
EVIDENCE = "b" * 64
NOW = "2026-09-05T18:59:57Z"
MAX_SIZE = 512
MAX_PAIRS = 31
MAX_WARMUP = 7

T = TypeVar("T")


@dataclass(frozen=True)
class ProjectionCase:
    size: int
    density: float
    pairs: int
    warmup: int

    def __post_init__(self) -> None:
        if type(self.size) is not int or not 1 <= self.size <= MAX_SIZE:
            raise ValueError(f"size must be an integer from 1 to {MAX_SIZE}")
        if type(self.density) is not float or not 0.0 < self.density <= 1.0:
            raise ValueError("density must be a float in (0, 1]")
        if type(self.pairs) is not int or not 1 <= self.pairs <= MAX_PAIRS:
            raise ValueError(f"pairs must be an integer from 1 to {MAX_PAIRS}")
        if type(self.warmup) is not int or not 0 <= self.warmup <= MAX_WARMUP:
            raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")


def _fixture(case: ProjectionCase) -> tuple[KnowledgeForest, FourfoldSnapshot, RelationSignature, int]:
    width = min(case.size, max(1, round(case.size * case.density)))
    code_nodes = tuple(f"src/c{index:04d}.py" for index in range(case.size))
    type_nodes = tuple(f"type:src/c{index:04d}.py#T{index:04d}" for index in range(case.size))
    forest = KnowledgeForest(
        root="/bounded-fourfold-projection-probe",
        nodes=tuple(ForestNode(node_id, "source_file") for node_id in code_nodes)
        + tuple(ForestNode(node_id, "type") for node_id in type_nodes),
        edges=(),
        hyperedges=(),
        provenance={"origin": "experiment.fourfold-projection-index-probe"},
    )
    planes = (
        PlaneSnapshot("code", REVISION, "complete", code_nodes, evidence_sha256s=(EVIDENCE,)),
        PlaneSnapshot("type", REVISION, "complete", type_nodes, evidence_sha256s=(EVIDENCE,)),
        PlaneSnapshot("data", REVISION, "absent", reason="not used by bounded projection probe"),
        PlaneSnapshot("knowledge", REVISION, "absent", reason="not used by bounded projection probe"),
    )
    bindings = tuple(
        CrossPlaneBinding(
            source_plane="code",
            source_node_id=code_nodes[row],
            target_plane="type",
            target_node_id=type_nodes[(row + offset) % case.size],
            relation="has-type",
            source_revision=REVISION,
            evidence_sha256s=(EVIDENCE,),
        )
        for row in range(case.size)
        for offset in range(width)
    )
    if len(bindings) > MAX_BLOCK_ENTRIES:
        raise ValueError(f"fixture exceeds bounded entry limit {MAX_BLOCK_ENTRIES}")
    provenance = ContractProvenance(
        origin="experiment.fourfold-projection-index-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in bindings),
        ),
        trace_id=f"fourfold-projection-{case.size}-{width}",
    )
    snapshot = FourfoldSnapshot(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=bindings,
        provenance=provenance,
    )
    return forest, snapshot, RelationSignature("code", "has-type", "type"), len(bindings)


def _candidate(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    signature: RelationSignature,
) -> TypedRelationBlock[bool]:
    """Mirror only the valid cross-plane common path using the existing indexed owner."""
    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    if not isinstance(signature, RelationSignature):
        raise ValueError("signature must be a RelationSignature")
    if forest.content_sha256 != snapshot.source_forest_sha256:
        raise ValueError("relation projection requires the exact Forest bound by Fourfold")
    if signature.source_plane == signature.target_plane:
        raise ValueError("probe candidate is bounded to cross-plane relations")

    source_plane = snapshot.planes[FOURFOLD_PLANES.index(signature.source_plane)]
    target_plane = snapshot.planes[FOURFOLD_PLANES.index(signature.target_plane)]
    incomplete = sorted(
        plane.plane for plane in (source_plane, target_plane) if plane.status != "complete"
    )
    if incomplete:
        raise ValueError(
            "relation projection requires complete endpoint planes; "
            f"incomplete={incomplete}"
        )

    row_axis = TypedAxis(
        name=f"{signature.source_plane}-nodes",
        plane=signature.source_plane,
        labels=source_plane.node_ids,
    )
    column_axis = TypedAxis(
        name=f"{signature.target_plane}-nodes",
        plane=signature.target_plane,
        labels=target_plane.node_ids,
    )
    row_positions = {label: index for index, label in enumerate(row_axis.labels)}
    column_positions = {label: index for index, label in enumerate(column_axis.labels)}
    entries: dict[tuple[int, int], bool] = {}
    for binding in snapshot.bindings:
        if (
            binding.source_plane == signature.source_plane
            and binding.target_plane == signature.target_plane
            and binding.relation == signature.relation
        ):
            entries[(row_positions[binding.source_node_id], column_positions[binding.target_node_id])] = True
    return TypedRelationBlock._from_indexed(
        ProjectionSubject(
            repository_id=snapshot.repository_id,
            source_revision=snapshot.source_revision,
            source_fourfold_sha256=snapshot.digest,
        ),
        signature,
        row_axis,
        column_axis,
        entries,
        BooleanSemiring(),
    )


def _time_once(factory: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter_ns()
    result = factory()
    return result, (time.perf_counter_ns() - started) / 1_000_000.0


def _median(values: Sequence[float]) -> float:
    return float(statistics.median(values))


def run_case(case: ProjectionCase) -> dict[str, Any]:
    if not isinstance(case, ProjectionCase):
        raise ValueError("case must be ProjectionCase")
    forest, snapshot, signature, binding_count = _fixture(case)
    baseline_factory = lambda: boolean_relation_block_from_fourfold(forest, snapshot, signature)
    candidate_factory = lambda: _candidate(forest, snapshot, signature)

    baseline = baseline_factory()
    candidate = candidate_factory()
    if candidate != baseline or candidate.digest != baseline.digest or candidate.to_json() != baseline.to_json():
        raise AssertionError("candidate changed canonical Fourfold relation projection")

    for _ in range(case.warmup):
        baseline_factory()
        candidate_factory()

    baseline_samples: list[float] = []
    candidate_samples: list[float] = []
    for pair in range(case.pairs):
        ordered = (
            (("baseline", baseline_factory), ("candidate", candidate_factory))
            if pair % 2 == 0
            else (("candidate", candidate_factory), ("baseline", baseline_factory))
        )
        for name, factory in ordered:
            result, elapsed = _time_once(factory)
            if result.digest != baseline.digest:
                raise AssertionError("timed projection changed canonical digest")
            (baseline_samples if name == "baseline" else candidate_samples).append(elapsed)

    baseline_median = _median(baseline_samples)
    candidate_median = _median(candidate_samples)
    return {
        "status": "verified",
        "claim": "none",
        "case": {
            "size": case.size,
            "requested_density": case.density,
            "pairs": case.pairs,
            "warmup": case.warmup,
            "binding_count": binding_count,
        },
        "canonical_digest": baseline.digest,
        "baseline_ms": {
            "median": baseline_median,
            "min": min(baseline_samples),
            "max": max(baseline_samples),
        },
        "candidate_ms": {
            "median": candidate_median,
            "min": min(candidate_samples),
            "max": max(candidate_samples),
        },
        "candidate_to_baseline_ratio": candidate_median / baseline_median,
        "interpretation": (
            "Paired same-process valid cross-plane projection decision evidence only. "
            "The candidate reuses the existing _from_indexed owner and final canonical "
            "TypedRelationBlock validation; no production speedup claim is established."
        ),
    }


def run_probe(cases: Sequence[ProjectionCase]) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
        raise ValueError("cases must be a non-empty bounded sequence")
    if len(cases) > 8:
        raise ValueError("cases must contain at most 8 entries")
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "valid complete cross-plane Fourfold -> Boolean TypedRelationBlock projection",
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "cases": [run_case(case) for case in cases],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe duplicate Fourfold label admission removal.")
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--pairs", type=int, default=11)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = tuple(
        ProjectionCase(size=size, density=float(density), pairs=args.pairs, warmup=args.warmup)
        for size in args.sizes
        for density in args.densities
    )
    report = run_probe(cases)
    text = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    print(text)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
