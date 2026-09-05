"""One-shot same-plane Fourfold projection probe.

Compares the canonical adapter with one bounded candidate that preserves the
same-plane Forest refusal/error order while reusing the existing
TypedRelationBlock._from_indexed owner for already validated Forest labels.
Decision evidence only; no production authority or performance claim.
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
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, ForestHyperedge, ForestNode, KnowledgeForest
from daedalus.twin.contracts import FOURFOLD_PLANES, FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring

SCHEMA = "daedalus-fourfold-same-plane-index-probe/1"
REVISION = "a" * 40
EVIDENCE = "b" * 64
NOW = "2026-09-05T21:00:00Z"
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
        if type(self.size) is not int or not 2 <= self.size <= MAX_SIZE:
            raise ValueError(f"size must be an integer from 2 to {MAX_SIZE}")
        if type(self.density) is not float or not 0.0 < self.density <= 1.0:
            raise ValueError("density must be a float in (0, 1]")
        if type(self.pairs) is not int or not 1 <= self.pairs <= MAX_PAIRS:
            raise ValueError(f"pairs must be an integer from 1 to {MAX_PAIRS}")
        if type(self.warmup) is not int or not 0 <= self.warmup <= MAX_WARMUP:
            raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")


def _snapshot(
    forest: KnowledgeForest,
    *,
    code_node_ids: tuple[str, ...],
    relation_sha256s: tuple[str, ...],
    trace_id: str,
) -> FourfoldSnapshot:
    planes = (
        PlaneSnapshot(
            "code",
            REVISION,
            "complete",
            code_node_ids,
            relation_sha256s=relation_sha256s,
            evidence_sha256s=(EVIDENCE,),
        ),
        PlaneSnapshot("type", REVISION, "absent", reason="not used by bounded probe"),
        PlaneSnapshot("data", REVISION, "absent", reason="not used by bounded probe"),
        PlaneSnapshot("knowledge", REVISION, "absent", reason="not used by bounded probe"),
    )
    provenance = ContractProvenance(
        origin="experiment.fourfold-same-plane-index-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(forest.content_sha256, *(plane.digest for plane in planes)),
        trace_id=trace_id,
    )
    return FourfoldSnapshot(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=(),
        provenance=provenance,
    )


def _fixture(
    case: ProjectionCase,
) -> tuple[KnowledgeForest, FourfoldSnapshot, RelationSignature, int]:
    width = min(case.size - 1, max(1, round(case.size * case.density)))
    node_ids = tuple(f"src/c{index:04d}.py" for index in range(case.size))
    edges = tuple(
        ForestEdge(
            node_ids[row],
            node_ids[(row + offset + 1) % case.size],
            "imports",
            True,
            evidence=("probe.imports",),
        )
        for row in range(case.size)
        for offset in range(width)
    )
    if len(edges) > MAX_BLOCK_ENTRIES:
        raise ValueError(f"fixture exceeds bounded entry limit {MAX_BLOCK_ENTRIES}")
    forest = KnowledgeForest(
        root="/bounded-fourfold-same-plane-probe",
        nodes=tuple(ForestNode(node_id, "source_file") for node_id in node_ids),
        edges=edges,
        hyperedges=(),
        provenance={"origin": "experiment.fourfold-same-plane-index-probe"},
    )
    relation_sha256s = tuple(sorted(canonical_sha(edge.to_dict()) for edge in forest.edges))
    snapshot = _snapshot(
        forest,
        code_node_ids=node_ids,
        relation_sha256s=relation_sha256s,
        trace_id=f"fourfold-same-plane-{case.size}-{width}",
    )
    return forest, snapshot, RelationSignature("code", "imports", "code"), len(edges)


def _retains_digest(digests: tuple[str, ...], digest: str) -> bool:
    from bisect import bisect_left

    position = bisect_left(digests, digest)
    return position < len(digests) and digests[position] == digest


def _candidate(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    signature: RelationSignature,
) -> TypedRelationBlock[bool]:
    """Mirror only the same-plane path while preserving refusal/error order."""
    if not isinstance(forest, KnowledgeForest):
        raise ValueError("forest must be a KnowledgeForest")
    if not isinstance(snapshot, FourfoldSnapshot):
        raise ValueError("snapshot must be a FourfoldSnapshot")
    if not isinstance(signature, RelationSignature):
        raise ValueError("signature must be a RelationSignature")
    if forest.content_sha256 != snapshot.source_forest_sha256:
        raise ValueError("relation projection requires the exact Forest bound by Fourfold")
    if signature.source_plane != signature.target_plane:
        raise ValueError("probe candidate is bounded to same-plane relations")

    source_plane = snapshot.planes[FOURFOLD_PLANES.index(signature.source_plane)]
    if source_plane.status != "complete":
        raise ValueError(
            "relation projection requires complete endpoint planes; "
            f"incomplete={[source_plane.plane]}"
        )

    axis = TypedAxis(
        name=f"{signature.source_plane}-nodes",
        plane=signature.source_plane,
        labels=source_plane.node_ids,
    )
    subject = ProjectionSubject(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_fourfold_sha256=snapshot.digest,
    )
    semiring = BooleanSemiring()

    retained_digests = source_plane.relation_sha256s
    endpoints: list[tuple[str, str]] = []
    if retained_digests:
        for hyperedge in forest.hyperedges:
            if hyperedge.relation != signature.relation:
                continue
            digest = canonical_sha(hyperedge.to_dict())
            if _retains_digest(retained_digests, digest):
                raise ValueError(
                    "binary relation projection cannot flatten a retained ForestHyperedge"
                )

        for edge in forest.edges:
            if edge.relation != signature.relation:
                continue
            digest = canonical_sha(edge.to_dict())
            if not _retains_digest(retained_digests, digest):
                continue
            if not edge.directed:
                raise ValueError(
                    "binary relation projection requires an explicitly directed ForestEdge"
                )
            if len(endpoints) >= MAX_BLOCK_ENTRIES:
                raise ValueError(
                    f"relation projection exceeds bounded limit {MAX_BLOCK_ENTRIES}"
                )
            endpoints.append((edge.source, edge.target))

    entries: dict[tuple[int, int], bool] = {}
    if endpoints:
        positions = {label: position for position, label in enumerate(axis.labels)}
        for source, target in endpoints:
            row_position = positions.get(source)
            if row_position is None:
                raise ValueError(f"unknown row label {source!r}")
            column_position = positions.get(target)
            if column_position is None:
                raise ValueError(f"unknown column label {target!r}")
            entries[(row_position, column_position)] = True

    return TypedRelationBlock._from_indexed(
        subject,
        signature,
        axis,
        axis,
        entries,
        semiring,
    )


def _outcome(factory: Callable[[], TypedRelationBlock[bool]]) -> tuple[str, str, str]:
    try:
        block = factory()
    except Exception as exc:
        return ("error", type(exc).__name__, str(exc))
    return ("ok", block.digest, block.to_json())


def _semantic_cases() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    valid = ProjectionCase(size=8, density=0.25, pairs=1, warmup=0)
    forest, snapshot, signature, _ = _fixture(valid)
    cases: list[tuple[str, KnowledgeForest, FourfoldSnapshot, RelationSignature]] = [
        ("valid", forest, snapshot, signature)
    ]

    node_a, node_b = "src/a.py", "src/b.py"
    edge = ForestEdge(
        node_a,
        node_b,
        "imports",
        True,
        evidence=("probe.malformed-membership",),
    )
    malformed_forest = KnowledgeForest(
        root="/bounded-fourfold-same-plane-membership",
        nodes=(ForestNode(node_a, "source_file"), ForestNode(node_b, "source_file")),
        edges=(edge,),
        hyperedges=(),
        provenance={"origin": "experiment.fourfold-same-plane-index-probe.membership"},
    )
    edge_digest = canonical_sha(malformed_forest.edges[0].to_dict())
    missing_target = _snapshot(
        malformed_forest,
        code_node_ids=(node_a,),
        relation_sha256s=(edge_digest,),
        trace_id="same-plane-missing-target",
    )
    missing_source = _snapshot(
        malformed_forest,
        code_node_ids=(node_b,),
        relation_sha256s=(edge_digest,),
        trace_id="same-plane-missing-source",
    )
    cases.extend(
        (
            ("unknown-column", malformed_forest, missing_target, signature),
            ("unknown-row", malformed_forest, missing_source, signature),
        )
    )

    undirected_edge = ForestEdge(
        node_a,
        node_b,
        "imports",
        False,
        evidence=("probe.undirected",),
    )
    undirected_forest = KnowledgeForest(
        root="/bounded-fourfold-same-plane-undirected",
        nodes=(ForestNode(node_a, "source_file"), ForestNode(node_b, "source_file")),
        edges=(undirected_edge,),
        hyperedges=(),
        provenance={"origin": "experiment.fourfold-same-plane-index-probe.undirected"},
    )
    undirected_snapshot = _snapshot(
        undirected_forest,
        code_node_ids=(node_a, node_b),
        relation_sha256s=(canonical_sha(undirected_forest.edges[0].to_dict()),),
        trace_id="same-plane-undirected",
    )
    cases.append(("undirected", undirected_forest, undirected_snapshot, signature))

    hyperedge = ForestHyperedge(
        id="clone_exact:probe",
        relation="imports",
        members=(node_a, node_b),
        evidence=("probe.hyperedge",),
    )
    hyper_forest = KnowledgeForest(
        root="/bounded-fourfold-same-plane-hyperedge",
        nodes=(ForestNode(node_a, "source_file"), ForestNode(node_b, "source_file")),
        edges=(),
        hyperedges=(hyperedge,),
        provenance={"origin": "experiment.fourfold-same-plane-index-probe.hyperedge"},
    )
    hyper_snapshot = _snapshot(
        hyper_forest,
        code_node_ids=(node_a, node_b),
        relation_sha256s=(canonical_sha(hyper_forest.hyperedges[0].to_dict()),),
        trace_id="same-plane-hyperedge",
    )
    cases.append(("retained-hyperedge", hyper_forest, hyper_snapshot, signature))

    empty_snapshot = _snapshot(
        malformed_forest,
        code_node_ids=(node_a, node_b),
        relation_sha256s=(),
        trace_id="same-plane-empty-retention",
    )
    cases.append(("empty-retention", malformed_forest, empty_snapshot, signature))

    for name, case_forest, case_snapshot, case_signature in cases:
        baseline = _outcome(
            lambda f=case_forest, s=case_snapshot, sig=case_signature: boolean_relation_block_from_fourfold(f, s, sig)
        )
        candidate = _outcome(
            lambda f=case_forest, s=case_snapshot, sig=case_signature: _candidate(f, s, sig)
        )
        if baseline != candidate:
            raise AssertionError(
                f"same-plane candidate changed observable semantics for {name}: "
                f"baseline={baseline!r}, candidate={candidate!r}"
            )
        results.append(
            {
                "name": name,
                "outcome": baseline[0],
                "detail": baseline[1],
                "message": baseline[2] if baseline[0] == "error" else None,
            }
        )
    return results


def _time_once(factory: Callable[[], T]) -> tuple[T, float]:
    started = time.perf_counter_ns()
    result = factory()
    return result, (time.perf_counter_ns() - started) / 1_000_000.0


def run_case(case: ProjectionCase) -> dict[str, Any]:
    if not isinstance(case, ProjectionCase):
        raise ValueError("case must be ProjectionCase")
    forest, snapshot, signature, edge_count = _fixture(case)
    baseline_factory = lambda: boolean_relation_block_from_fourfold(forest, snapshot, signature)
    candidate_factory = lambda: _candidate(forest, snapshot, signature)

    baseline = baseline_factory()
    candidate = candidate_factory()
    if candidate != baseline or candidate.digest != baseline.digest or candidate.to_json() != baseline.to_json():
        raise AssertionError("candidate changed canonical same-plane Fourfold projection")

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
                raise AssertionError("timed same-plane projection changed canonical digest")
            (baseline_samples if name == "baseline" else candidate_samples).append(elapsed)

    baseline_median = float(statistics.median(baseline_samples))
    candidate_median = float(statistics.median(candidate_samples))
    return {
        "status": "verified",
        "claim": "none",
        "case": {
            "size": case.size,
            "requested_density": case.density,
            "pairs": case.pairs,
            "warmup": case.warmup,
            "edge_count": edge_count,
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
            "Paired same-process valid same-plane projection decision evidence only. "
            "The candidate preserves current scan/refusal ordering and explicit unknown-label "
            "errors before reusing _from_indexed; no production speedup claim is established."
        ),
    }


def run_probe(cases: Sequence[ProjectionCase]) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence) or not cases:
        raise ValueError("cases must be a non-empty bounded sequence")
    if len(cases) > 8:
        raise ValueError("cases must contain at most 8 entries")
    semantic_cases = _semantic_cases()
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": (
            "same-plane complete Fourfold -> Boolean TypedRelationBlock projection, including "
            "unknown-row/column membership and retained undirected/hyperedge refusals"
        ),
        "semantic_cases": semantic_cases,
        "semantic_case_count": len(semantic_cases),
        "semantic_mismatches": 0,
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "cases": [run_case(case) for case in cases],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe same-plane Fourfold label readmission.")
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
