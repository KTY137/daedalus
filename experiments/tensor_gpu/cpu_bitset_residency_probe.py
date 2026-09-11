"""Packed Boolean chain probe for intermediate-representation residency.

This is a contained experiment, not a production cache or backend.  It extends
the existing packed-CPU Boolean baseline by asking whether a multi-relation
composition should keep intermediate support as Python-int bitsets instead of
materializing a canonical ``TypedRelationBlock`` after every contraction.

The canonical stdlib CSR ``TypedRelationBlock.matmul`` interpreter remains the
semantic oracle.  The resident path packs exact typed inputs once, keeps only
regenerable bit masks between contractions, and reconstructs one canonical
block at the final evidence boundary.  Timings are diagnostic-only and cannot
mint trust, promotion, or a benchmark-superiority claim.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from daedalus.twin.relation_blocks import RelationSignature, TypedAxis, TypedRelationBlock
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import (
        MAX_CASES,
        ProbeCase,
        build_boolean_case,
        exact_reference_operation_count,
        ratio,
        same_support,
        write_report,
    )
    from .cpu_bitset_baseline import (
        _block_from_masks,
        _compose_packed_rows_unchecked,
        _measure_repeated,
        _validate_boolean_pair,
        _validate_packed_rows,
        _validate_sampling,
        compose_packed_rows,
        pack_rows,
    )
else:  # direct ``python experiments/tensor_gpu/cpu_bitset_residency_probe.py``
    from boolean_probe_contract import (
        MAX_CASES,
        ProbeCase,
        build_boolean_case,
        exact_reference_operation_count,
        ratio,
        same_support,
        write_report,
    )
    from cpu_bitset_baseline import (
        _block_from_masks,
        _compose_packed_rows_unchecked,
        _measure_repeated,
        _validate_boolean_pair,
        _validate_packed_rows,
        _validate_sampling,
        compose_packed_rows,
        pack_rows,
    )

SCHEMA = "daedalus-tensor-cpu-bitset-residency/1"
MAX_CHAIN_RELATIONS = 6
FINAL_RELATION = "cpu_bitset_resident_chain"


@dataclass(frozen=True)
class ResidentChainExecution:
    """One chain execution split into reusable and evidence-boundary costs."""

    block: TypedRelationBlock[bool]
    pack_ms: float
    validate_ms: float
    kernel_ms: tuple[float, ...]
    canonicalize_ms: float


def _validate_relation_count(value: int) -> int:
    if type(value) is not int or not 2 <= value <= MAX_CHAIN_RELATIONS:
        raise ValueError(
            f"relation_count must be an integer from 2 to {MAX_CHAIN_RELATIONS}"
        )
    return value


def _stage_relation(stage: int, composition_count: int) -> str:
    if stage == composition_count:
        return FINAL_RELATION
    return f"cpu_bitset_resident_stage_{stage:02d}"


def build_boolean_chain(
    case: ProbeCase,
    *,
    relation_count: int,
) -> tuple[tuple[TypedRelationBlock[bool], ...], dict[str, Any]]:
    """Build one exact typed chain without inventing a second fixture generator.

    The first two relations come from the shared CPU/CUDA fixture.  Additional
    tails reuse the exact sparse support arrays of the existing right relation
    while retagging only their typed row/column axes so every adjacent pair has
    an exact composition boundary.  This keeps the experiment deterministic and
    avoids a parallel synthetic graph generator.
    """

    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    relation_count = _validate_relation_count(relation_count)
    left, right, fixture = build_boolean_case(case)
    chain: list[TypedRelationBlock[bool]] = [left, right]
    template = right
    current_axis = right.column_axis

    for index in range(2, relation_count):
        next_axis = TypedAxis(
            f"resident-chain-{index + 1:02d}-nodes",
            current_axis.plane,
            current_axis.labels,
        )
        tail = TypedRelationBlock(
            subject=left.subject,
            signature=RelationSignature(
                current_axis.plane,
                f"cpu_bitset_resident_tail_{index:02d}",
                next_axis.plane,
            ),
            row_axis=current_axis,
            column_axis=next_axis,
            semiring_name="boolean",
            row_offsets=template.row_offsets,
            column_indices=template.column_indices,
            values=template.values,
        )
        chain.append(tail)
        current_axis = next_axis

    return tuple(chain), {
        **fixture,
        "relation_count": relation_count,
        "composition_count": relation_count - 1,
        "avoided_intermediate_materializations": max(0, relation_count - 2),
        "total_input_entries": sum(block.entry_count for block in chain),
    }


def _validate_chain(chain: Sequence[TypedRelationBlock[bool]]) -> None:
    if isinstance(chain, (str, bytes)) or not isinstance(chain, Sequence):
        raise ValueError("chain must be a bounded sequence")
    _validate_relation_count(len(chain))
    if any(not isinstance(block, TypedRelationBlock) for block in chain):
        raise ValueError("chain must contain TypedRelationBlock values")
    for left, right in zip(chain, chain[1:]):
        _validate_boolean_pair(left, right)


def _compose_packed_chain_unchecked(
    packed: Sequence[Sequence[int]],
) -> tuple[int, ...]:
    """Compose already admitted packed relations without materializing stages."""

    current = tuple(packed[0])
    for right_rows in packed[1:]:
        current = _compose_packed_rows_unchecked(current, right_rows)
    return current


def execute_resident_chain(
    chain: Sequence[TypedRelationBlock[bool]],
    *,
    repeats: int,
    warmup: int,
) -> ResidentChainExecution:
    """Measure a chain whose intermediate Boolean support remains packed."""

    _validate_chain(chain)
    _validate_sampling(repeats=repeats, warmup=warmup)

    started = time.perf_counter_ns()
    packed = tuple(pack_rows(block) for block in chain)
    pack_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    for left_rows, right_rows in zip(packed, packed[1:]):
        _validate_packed_rows(left_rows, right_rows)
    validate_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    result_rows, kernel_ms = _measure_repeated(
        lambda: _compose_packed_chain_unchecked(packed),
        repeats=repeats,
        warmup=warmup,
    )

    started = time.perf_counter_ns()
    block = _block_from_masks(
        chain[0],
        chain[-1],
        result_rows,
        relation=FINAL_RELATION,
    )
    canonicalize_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return ResidentChainExecution(
        block=block,
        pack_ms=pack_ms,
        validate_ms=validate_ms,
        kernel_ms=kernel_ms,
        canonicalize_ms=canonicalize_ms,
    )


def _canonicalized_bitset_chain_once(
    chain: Sequence[TypedRelationBlock[bool]],
) -> TypedRelationBlock[bool]:
    """Bitset composition that deliberately materializes every stage."""

    _validate_chain(chain)
    current = chain[0]
    composition_count = len(chain) - 1
    for stage, right in enumerate(chain[1:], start=1):
        left_rows = pack_rows(current)
        right_rows = pack_rows(right)
        masks = compose_packed_rows(left_rows, right_rows)
        current = _block_from_masks(
            current,
            right,
            masks,
            relation=_stage_relation(stage, composition_count),
        )
    return current


def _csr_chain_once(
    chain: Sequence[TypedRelationBlock[bool]],
    *,
    max_operations: int,
) -> TypedRelationBlock[bool]:
    current = chain[0]
    composition_count = len(chain) - 1
    for stage, right in enumerate(chain[1:], start=1):
        current = current.matmul(
            right,
            BooleanSemiring(),
            relation=_stage_relation(stage, composition_count),
            max_operations=max_operations,
        )
    return current


def _preflight_csr_chain(
    chain: Sequence[TypedRelationBlock[bool]],
    *,
    max_total_operations: int,
) -> tuple[TypedRelationBlock[bool] | None, int]:
    """Admit a CSR chain only when the sum of exact stage work fits the budget."""

    _validate_chain(chain)
    if type(max_total_operations) is not int or max_total_operations < 0:
        raise ValueError("max_total_operations must be a non-negative integer")

    current = chain[0]
    composition_count = len(chain) - 1
    total = 0
    for stage, right in enumerate(chain[1:], start=1):
        operations = exact_reference_operation_count(current, right)
        if total + operations > max_total_operations:
            return None, total + operations
        current = current.matmul(
            right,
            BooleanSemiring(),
            relation=_stage_relation(stage, composition_count),
            max_operations=max_total_operations - total,
        )
        total += operations
    return current, total


def run_case(case: ProbeCase, *, relation_count: int = 3) -> dict[str, Any]:
    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    relation_count = _validate_relation_count(relation_count)

    started = time.perf_counter_ns()
    chain, fixture = build_boolean_chain(case, relation_count=relation_count)
    fixture_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    oracle, reference_operations = _preflight_csr_chain(
        chain,
        max_total_operations=case.cpu_max_operations,
    )
    oracle_samples: tuple[float, ...] = ()
    oracle_median: float | None = None
    if oracle is not None:
        measured_oracle, oracle_samples = _measure_repeated(
            lambda: _csr_chain_once(
                chain,
                max_operations=case.cpu_max_operations,
            ),
            repeats=case.repeats,
            warmup=case.warmup,
        )
        if measured_oracle.digest != oracle.digest:
            raise AssertionError("repeated CSR chain changed its canonical digest")
        oracle_median = float(statistics.median(oracle_samples))

    materialized, materialized_samples = _measure_repeated(
        lambda: _canonicalized_bitset_chain_once(chain),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    materialized_median = float(statistics.median(materialized_samples))

    resident = execute_resident_chain(
        chain,
        repeats=case.repeats,
        warmup=case.warmup,
    )
    resident_kernel_median = float(statistics.median(resident.kernel_ms))
    resident_one_shot_ms = (
        resident.pack_ms
        + resident.validate_ms
        + resident_kernel_median
        + resident.canonicalize_ms
    )

    materialized_equal = same_support(materialized, resident.block)
    if not materialized_equal or materialized.digest != resident.block.digest:
        raise AssertionError(
            "resident packed chain differs from the materialized bitset chain"
        )
    oracle_equal = None if oracle is None else same_support(oracle, resident.block)
    if oracle_equal is False or (oracle is not None and oracle.digest != resident.block.digest):
        raise AssertionError("resident packed chain differs from the stdlib CSR oracle")

    return {
        "status": "verified" if oracle_equal is True else "performance-only",
        "claim": "none",
        "case": {
            "size": case.size,
            "repeats": case.repeats,
            "warmup": case.warmup,
            **fixture,
        },
        "construction": {
            "typed_chain_inputs_ms": fixture_ms,
            "reference_operation_budget": case.cpu_max_operations,
            "reference_operations_or_first_blocked_total": reference_operations,
        },
        "cpu_reference_chain": {
            "status": "verified" if oracle is not None else "skipped-total-operation-bound",
            "elapsed_ms_median": oracle_median,
            "elapsed_ms_min": None if not oracle_samples else min(oracle_samples),
            "elapsed_ms_max": None if not oracle_samples else max(oracle_samples),
            "samples": len(oracle_samples),
            "digest": None if oracle is None else oracle.digest,
        },
        "cpu_bitset_materialized_chain": {
            "elapsed_ms_median": materialized_median,
            "elapsed_ms_min": min(materialized_samples),
            "elapsed_ms_max": max(materialized_samples),
            "samples": len(materialized_samples),
            "digest": materialized.digest,
        },
        "cpu_bitset_resident_chain": {
            "pack_all_inputs_ms": resident.pack_ms,
            "validate_all_inputs_ms": resident.validate_ms,
            "kernel_ms_median": resident_kernel_median,
            "kernel_ms_min": min(resident.kernel_ms),
            "kernel_ms_max": max(resident.kernel_ms),
            "samples": len(resident.kernel_ms),
            "final_canonicalize_ms": resident.canonicalize_ms,
            "one_shot_end_to_end_ms": resident_one_shot_ms,
            "output_entries": resident.block.entry_count,
            "digest": resident.block.digest,
        },
        "correctness": {
            "materialized_bitset_support_equal": materialized_equal,
            "materialized_bitset_digest_equal": materialized.digest == resident.block.digest,
            "cpu_oracle_executed": oracle is not None,
            "cpu_oracle_support_equal": oracle_equal,
            "cpu_oracle_digest_equal": (
                None if oracle is None else oracle.digest == resident.block.digest
            ),
        },
        "diagnostic_ratios": {
            "materialized_bitset_chain_over_resident_kernel": ratio(
                materialized_median, resident_kernel_median
            ),
            "materialized_bitset_chain_over_resident_one_shot": ratio(
                materialized_median, resident_one_shot_ms
            ),
            "csr_chain_over_resident_one_shot": ratio(
                oracle_median, resident_one_shot_ms
            ),
            "csr_chain_over_materialized_bitset_chain": ratio(
                oracle_median, materialized_median
            ),
        },
    }


def run_probe(
    cases: Sequence[ProbeCase],
    *,
    relation_count: int = 3,
) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")
    relation_count = _validate_relation_count(relation_count)
    results = tuple(run_case(case, relation_count=relation_count) for case in cases)
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "Boolean relation support only",
        "measurement_contract": (
            "All CPU arms use the same warmup/repeat policy in one process. The "
            "resident bitset arm packs canonical inputs once, keeps intermediate "
            "support as regenerable integer masks, and materializes only the final "
            "TypedRelationBlock."
        ),
        "relation_count": relation_count,
        "cases": list(results),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure whether retaining packed Boolean intermediates avoids enough "
            "canonical reconstruction cost to justify a resident physical view."
        )
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--chain-relations", type=int, default=3)
    parser.add_argument("--cpu-max-operations", type=int, default=5_000_000)
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
    report = run_probe(cases, relation_count=args.chain_relations)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if args.output is not None:
        write_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
