"""Profile real reference Fourfold relation shapes without changing kernel policy.

This experiment compiles existing bounded reference projects through the canonical
``compile_reference_project`` -> ``compile_relation_blocks`` path and reports
revision-bound CSR degree/fan-out structure. It is diagnostic only: Forest and
Fourfold remain authoritative, no backend is selected, and no performance claim
is inferred from structural operation counts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from daedalus.twin.reference_compiler import compile_reference_project
from daedalus.twin.relation_blocks import TypedRelationBlock
from daedalus.twin.relation_compiler import compile_relation_blocks
from daedalus.twin.semiring import BooleanSemiring

SCHEMA = "daedalus-tensor-relation-shape/1"
MAX_PROJECTS = 8


def _nearest_rank(values: Sequence[int], percentile: int) -> int:
    """Return a deterministic nearest-rank percentile for non-negative integers."""

    if not values:
        return 0
    if type(percentile) is not int or not 1 <= percentile <= 100:
        raise ValueError("percentile must be an integer from 1 to 100")
    ordered = sorted(values)
    rank = (percentile * len(ordered) + 99) // 100
    return ordered[rank - 1]


def _row_degrees(block: TypedRelationBlock[Any]) -> tuple[int, ...]:
    return tuple(
        block.row_offsets[row + 1] - block.row_offsets[row]
        for row in range(len(block.row_axis.labels))
    )


def _profile_block(name: str, block: TypedRelationBlock[Any]) -> dict[str, Any]:
    degrees = _row_degrees(block)
    rows = len(block.row_axis.labels)
    columns = len(block.column_axis.labels)
    cells = rows * columns
    return {
        "name": name,
        "signature": block.signature.to_dict(),
        "rows": rows,
        "columns": columns,
        "entries": block.entry_count,
        "density": (block.entry_count / cells) if cells else 0.0,
        "nonempty_rows": sum(degree > 0 for degree in degrees),
        "out_degree": {
            "mean": (sum(degrees) / rows) if rows else 0.0,
            "p50": _nearest_rank(degrees, 50),
            "p95": _nearest_rank(degrees, 95),
            "max": max(degrees, default=0),
        },
    }


def _reference_matmul_shape(
    left: TypedRelationBlock[Any],
    right: TypedRelationBlock[Any],
) -> tuple[int, int]:
    """Measure current Boolean CSR nested work and peak row-accumulator width."""

    if left.subject != right.subject or left.column_axis != right.row_axis:
        raise ValueError("relation blocks are not exactly composable")

    operations = 0
    peak_accumulator_entries = 0
    for row in range(len(left.row_axis.labels)):
        accumulator_columns: set[int] = set()
        for position in range(left.row_offsets[row], left.row_offsets[row + 1]):
            middle = left.column_indices[position]
            for right_position in range(
                right.row_offsets[middle],
                right.row_offsets[middle + 1],
            ):
                operations += 1
                accumulator_columns.add(right.column_indices[right_position])
        peak_accumulator_entries = max(
            peak_accumulator_entries,
            len(accumulator_columns),
        )
    return operations, peak_accumulator_entries


def _profile_compiled(compiled: Any) -> dict[str, Any]:
    blocks = tuple(compiled.blocks)
    relation_profiles = tuple(_profile_block(name, block) for name, block in blocks)
    composable_pairs: list[dict[str, Any]] = []
    for left_name, left in blocks:
        for right_name, right in blocks:
            if left.column_axis != right.row_axis:
                continue
            operations, peak_accumulator_entries = _reference_matmul_shape(left, right)
            composable_pairs.append(
                {
                    "left": left_name,
                    "right": right_name,
                    "middle_plane": left.signature.target_plane,
                    "reference_operations": operations,
                    "reference_peak_accumulator_entries": peak_accumulator_entries,
                    "left_entries": left.entry_count,
                    "right_entries": right.entry_count,
                }
            )
    composable_pairs.sort(key=lambda item: (item["left"], item["right"]))
    max_out_degree = max(
        (profile["out_degree"]["max"] for profile in relation_profiles),
        default=0,
    )
    max_reference_operations = max(
        (item["reference_operations"] for item in composable_pairs),
        default=0,
    )
    return {
        "subject": compiled.subject.to_dict(),
        "subject_digest": compiled.subject.digest,
        "relation_count": len(blocks),
        "semantic_fact_count": compiled.semantic_fact_count,
        "relations": list(relation_profiles),
        "composable_pair_count": len(composable_pairs),
        "composable_pairs": composable_pairs,
        "observed_max_out_degree": max_out_degree,
        "observed_max_reference_operations": max_reference_operations,
    }


def profile_reference_project(
    root: str | Path,
    *,
    source_revision: str,
    created_at: str,
) -> dict[str, Any]:
    """Compile one real bounded reference project and profile its Boolean CSR view."""

    project_root = Path(root).resolve()
    reference = compile_reference_project(
        project_root,
        source_revision=source_revision,
        created_at=created_at,
        trace_id="tensor-relation-shape-probe",
    )
    compiled = compile_relation_blocks(
        reference.forest,
        reference.snapshot,
        BooleanSemiring(),
    )
    return {
        "repository_id": reference.snapshot.repository_id,
        "compile_inputs": {
            "source_revision": source_revision,
            "created_at": created_at,
        },
        "forest_sha256": reference.forest.content_sha256,
        "fourfold_sha256": reference.snapshot.digest,
        **_profile_compiled(compiled),
    }


def run_probe(
    project_roots: Sequence[str | Path],
    *,
    source_revision: str,
    created_at: str,
) -> dict[str, Any]:
    if isinstance(project_roots, (str, bytes)) or not isinstance(project_roots, Sequence):
        raise ValueError("project_roots must be a bounded sequence")
    if not project_roots or len(project_roots) > MAX_PROJECTS:
        raise ValueError(f"project_roots must contain between 1 and {MAX_PROJECTS} entries")

    resolved = tuple(Path(root).resolve() for root in project_roots)
    if len(set(resolved)) != len(resolved):
        raise ValueError("project_roots must not contain duplicates")

    projects = [
        profile_reference_project(
            root,
            source_revision=source_revision,
            created_at=created_at,
        )
        for root in resolved
    ]
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "projects": projects,
        "aggregate": {
            "project_count": len(projects),
            "relation_count": sum(item["relation_count"] for item in projects),
            "semantic_fact_count": sum(item["semantic_fact_count"] for item in projects),
            "composable_pair_count": sum(item["composable_pair_count"] for item in projects),
            "observed_max_out_degree": max(
                (item["observed_max_out_degree"] for item in projects),
                default=0,
            ),
            "observed_max_reference_operations": max(
                (item["observed_max_reference_operations"] for item in projects),
                default=0,
            ),
        },
        "gardener_boundary": {
            "production_backend_added": False,
            "adaptive_matmul_path_added": False,
            "persistent_index_or_cache_added": False,
            "parallel_graph_authority_added": False,
        },
        "claim_boundaries": {
            "performance_superiority": False,
            "tensor_vs_forest_superiority": False,
            "gpu_superiority": False,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_roots", nargs="+")
    parser.add_argument("--source-revision", default="0" * 64)
    parser.add_argument("--created-at", default="2026-09-11T00:00:00Z")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report = run_probe(
        args.project_roots,
        source_revision=args.source_revision,
        created_at=args.created_at,
    )
    text = json.dumps(report, sort_keys=True, indent=2) + "\n"
    if args.output is None:
        print(text, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
