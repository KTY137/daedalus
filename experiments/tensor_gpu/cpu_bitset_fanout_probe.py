"""Frozen packed-prefix fanout probe for Boolean Fourfold relations.

This contained experiment asks one narrow follow-up to the packed-residency
probe: when several exact queries share the same revision-bound Boolean prefix,
is it cheaper to retain that regenerable packed prefix and fan out from it than
to recompute the prefix for every query?

It is not a product cache, backend, scheduler, registry, or authority. Forest /
Fourfold remain authoritative and ``TypedRelationBlock.matmul`` remains the
semantic oracle. The retained value is process-local diagnostic state, bounded
by an explicit memory budget and invalidated by exact subject/axis checks.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Sequence

from daedalus.twin.relation_blocks import RelationSignature, TypedRelationBlock

if __package__:
    from .boolean_probe_contract import MAX_CASES, ProbeCase, same_support, write_report
    from .cpu_bitset_baseline import (
        _block_from_masks,
        _compose_packed_rows_unchecked,
        _measure_repeated,
        _validate_packed_rows,
        _validate_sampling,
        pack_rows,
    )
    from .cpu_bitset_residency_probe import (
        _compose_packed_chain_unchecked,
        _preflight_csr_chain,
        _validate_chain,
        build_boolean_chain,
    )
else:  # direct ``python experiments/tensor_gpu/cpu_bitset_fanout_probe.py``
    from boolean_probe_contract import MAX_CASES, ProbeCase, same_support, write_report
    from cpu_bitset_baseline import (
        _block_from_masks,
        _compose_packed_rows_unchecked,
        _measure_repeated,
        _validate_packed_rows,
        _validate_sampling,
        pack_rows,
    )
    from cpu_bitset_residency_probe import (
        _compose_packed_chain_unchecked,
        _preflight_csr_chain,
        _validate_chain,
        build_boolean_chain,
    )

SCHEMA = "daedalus-tensor-cpu-bitset-fanout/1"
MAX_FANOUT_QUERIES = 16
MAX_RESIDENT_MIB = 256
MIN_FANOUT_RELATIONS = 3
FANOUT_RELATION_PREFIX = "cpu_bitset_resident_fanout"


def _validate_query_count(value: int) -> int:
    if type(value) is not int or not 2 <= value <= MAX_FANOUT_QUERIES:
        raise ValueError(
            f"query_count must be an integer from 2 to {MAX_FANOUT_QUERIES}"
        )
    return value


def _validate_resident_mib(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_RESIDENT_MIB:
        raise ValueError(
            f"max_resident_mib must be an integer from 1 to {MAX_RESIDENT_MIB}"
        )
    return value


def build_boolean_fanout(
    case: ProbeCase,
    *,
    relation_count: int,
    query_count: int,
) -> tuple[
    tuple[TypedRelationBlock[bool], ...],
    tuple[TypedRelationBlock[bool], ...],
    dict[str, Any],
]:
    """Build one shared exact prefix plus bounded typed query tails.

    ``build_boolean_chain`` remains the only synthetic graph generator. Query
    tails reuse its final support exactly and vary only the relation identity,
    so the experiment isolates reuse of the shared prefix rather than changing
    graph difficulty between queries.
    """

    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    if type(relation_count) is not int or relation_count < MIN_FANOUT_RELATIONS:
        raise ValueError(
            f"relation_count must be at least {MIN_FANOUT_RELATIONS} for fanout"
        )
    query_count = _validate_query_count(query_count)
    chain, fixture = build_boolean_chain(case, relation_count=relation_count)
    prefix = chain[:-1]
    template = chain[-1]
    tails = tuple(
        TypedRelationBlock(
            subject=template.subject,
            signature=RelationSignature(
                template.signature.source_plane,
                f"cpu_bitset_fanout_tail_{index:02d}",
                template.signature.target_plane,
            ),
            row_axis=template.row_axis,
            column_axis=template.column_axis,
            semiring_name=template.semiring_name,
            row_offsets=template.row_offsets,
            column_indices=template.column_indices,
            values=template.values,
        )
        for index in range(query_count)
    )
    return prefix, tails, {
        **fixture,
        "relation_count": relation_count,
        "prefix_relation_count": len(prefix),
        "query_count": query_count,
        "shared_subject_digest": prefix[0].subject.digest,
        "shared_prefix_input_entries": sum(block.entry_count for block in prefix),
        "query_tail_entries": template.entry_count,
    }


def _validate_fanout(
    prefix: Sequence[TypedRelationBlock[bool]],
    tails: Sequence[TypedRelationBlock[bool]],
) -> None:
    _validate_chain(prefix)
    _validate_query_count(len(tails))
    if any(not isinstance(tail, TypedRelationBlock) for tail in tails):
        raise ValueError("fanout tails must contain TypedRelationBlock values")
    last = prefix[-1]
    for tail in tails:
        if tail.semiring_name != "boolean":
            raise ValueError("fanout tails must use the Boolean semiring")
        if tail.subject != last.subject:
            raise ValueError("fanout tail invalidated by a different Fourfold subject")
        if tail.row_axis != last.column_axis:
            raise ValueError("fanout tail invalidated by a different typed prefix axis")


def _packed_storage_bytes(rows: Sequence[int]) -> int:
    """Observed CPython storage for the retained tuple and integer masks."""

    return sys.getsizeof(rows) + sum(sys.getsizeof(value) for value in rows)


def _pack_fanout(
    prefix: Sequence[TypedRelationBlock[bool]],
    tails: Sequence[TypedRelationBlock[bool]],
) -> tuple[tuple[tuple[int, ...], ...], tuple[tuple[int, ...], ...], float, float]:
    _validate_fanout(prefix, tails)
    started = time.perf_counter_ns()
    prefix_packed = tuple(pack_rows(block) for block in prefix)
    tails_packed = tuple(pack_rows(tail) for tail in tails)
    pack_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    for left_rows, right_rows in zip(prefix_packed, prefix_packed[1:]):
        _validate_packed_rows(left_rows, right_rows)
    for tail_rows in tails_packed:
        _validate_packed_rows(prefix_packed[-1], tail_rows)
    validate_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    return prefix_packed, tails_packed, pack_ms, validate_ms


def _materialize_query_batch(
    prefix: Sequence[TypedRelationBlock[bool]],
    tails: Sequence[TypedRelationBlock[bool]],
    prefix_rows: Sequence[int],
    tails_packed: Sequence[Sequence[int]],
) -> tuple[TypedRelationBlock[bool], ...]:
    outputs: list[TypedRelationBlock[bool]] = []
    for index, (tail, tail_rows) in enumerate(zip(tails, tails_packed)):
        masks = _compose_packed_rows_unchecked(prefix_rows, tail_rows)
        outputs.append(
            _block_from_masks(
                prefix[0],
                tail,
                masks,
                relation=f"{FANOUT_RELATION_PREFIX}_{index:02d}",
            )
        )
    return tuple(outputs)


def _recompute_query_batch(
    prefix: Sequence[TypedRelationBlock[bool]],
    tails: Sequence[TypedRelationBlock[bool]],
    prefix_packed: Sequence[Sequence[int]],
    tails_packed: Sequence[Sequence[int]],
) -> tuple[TypedRelationBlock[bool], ...]:
    outputs: list[TypedRelationBlock[bool]] = []
    for index, (tail, tail_rows) in enumerate(zip(tails, tails_packed)):
        prefix_rows = _compose_packed_chain_unchecked(prefix_packed)
        masks = _compose_packed_rows_unchecked(prefix_rows, tail_rows)
        outputs.append(
            _block_from_masks(
                prefix[0],
                tail,
                masks,
                relation=f"{FANOUT_RELATION_PREFIX}_{index:02d}",
            )
        )
    return tuple(outputs)


def _retag_relation(
    block: TypedRelationBlock[bool],
    *,
    relation: str,
) -> TypedRelationBlock[bool]:
    return TypedRelationBlock(
        subject=block.subject,
        signature=RelationSignature(
            block.signature.source_plane,
            relation,
            block.signature.target_plane,
        ),
        row_axis=block.row_axis,
        column_axis=block.column_axis,
        semiring_name=block.semiring_name,
        row_offsets=block.row_offsets,
        column_indices=block.column_indices,
        values=block.values,
    )


def _same_output_batch(
    left: Sequence[TypedRelationBlock[bool]],
    right: Sequence[TypedRelationBlock[bool]],
) -> bool:
    return len(left) == len(right) and all(
        same_support(left_block, right_block) and left_block.digest == right_block.digest
        for left_block, right_block in zip(left, right)
    )


def run_case(
    case: ProbeCase,
    *,
    relation_count: int = 3,
    query_count: int = 4,
    max_resident_mib: int = 64,
) -> dict[str, Any]:
    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    query_count = _validate_query_count(query_count)
    max_resident_mib = _validate_resident_mib(max_resident_mib)
    _validate_sampling(repeats=case.repeats, warmup=case.warmup)

    started = time.perf_counter_ns()
    prefix, tails, fixture = build_boolean_fanout(
        case,
        relation_count=relation_count,
        query_count=query_count,
    )
    fixture_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    prefix_packed, tails_packed, pack_ms, validate_ms = _pack_fanout(prefix, tails)

    prefix_rows, prefix_samples = _measure_repeated(
        lambda: _compose_packed_chain_unchecked(prefix_packed),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    prefix_median = float(statistics.median(prefix_samples))
    retained_prefix_bytes = _packed_storage_bytes(prefix_rows)
    resident_budget_bytes = max_resident_mib * 1024 * 1024
    if retained_prefix_bytes > resident_budget_bytes:
        return {
            "status": "blocked-resident-memory-budget",
            "claim": "none",
            "case": fixture,
            "construction": {
                "typed_fanout_inputs_ms": fixture_ms,
                "pack_all_inputs_ms": pack_ms,
                "validate_all_inputs_ms": validate_ms,
            },
            "resident_prefix": {
                "storage_bytes": retained_prefix_bytes,
                "budget_bytes": resident_budget_bytes,
                "admitted": False,
            },
        }

    started = time.perf_counter_ns()
    for tail_rows in tails_packed:
        _validate_packed_rows(prefix_rows, tail_rows)
    retained_validate_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    resident_outputs, resident_samples = _measure_repeated(
        lambda: _materialize_query_batch(prefix, tails, prefix_rows, tails_packed),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    recompute_outputs, recompute_samples = _measure_repeated(
        lambda: _recompute_query_batch(prefix, tails, prefix_packed, tails_packed),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    if not _same_output_batch(resident_outputs, recompute_outputs):
        raise AssertionError("resident-prefix fanout differs from recomputed packed control")

    oracle_outputs: list[TypedRelationBlock[bool]] = []
    reference_operations: list[int] = []
    oracle_executed = True
    for tail in tails:
        oracle, operations = _preflight_csr_chain(
            tuple(prefix) + (tail,),
            max_total_operations=case.cpu_max_operations,
        )
        reference_operations.append(operations)
        if oracle is None:
            oracle_executed = False
            oracle_outputs = []
            break
        oracle_outputs.append(
            _retag_relation(
                oracle,
                relation=f"{FANOUT_RELATION_PREFIX}_{len(oracle_outputs):02d}",
            )
        )

    oracle_equal: bool | None = None
    if oracle_executed:
        oracle_equal = _same_output_batch(tuple(oracle_outputs), resident_outputs)
        if not oracle_equal:
            raise AssertionError("resident-prefix fanout differs from stdlib CSR oracle")

    resident_median = float(statistics.median(resident_samples))
    recompute_median = float(statistics.median(recompute_samples))
    resident_one_shot = (
        pack_ms
        + validate_ms
        + prefix_median
        + retained_validate_ms
        + resident_median
    )
    recompute_one_shot = pack_ms + validate_ms + recompute_median
    return {
        "status": "verified" if oracle_equal is True else "performance-only",
        "claim": "none",
        "case": fixture,
        "construction": {
            "typed_fanout_inputs_ms": fixture_ms,
            "pack_all_inputs_ms": pack_ms,
            "validate_all_inputs_ms": validate_ms,
            "reference_operation_budget_per_query": case.cpu_max_operations,
            "reference_operations_or_first_blocked_total": (
                None if not reference_operations else reference_operations[0]
            ),
        },
        "resident_prefix": {
            "build_ms_median": prefix_median,
            "build_ms_min": min(prefix_samples),
            "build_ms_max": max(prefix_samples),
            "samples": len(prefix_samples),
            "postbuild_validate_ms": retained_validate_ms,
            "storage_bytes": retained_prefix_bytes,
            "budget_bytes": resident_budget_bytes,
            "admitted": True,
        },
        "resident_query_batch": {
            "elapsed_ms_median": resident_median,
            "elapsed_ms_min": min(resident_samples),
            "elapsed_ms_max": max(resident_samples),
            "samples": len(resident_samples),
            "one_shot_end_to_end_ms": resident_one_shot,
            "digests": [block.digest for block in resident_outputs],
        },
        "recomputed_query_batch": {
            "elapsed_ms_median": recompute_median,
            "elapsed_ms_min": min(recompute_samples),
            "elapsed_ms_max": max(recompute_samples),
            "samples": len(recompute_samples),
            "one_shot_end_to_end_ms": recompute_one_shot,
            "digests": [block.digest for block in recompute_outputs],
        },
        "correctness": {
            "recomputed_support_and_digest_equal": True,
            "cpu_oracle_executed_for_all_queries": oracle_executed,
            "cpu_oracle_support_and_digest_equal": oracle_equal,
        },
        "diagnostic_ratios": {
            "recompute_batch_over_resident_query_batch": (
                recompute_median / resident_median if resident_median > 0.0 else None
            ),
            "recompute_one_shot_over_shared_prefix_one_shot": (
                recompute_one_shot / resident_one_shot if resident_one_shot > 0.0 else None
            ),
        },
    }


def run_probe(
    cases: Sequence[ProbeCase],
    *,
    relation_count: int = 3,
    query_count: int = 4,
    max_resident_mib: int = 64,
) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")
    query_count = _validate_query_count(query_count)
    max_resident_mib = _validate_resident_mib(max_resident_mib)
    results = tuple(
        run_case(
            case,
            relation_count=relation_count,
            query_count=query_count,
            max_resident_mib=max_resident_mib,
        )
        for case in cases
    )
    blocked = any(result["status"].startswith("blocked-") for result in results)
    return {
        "schema": SCHEMA,
        "status": "completed-with-blocked-cases" if blocked else "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "Boolean relation support only",
        "measurement_contract": (
            "All arms share exact typed inputs and one process. Packed inputs are "
            "prepared once. The control recomputes the shared packed prefix for every "
            "query; the resident arm builds it once, enforces an explicit storage "
            "budget, and materializes only final typed query outputs."
        ),
        "relation_count": relation_count,
        "query_count": query_count,
        "max_resident_mib": max_resident_mib,
        "cases": list(results),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Measure bounded reuse of one revision-frozen packed Boolean prefix "
            "across several typed query tails."
        )
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--chain-relations", type=int, default=3)
    parser.add_argument("--queries", type=int, default=4)
    parser.add_argument("--max-resident-mib", type=int, default=64)
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
    report = run_probe(
        cases,
        relation_count=args.chain_relations,
        query_count=args.queries,
        max_resident_mib=args.max_resident_mib,
    )
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if args.output is not None:
        write_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
