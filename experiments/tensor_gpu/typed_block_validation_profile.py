"""Profile canonical ``TypedRelationBlock`` materialization without bypassing it.

GPU-10 showed that packed Boolean support materializes quickly enough that the
remaining cost is dominated by canonical ``TypedRelationBlock`` construction.
GPU-11/12 identified and fused repeated structural validation scans. GPU-13
separated persisted-scalar ``_stored`` cost, while GPU-14/15 then narrowed and
reduced packed-support decoding overhead. GPU-16 removed the duplicate scalar
wall-time path and kept only constructor-native attribution. GPU-17 pruned the
retired zero-only profiler metrics. GPU-19 replaced the canonical common-case
per-entry CSR row-state walk with exact row-span validation.

GPU-20 adds one bounded same-process A/B for that GPU-19 algorithmic change.
The control is the retired pre-GPU-19 column/order loop from relation-block blob
``e48c26180597de7ff94da3b8b10cef57b15b2424``; the candidate is the current
matched-count row-span algorithm. They operate only on already decoded CSR
support, alternate AB/BA order, and must agree on valid and invalid outcomes.
This is experiment-only comparison code, not a second product validator.

The profiler still executes the real support decoder and canonical constructor
and reports only active in-path cProfile functions. Independently sampled wall
timings and the CSR microstage A/B are diagnostic only; neither mints a
constructor-wide speedup or promotion claim.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import platform
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

import daedalus.schemas as _schemas
import daedalus.twin.relation_blocks as _relation_blocks
from daedalus.twin.relation_blocks import TypedRelationBlock

if __package__:
    from .boolean_probe_contract import MAX_CASES, MAX_REPEATS, MAX_WARMUP, ProbeCase, build_boolean_case, write_report
    from .cpu_bitset_baseline import (
        _block_from_csr_support,
        _csr_support_from_masks,
        _measure_repeated,
        compose_packed_rows,
        pack_rows,
    )
else:  # direct ``python experiments/tensor_gpu/typed_block_validation_profile.py``
    from boolean_probe_contract import MAX_CASES, MAX_REPEATS, MAX_WARMUP, ProbeCase, build_boolean_case, write_report
    from cpu_bitset_baseline import (
        _block_from_csr_support,
        _csr_support_from_masks,
        _measure_repeated,
        compose_packed_rows,
        pack_rows,
    )

SCHEMA = "daedalus-tensor-typed-block-validation-profile/6"
MAX_PROFILE_REPEATS = 5
PRE_GPU19_RELATION_BLOCK_BLOB = "e48c26180597de7ff94da3b8b10cef57b15b2424"


@dataclass(frozen=True)
class _ProfileSample:
    block: TypedRelationBlock[bool]
    wall_ms: float
    metrics: dict[str, dict[str, float | int]]


def _validate_profile_repeats(value: int) -> int:
    if type(value) is not int or not 1 <= value <= MAX_PROFILE_REPEATS:
        raise ValueError(
            f"profile_repeats must be an integer from 1 to {MAX_PROFILE_REPEATS}"
        )
    return value


def _entry_metrics(entries: Sequence[Any]) -> dict[str, float | int]:
    return {
        "calls": sum(int(entry.callcount) for entry in entries),
        "self_ms": sum(float(entry.inlinetime) for entry in entries) * 1_000.0,
        "cumulative_ms": sum(float(entry.totaltime) for entry in entries) * 1_000.0,
    }


def _code_metrics(stats: Sequence[Any], codes: Sequence[Any]) -> dict[str, float | int]:
    code_ids = {id(code) for code in codes}
    return _entry_metrics(tuple(entry for entry in stats if id(entry.code) in code_ids))


def _profile_once(factory: Callable[[], TypedRelationBlock[bool]]) -> _ProfileSample:
    if not callable(factory):
        raise ValueError("factory must be callable")
    profiler = cProfile.Profile()
    started = time.perf_counter_ns()
    profiler.enable()
    try:
        block = factory()
    finally:
        profiler.disable()
    wall_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    stats = tuple(profiler.getstats())

    post_init_code = TypedRelationBlock.__post_init__.__code__
    metrics = {
        "bitset_block_factory": _code_metrics(stats, (_block_from_csr_support.__code__,)),
        "typed_block_post_init": _code_metrics(stats, (post_init_code,)),
        "stored_scalar_admission": _code_metrics(stats, (_relation_blocks._stored.__code__,)),
        "bounded_sequence_admission": _code_metrics(stats, (_relation_blocks._sequence.__code__,)),
        "semiring_resolution": _code_metrics(stats, (_relation_blocks._reference_semiring.__code__,)),
        "identifier_admission": _code_metrics(stats, (_schemas._identifier.__code__,)),
    }
    return _ProfileSample(block=block, wall_ms=wall_ms, metrics=metrics)


def _median_metrics(samples: Sequence[_ProfileSample]) -> dict[str, dict[str, float | int]]:
    if not samples:
        raise ValueError("profile samples must not be empty")
    names = tuple(samples[0].metrics)
    if any(tuple(sample.metrics) != names for sample in samples[1:]):
        raise AssertionError("profile metric surface drifted inside one case")
    output: dict[str, dict[str, float | int]] = {}
    for name in names:
        calls = {int(sample.metrics[name]["calls"]) for sample in samples}
        if len(calls) != 1:
            raise AssertionError(f"profile call count for {name} drifted inside one case")
        output[name] = {
            "calls": calls.pop(),
            "self_ms_median": float(
                statistics.median(float(sample.metrics[name]["self_ms"]) for sample in samples)
            ),
            "cumulative_ms_median": float(
                statistics.median(
                    float(sample.metrics[name]["cumulative_ms"]) for sample in samples
                )
            ),
        }
    return output


def _timing_summary(samples: Sequence[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("timing samples must not be empty")
    return {
        "median": float(statistics.median(samples)),
        "min": float(min(samples)),
        "max": float(max(samples)),
        "samples": len(samples),
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0.0 else numerator / denominator


def _pre_gpu19_column_validation(
    row_offsets: Sequence[int],
    column_indices: Sequence[Any],
    *,
    row_count: int,
    column_count: int,
    entry_count: int,
) -> None:
    """Retired pre-GPU-19 column/order loop, retained only as an A/B control."""
    row = 0
    row_stop = row_offsets[1] if row_count else 0
    previous_column: int | None = None
    columns_out_of_range = False
    columns_not_strict = False
    for position, item in enumerate(column_indices):
        if type(item) is not int:
            raise ValueError("block.column_indices must contain integers")
        if not 0 <= item < column_count:
            columns_out_of_range = True
        while row < row_count and position >= row_stop:
            row += 1
            previous_column = None
            if row < row_count:
                row_stop = row_offsets[row + 1]
        if row < row_count:
            if previous_column is not None and previous_column >= item:
                columns_not_strict = True
            previous_column = item
    if columns_out_of_range:
        raise ValueError("block.column_indices contains an out-of-range index")
    if len(column_indices) != entry_count or row_offsets[-1] != entry_count:
        raise ValueError("CSR arrays must terminate at the common entry count")
    if columns_not_strict:
        raise ValueError("column indices must be strictly increasing inside each row")


def _gpu19_column_validation(
    row_offsets: Sequence[int],
    column_indices: Sequence[Any],
    *,
    row_count: int,
    column_count: int,
    entry_count: int,
) -> None:
    """GPU-19 matched-count row-span algorithm, mirrored for bounded A/B timing."""
    columns_out_of_range = False
    columns_not_strict = False
    if len(column_indices) == entry_count and row_offsets[-1] == entry_count:
        for row in range(row_count):
            previous_column: int | None = None
            for position in range(row_offsets[row], row_offsets[row + 1]):
                item = column_indices[position]
                if type(item) is not int:
                    raise ValueError("block.column_indices must contain integers")
                if not 0 <= item < column_count:
                    columns_out_of_range = True
                if previous_column is not None and previous_column >= item:
                    columns_not_strict = True
                previous_column = item
    else:
        for item in column_indices:
            if type(item) is not int:
                raise ValueError("block.column_indices must contain integers")
            if not 0 <= item < column_count:
                columns_out_of_range = True
    if columns_out_of_range:
        raise ValueError("block.column_indices contains an out-of-range index")
    if len(column_indices) != entry_count or row_offsets[-1] != entry_count:
        raise ValueError("CSR arrays must terminate at the common entry count")
    if columns_not_strict:
        raise ValueError("column indices must be strictly increasing inside each row")


def _measure_validation_ab(
    control: Callable[[], None],
    candidate: Callable[[], None],
    *,
    repeats: int,
    warmup: int,
) -> dict[str, Any]:
    if not callable(control) or not callable(candidate):
        raise ValueError("A/B validators must be callable")
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(warmup) is not int or not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")

    for index in range(warmup):
        first, second = (control, candidate) if index % 2 == 0 else (candidate, control)
        first()
        second()

    control_samples: list[float] = []
    candidate_samples: list[float] = []

    def sample(factory: Callable[[], None], target: list[float]) -> None:
        started = time.perf_counter_ns()
        factory()
        target.append((time.perf_counter_ns() - started) / 1_000_000.0)

    for index in range(repeats):
        if index % 2 == 0:
            sample(control, control_samples)
            sample(candidate, candidate_samples)
        else:
            sample(candidate, candidate_samples)
            sample(control, control_samples)

    control_median = float(statistics.median(control_samples))
    candidate_median = float(statistics.median(candidate_samples))
    return {
        "control_ms": _timing_summary(control_samples),
        "candidate_ms": _timing_summary(candidate_samples),
        "candidate_to_control_ratio": _ratio(candidate_median, control_median),
        "ordering": "alternating AB/BA in one process",
    }


def run_case(case: ProbeCase, *, profile_repeats: int) -> dict[str, Any]:
    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    profile_repeats = _validate_profile_repeats(profile_repeats)

    left, right, fixture = build_boolean_case(case)
    result_masks = compose_packed_rows(pack_rows(left), pack_rows(right))

    support, support_decode_samples = _measure_repeated(
        lambda: _csr_support_from_masks(left, right, result_masks),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    row_offsets, column_indices = support
    row_count = len(row_offsets) - 1
    column_count = len(right.column_axis.labels)
    entry_count = len(column_indices)

    validation_args = {
        "row_count": row_count,
        "column_count": column_count,
        "entry_count": entry_count,
    }
    control = lambda: _pre_gpu19_column_validation(
        row_offsets,
        column_indices,
        **validation_args,
    )
    candidate = lambda: _gpu19_column_validation(
        row_offsets,
        column_indices,
        **validation_args,
    )
    control()
    candidate()
    validation_ab = _measure_validation_ab(
        control,
        candidate,
        repeats=case.repeats,
        warmup=case.warmup,
    )

    factory = lambda: _block_from_csr_support(
        left,
        right,
        row_offsets,
        column_indices,
        relation="cpu_bitset_composed",
    )
    canonical, unprofiled_samples = _measure_repeated(
        factory,
        repeats=case.repeats,
        warmup=case.warmup,
    )
    profiled = tuple(_profile_once(factory) for _ in range(profile_repeats))
    if any(sample.block.digest != canonical.digest for sample in profiled):
        raise AssertionError("profiling changed canonical TypedRelationBlock output")

    decoded_again = _csr_support_from_masks(left, right, result_masks)
    if decoded_again != support:
        raise AssertionError("support decoding drifted for identical packed output")
    if canonical.row_offsets != row_offsets or canonical.column_indices != column_indices:
        raise AssertionError("canonical block changed decoded Boolean support")

    metrics = _median_metrics(profiled)
    profiled_wall_median = float(statistics.median(sample.wall_ms for sample in profiled))
    constructor_median = float(statistics.median(unprofiled_samples))
    support_decode_median = float(statistics.median(support_decode_samples))
    post_init_cumulative_ms = float(
        metrics["typed_block_post_init"]["cumulative_ms_median"]
    )
    stored_cumulative_ms = float(
        metrics["stored_scalar_admission"]["cumulative_ms_median"]
    )
    return {
        "status": "verified",
        "claim": "none",
        "case": {
            "size": case.size,
            "repeats": case.repeats,
            "warmup": case.warmup,
            "profile_repeats": profile_repeats,
            **fixture,
        },
        "output_entries": canonical.entry_count,
        "canonical_digest": canonical.digest,
        "csr_column_validation_ab": {
            "authority": "microstage-diagnostic-only",
            "control": (
                "retired pre-GPU-19 per-entry row-state column/order validation from "
                f"relation-block blob {PRE_GPU19_RELATION_BLOCK_BLOB}"
            ),
            "candidate": "GPU-19 matched-count row-span column/order validation algorithm",
            "valid_outcome_parity": True,
            **validation_ab,
            "interpretation": (
                "Same-process microstage timing on already decoded canonical CSR support. "
                "The control and candidate alternate AB/BA order. This does not measure the "
                "complete TypedRelationBlock constructor and cannot mint a constructor-wide "
                "or general CPU speedup claim."
            ),
        },
        "support_decode": {
            "contract": "experiments.tensor_gpu.cpu_bitset_baseline._csr_support_from_masks",
            "row_count": row_count,
            "entry_count": len(column_indices),
            "unprofiled_ms": _timing_summary(support_decode_samples),
        },
        "unprofiled_construct_ms": _timing_summary(unprofiled_samples),
        "unprofiled_comparison": {
            "support_decode_to_constructor_ratio": _ratio(
                support_decode_median, constructor_median
            ),
            "interpretation": (
                "Ratio compares independently sampled decoder and constructor medians using "
                "one warmup/repeat policy. The timings are diagnostic and non-additive."
            ),
        },
        "profiled_construct_wall_ms": _timing_summary(
            tuple(sample.wall_ms for sample in profiled)
        ),
        "profiler_slowdown_ratio": _ratio(profiled_wall_median, constructor_median),
        "profile_metrics": metrics,
        "profile_attribution": {
            "post_init_cumulative_ms_median": post_init_cumulative_ms,
            "stored_cumulative_ms_median": stored_cumulative_ms,
            "post_init_less_stored_cumulative_ms_median": max(
                0.0, post_init_cumulative_ms - stored_cumulative_ms
            ),
            "interpretation": (
                "Single-run cProfile inclusive attribution only. _stored attribution comes "
                "from the real canonical constructor; no duplicate scalar wall-time probe is "
                "executed. The less-stored remainder contains every other __post_init__ "
                "child/self cost and is not a pure structural wall-time measurement."
            ),
        },
    }


def run_probe(
    cases: Sequence[ProbeCase],
    *,
    profile_repeats: int,
) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")
    profile_repeats = _validate_profile_repeats(profile_repeats)
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "canonical Boolean TypedRelationBlock materialization only",
        "measurement_contract": (
            "Run the unchanged packed-support decoder and canonical constructor with one "
            "warmup/repeat policy, retain only active constructor-native cProfile attribution, "
            "and add one bounded alternating same-process A/B for the retired pre-GPU-19 "
            "per-entry CSR column/order loop versus the GPU-19 matched-count row-span loop. "
            "The A/B operates only on already decoded canonical CSR and is microstage-only; "
            "it does not bypass product validation or establish a constructor-wide speedup."
        ),
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "cases": [
            run_case(case, profile_repeats=profile_repeats)
            for case in cases
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Profile the existing canonical TypedRelationBlock materialization boundary."
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--profile-repeats", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if type(args.repeats) is not int or not 1 <= args.repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(args.warmup) is not int or not 0 <= args.warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")
    profile_repeats = _validate_profile_repeats(args.profile_repeats)
    cases = tuple(
        ProbeCase(
            size=size,
            density=float(density),
            repeats=args.repeats,
            warmup=args.warmup,
            max_device_mib=64,
        )
        for size in args.sizes
        for density in args.densities
    )
    report = run_probe(cases, profile_repeats=profile_repeats)
    print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    if args.output is not None:
        write_report(args.output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())