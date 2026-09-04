"""Shared exact contract for the bounded Boolean CPU/CUDA Tensor probes.

This module owns only deterministic fixture identity, common bounds, comparison
helpers, and report persistence.  It is not a backend, scheduler, registry, or
source of Fourfold truth.  Physical execution remains in the separate packed
CPU and CUDA experiment arms, while ``TypedRelationBlock`` plus
``BooleanSemiring`` remains the semantic oracle.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    MAX_REFERENCE_OPERATIONS,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

MAX_AXIS = 8_192
MAX_CASES = 32
MAX_REPEATS = 100
MAX_WARMUP = 50
MAX_DEVICE_MIB = 32_768
SUPPORTED_DTYPES = frozenset({"float16", "bfloat16"})
MIB = 1024 * 1024
INT64_BYTES = 8


@dataclass(frozen=True)
class ProbeCase:
    size: int
    density: float
    repeats: int = 20
    warmup: int = 5
    dtype_name: str = "float16"
    tile_multiple: int = 8
    max_device_mib: int = 1_024
    cpu_max_operations: int = MAX_REFERENCE_OPERATIONS

    def __post_init__(self) -> None:
        if type(self.size) is not int or not 2 <= self.size <= MAX_AXIS:
            raise ValueError(f"size must be an integer from 2 to {MAX_AXIS}")
        if type(self.density) is not float or not math.isfinite(self.density):
            raise ValueError("density must be a finite float")
        if not 0.0 < self.density <= 1.0:
            raise ValueError("density must be in (0, 1]")
        if type(self.repeats) is not int or not 1 <= self.repeats <= MAX_REPEATS:
            raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
        if type(self.warmup) is not int or not 0 <= self.warmup <= MAX_WARMUP:
            raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")
        if self.dtype_name not in SUPPORTED_DTYPES:
            raise ValueError(f"dtype_name must be one of {sorted(SUPPORTED_DTYPES)}")
        if self.tile_multiple not in (8, 16):
            raise ValueError("tile_multiple must be 8 or 16")
        if (
            type(self.max_device_mib) is not int
            or not 64 <= self.max_device_mib <= MAX_DEVICE_MIB
        ):
            raise ValueError(
                f"max_device_mib must be an integer from 64 to {MAX_DEVICE_MIB}"
            )
        if (
            type(self.cpu_max_operations) is not int
            or not 0 <= self.cpu_max_operations <= MAX_REFERENCE_OPERATIONS
        ):
            raise ValueError(
                "cpu_max_operations must be a bounded non-negative integer"
            )
        width = row_width(self.size, self.density)
        if self.size * width > MAX_BLOCK_ENTRIES:
            raise ValueError(
                "input relation exceeds TypedRelationBlock entry limit; "
                f"size={self.size}, row_width={width}, entries={self.size * width}"
            )


def row_width(size: int, density: float) -> int:
    return max(1, min(size, int(round(size * density))))


def padded(value: int, multiple: int) -> int:
    return ((value + multiple - 1) // multiple) * multiple


def dtype_bytes(dtype_name: str) -> int:
    if dtype_name not in SUPPORTED_DTYPES:
        raise ValueError(f"unsupported dtype {dtype_name!r}")
    return 2


def estimate_dense_device_bytes(case: ProbeCase) -> int:
    """Conservative explicit allocation estimate before CUDA admission.

    The dense resident set is two inputs, one GEMM output, and one Boolean
    support mask. Packing one CSR block also creates int64 row and column index
    tensors; the two inputs are packed sequentially, so only one such pair is
    counted at peak. cuBLAS workspace is implementation-owned and cannot be
    predicted here, which is why CUDA admission additionally reserves half of
    free VRAM as headroom and runtime OOM remains blocked evidence.
    """

    padded_size = padded(case.size, case.tile_multiple)
    cells = padded_size * padded_size
    dense_bytes = cells * (3 * dtype_bytes(case.dtype_name) + 1)
    input_entries = case.size * row_width(case.size, case.density)
    scatter_index_bytes = input_entries * 2 * INT64_BYTES
    return dense_bytes + scatter_index_bytes


def _coprime_step(size: int, salt: int) -> int:
    step = (2 * salt + 1) % size
    if step == 0:
        step = 1
    while math.gcd(step, size) != 1:
        step = (step + 2) % size
        if step == 0:
            step = 1
    return step


def _relation_coordinates(
    labels: tuple[str, ...],
    *,
    width: int,
    salt: int,
) -> tuple[tuple[str, str, bool], ...]:
    size = len(labels)
    step = _coprime_step(size, salt)
    coordinates: list[tuple[str, str, bool]] = []
    for row in range(size):
        base = (row * (2 * salt + 17) + salt) % size
        for offset in range(width):
            column = (base + offset * step) % size
            coordinates.append((labels[row], labels[column], True))
    return tuple(coordinates)


def build_boolean_case(
    case: ProbeCase,
) -> tuple[TypedRelationBlock[bool], TypedRelationBlock[bool], dict[str, Any]]:
    """Build two exact typed relations with one shared middle axis."""

    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    labels = tuple(f"node-{index:05d}" for index in range(case.size))
    source_axis = TypedAxis("source-nodes", "code", labels)
    middle_axis = TypedAxis("middle-nodes", "code", labels)
    target_axis = TypedAxis("target-nodes", "code", labels)
    subject = ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision="a" * 40,
        source_fourfold_sha256=hashlib.sha256(
            f"cuda-probe:{case.size}:{case.density:.12g}".encode("utf-8")
        ).hexdigest(),
    )
    width = row_width(case.size, case.density)
    boolean = BooleanSemiring()
    left = TypedRelationBlock.from_coordinates(
        subject=subject,
        signature=RelationSignature("code", "cuda_probe_left", "code"),
        row_axis=source_axis,
        column_axis=middle_axis,
        coordinates=_relation_coordinates(labels, width=width, salt=19),
        semiring=boolean,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=subject,
        signature=RelationSignature("code", "cuda_probe_right", "code"),
        row_axis=middle_axis,
        column_axis=target_axis,
        coordinates=_relation_coordinates(labels, width=width, salt=43),
        semiring=boolean,
    )
    return left, right, {
        "requested_density": case.density,
        "actual_density": width / case.size,
        "row_width": width,
        "left_entries": left.entry_count,
        "right_entries": right.entry_count,
    }


def exact_reference_operation_count(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> int:
    if left.column_axis != right.row_axis:
        raise ValueError("operation count requires an exactly shared middle axis")
    return sum(
        right.row_offsets[middle + 1] - right.row_offsets[middle]
        for middle in left.column_indices
    )


def same_support(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> bool:
    return (
        left.subject == right.subject
        and left.row_axis == right.row_axis
        and left.column_axis == right.column_axis
        and tuple(left.iter_entries()) == tuple(right.iter_entries())
    )


def ratio(numerator: float | None, denominator: float) -> float | None:
    if numerator is None or denominator <= 0.0:
        return None
    return numerator / denominator


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = [
    "INT64_BYTES",
    "MAX_AXIS",
    "MAX_CASES",
    "MAX_DEVICE_MIB",
    "MAX_REPEATS",
    "MAX_WARMUP",
    "MIB",
    "ProbeCase",
    "SUPPORTED_DTYPES",
    "build_boolean_case",
    "dtype_bytes",
    "estimate_dense_device_bytes",
    "exact_reference_operation_count",
    "padded",
    "ratio",
    "row_width",
    "same_support",
    "write_report",
]
