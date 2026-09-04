"""Packed-CPU baseline for the CUDA Boolean Fourfold experiment.

This file is a benchmark arm, not a production backend. It reuses the exact
shared Boolean probe contract and semantic oracle used by the CUDA arm and asks
a narrower question first: how far can one get by packing each relation row
into a Python integer bitset and executing the Boolean composition with C-level
bigint OR operations?

A strong result here would raise the bar for CUDA: GPU complexity is useful only
when it beats a simpler CPU representation under the same revision-bound
subject and output semantics. Timings remain diagnostic-only and never mint
trust, promotion, or a benchmark-superiority claim.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    RelationSignature,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import (
        MAX_CASES,
        MAX_REPEATS,
        MAX_WARMUP,
        ProbeCase,
        build_boolean_case,
        estimate_dense_device_bytes,
        exact_reference_operation_count,
        ratio,
        same_support,
        write_report,
    )
else:  # direct ``python experiments/tensor_gpu/cpu_bitset_baseline.py``
    from boolean_probe_contract import (
        MAX_CASES,
        MAX_REPEATS,
        MAX_WARMUP,
        ProbeCase,
        build_boolean_case,
        estimate_dense_device_bytes,
        exact_reference_operation_count,
        ratio,
        same_support,
        write_report,
    )

SCHEMA = "daedalus-tensor-cpu-bitset-baseline/2"
T = TypeVar("T")


@dataclass(frozen=True)
class BitsetExecution:
    """One packed CPU execution split into reusable and one-shot costs."""

    block: TypedRelationBlock[bool]
    pack_ms: float
    validate_ms: float
    kernel_ms: tuple[float, ...]
    canonicalize_ms: float


def _validate_sampling(*, repeats: int, warmup: int) -> None:
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(warmup) is not int or not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")


def _measure_repeated(
    operation: Callable[[], T],
    *,
    repeats: int,
    warmup: int,
) -> tuple[T, tuple[float, ...]]:
    """Measure one already-admitted operation with identical sample policy.

    This helper intentionally owns only warmup/repeat mechanics. Callers retain
    responsibility for semantic admission and for deciding which preparation or
    canonicalization costs belong inside the timed callable.
    """

    if not callable(operation):
        raise ValueError("operation must be callable")
    _validate_sampling(repeats=repeats, warmup=warmup)
    for _ in range(warmup):
        operation()

    result: T | None = None
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        result = operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    if result is None:  # repeats is bounded to >= 1; keep the invariant local.
        raise AssertionError("repeated measurement produced no result")
    return result, tuple(samples)


def _validate_boolean_pair(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> None:
    if not isinstance(left, TypedRelationBlock) or not isinstance(right, TypedRelationBlock):
        raise ValueError("bitset operands must be TypedRelationBlock values")
    if left.semiring_name != "boolean" or right.semiring_name != "boolean":
        raise ValueError("bitset baseline supports the Boolean semiring only")
    if any(value is not True for value in left.values + right.values):
        raise ValueError("bitset baseline requires canonical stored Boolean support")
    if left.subject != right.subject:
        raise ValueError("bitset operands must bind the same exact Fourfold subject")
    if left.column_axis != right.row_axis:
        raise ValueError("bitset composition requires an exactly shared typed middle axis")


def pack_rows(block: TypedRelationBlock[bool]) -> tuple[int, ...]:
    """Pack every sorted CSR row into one non-negative Python integer."""

    if not isinstance(block, TypedRelationBlock) or block.semiring_name != "boolean":
        raise ValueError("pack_rows requires one Boolean TypedRelationBlock")
    rows: list[int] = []
    for row in range(len(block.row_axis.labels)):
        mask = 0
        for position in range(block.row_offsets[row], block.row_offsets[row + 1]):
            if block.values[position] is not True:
                raise ValueError("bitset baseline requires canonical stored Boolean support")
            mask |= 1 << block.column_indices[position]
        rows.append(mask)
    return tuple(rows)


def _validate_packed_rows(
    left_rows: Sequence[int],
    right_rows: Sequence[int],
) -> None:
    """Validate packed operands once before any timed kernel repetition."""

    if isinstance(left_rows, (str, bytes)) or isinstance(right_rows, (str, bytes)):
        raise ValueError("packed rows must be integer sequences")
    if any(type(value) is not int or value < 0 for value in left_rows):
        raise ValueError("left packed rows must be non-negative integers")
    if any(type(value) is not int or value < 0 for value in right_rows):
        raise ValueError("right packed rows must be non-negative integers")
    right_count = len(right_rows)
    if any(value.bit_length() > right_count for value in left_rows):
        raise ValueError("left bitset references a missing right row")


def _compose_packed_rows_unchecked(
    left_rows: Sequence[int],
    right_rows: Sequence[int],
) -> tuple[int, ...]:
    """Boolean matrix product for already validated packed operands."""

    output: list[int] = []
    for left_mask in left_rows:
        remaining = left_mask
        result = 0
        while remaining:
            least = remaining & -remaining
            middle = least.bit_length() - 1
            result |= right_rows[middle]
            remaining ^= least
        output.append(result)
    return tuple(output)


def compose_packed_rows(
    left_rows: Sequence[int],
    right_rows: Sequence[int],
) -> tuple[int, ...]:
    """Boolean matrix product over packed rows.

    Each set bit in a left row selects one complete right-row bitset. The
    Boolean semiring's OR-over-AND support therefore becomes a sequence of
    bigint OR operations implemented by CPython's native integer core. Direct
    callers retain strict validation; benchmark repetitions validate once in
    :func:`execute_bitset` and then time only the already-admitted kernel.
    """

    _validate_packed_rows(left_rows, right_rows)
    return _compose_packed_rows_unchecked(left_rows, right_rows)


def _block_from_masks(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
    masks: Sequence[int],
    *,
    relation: str,
) -> TypedRelationBlock[bool]:
    if len(masks) != len(left.row_axis.labels):
        raise ValueError("bitset output must contain every result row")
    column_count = len(right.column_axis.labels)
    offsets = [0]
    indices: list[int] = []
    values: list[bool] = []
    for mask in masks:
        if type(mask) is not int or mask < 0:
            raise ValueError("bitset output rows must be non-negative integers")
        if mask.bit_length() > column_count:
            raise ValueError("bitset output references an out-of-range result column")
        remaining = mask
        while remaining:
            least = remaining & -remaining
            indices.append(least.bit_length() - 1)
            values.append(True)
            if len(indices) > MAX_BLOCK_ENTRIES:
                raise ValueError(
                    f"bitset output exceeds TypedRelationBlock limit {MAX_BLOCK_ENTRIES}"
                )
            remaining ^= least
        offsets.append(len(indices))
    return TypedRelationBlock(
        subject=left.subject,
        signature=RelationSignature(
            left.signature.source_plane,
            relation,
            right.signature.target_plane,
        ),
        row_axis=left.row_axis,
        column_axis=right.column_axis,
        semiring_name="boolean",
        row_offsets=tuple(offsets),
        column_indices=tuple(indices),
        values=tuple(values),
    )


def execute_bitset(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
    *,
    repeats: int,
    warmup: int,
    relation: str = "cpu_bitset_composed",
) -> BitsetExecution:
    _validate_boolean_pair(left, right)
    _validate_sampling(repeats=repeats, warmup=warmup)

    started = time.perf_counter_ns()
    left_rows = pack_rows(left)
    right_rows = pack_rows(right)
    pack_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    _validate_packed_rows(left_rows, right_rows)
    validate_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    result_rows, kernel_ms = _measure_repeated(
        lambda: _compose_packed_rows_unchecked(left_rows, right_rows),
        repeats=repeats,
        warmup=warmup,
    )

    started = time.perf_counter_ns()
    block = _block_from_masks(left, right, result_rows, relation=relation)
    canonicalize_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return BitsetExecution(
        block=block,
        pack_ms=pack_ms,
        validate_ms=validate_ms,
        kernel_ms=kernel_ms,
        canonicalize_ms=canonicalize_ms,
    )


def run_case(case: ProbeCase) -> dict[str, Any]:
    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    started = time.perf_counter_ns()
    left, right, fixture = build_boolean_case(case)
    fixture_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    operations = exact_reference_operation_count(left, right)

    oracle: TypedRelationBlock[bool] | None = None
    oracle_samples: tuple[float, ...] = ()
    oracle_median: float | None = None
    if operations <= case.cpu_max_operations:
        oracle, oracle_samples = _measure_repeated(
            lambda: left.matmul(
                right,
                BooleanSemiring(),
                relation="cpu_bitset_composed",
                max_operations=case.cpu_max_operations,
            ),
            repeats=case.repeats,
            warmup=case.warmup,
        )
        oracle_median = float(statistics.median(oracle_samples))

    execution = execute_bitset(
        left,
        right,
        repeats=case.repeats,
        warmup=case.warmup,
    )
    kernel_median = float(statistics.median(execution.kernel_ms))
    one_shot_ms = (
        execution.pack_ms
        + execution.validate_ms
        + kernel_median
        + execution.canonicalize_ms
    )
    support_equal = None if oracle is None else same_support(oracle, execution.block)
    if support_equal is False:
        raise AssertionError("packed CPU bitset support differs from the stdlib CSR oracle")

    return {
        "status": "verified" if support_equal is True else "performance-only",
        "claim": "none",
        "case": {
            "size": case.size,
            "repeats": case.repeats,
            "warmup": case.warmup,
            **fixture,
        },
        "construction": {
            "typed_csr_inputs_ms": fixture_ms,
            "reference_operation_count": operations,
            "cuda_dense_device_bytes_for_same_case": estimate_dense_device_bytes(case),
        },
        "cpu_reference": {
            "status": "verified" if oracle is not None else "skipped-operation-bound",
            "elapsed_ms_median": oracle_median,
            "elapsed_ms_min": None if not oracle_samples else min(oracle_samples),
            "elapsed_ms_max": None if not oracle_samples else max(oracle_samples),
            "samples": len(oracle_samples),
            "output_entries": None if oracle is None else oracle.entry_count,
            "digest": None if oracle is None else oracle.digest,
        },
        "cpu_bitset": {
            "pack_ms": execution.pack_ms,
            "validate_ms": execution.validate_ms,
            "kernel_ms_median": kernel_median,
            "kernel_ms_min": min(execution.kernel_ms),
            "kernel_ms_max": max(execution.kernel_ms),
            "samples": len(execution.kernel_ms),
            "canonicalize_ms": execution.canonicalize_ms,
            "one_shot_end_to_end_ms": one_shot_ms,
            "output_entries": execution.block.entry_count,
            "digest": execution.block.digest,
        },
        "correctness": {
            "cpu_oracle_executed": oracle is not None,
            "boolean_support_equal": support_equal,
        },
        "diagnostic_ratios": {
            "csr_full_operation_over_resident_bitset_kernel": ratio(
                oracle_median, kernel_median
            ),
            "csr_full_operation_over_bitset_one_shot": ratio(
                oracle_median, one_shot_ms
            ),
        },
    }


def run_probe(cases: Sequence[ProbeCase]) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")
    results = tuple(run_case(case) for case in cases)
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "Boolean relation support only",
        "measurement_contract": (
            "CSR reference and resident bitset kernel use the same warmup/repeat "
            "policy in one process; bitset one-shot additionally includes pack, "
            "validation and canonical reconstruction."
        ),
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "int_bits_per_digit": sys.int_info.bits_per_digit,
            "int_bytes_per_digit": sys.int_info.sizeof_digit,
        },
        "cases": list(results),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare exact stdlib Boolean CSR composition with packed Python-int "
            "bitsets before paying CUDA transfer/backend complexity."
        )
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256, 512))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument(
        "--cpu-max-operations",
        type=int,
        default=5_000_000,
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = tuple(
        ProbeCase(
            size=size,
            density=float(density),
            repeats=args.repeats,
            warmup=args.warmup,
            max_device_mib=64,
            cpu_max_operations=args.cpu_max_operations,
        )
        for size in args.sizes
        for density in args.densities
    )
    report = run_probe(cases)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if args.output is not None:
        write_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
