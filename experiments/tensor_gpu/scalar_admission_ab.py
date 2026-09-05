"""One-shot paired scalar-admission timing gate for canonical relation blocks.

GPU-22 established semantic parity for a sequence-level persisted-scalar owner
and then removed the duplicate experiment surface. This bounded follow-up asks
the remaining question before production mutation: does dispatching the
persisted semiring once per value sequence materially reduce Boolean admission
cost on the exact packed-CPU fixture family?

The control is the current per-entry ``relation_blocks._stored`` path. The
candidate is the already-proved GPU-22 sequence-level shape. Timings are paired
inside one process with alternating AB/BA order. This module is diagnostic-only:
it is not a backend, trusted constructor, persisted scalar authority, or broad
constructor speedup claim.
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import statistics
import time
from pathlib import Path
from typing import Any, Callable, Sequence

from daedalus.twin import relation_blocks as _relation_blocks
from daedalus.twin.relation_blocks import MAX_NATURAL_BITS
from daedalus.twin.semiring import EvidenceValue

if __package__:
    from .boolean_probe_contract import MAX_CASES, ProbeCase, build_boolean_case
    from .cpu_bitset_baseline import _csr_support_from_masks, compose_packed_rows, pack_rows
else:
    from boolean_probe_contract import MAX_CASES, ProbeCase, build_boolean_case
    from cpu_bitset_baseline import _csr_support_from_masks, compose_packed_rows, pack_rows

SCHEMA = "daedalus-tensor-scalar-admission-ab/2"
MAX_REPEATS = 25
MAX_WARMUP = 10
MAX_VALUES = 100_000
GPU22_EXPERIMENT_HEAD = "a5db37a871056855482d1e45afe0d86404a4f1d5"
GPU22_EXPERIMENT_BLOB = "dd90eae5f33c143744472236a5080ea3c9ab5e4f"


def _candidate_stored_values(
    raw_values: Sequence[Any],
    semiring_name: str,
) -> tuple[Any, ...]:
    if len(raw_values) > MAX_VALUES:
        raise ValueError(f"values exceed bounded experiment limit {MAX_VALUES}")

    output: list[Any] | None = None if type(raw_values) is tuple else []
    for index, item in enumerate(raw_values):
        if semiring_name == "boolean":
            if type(item) is not bool:
                raise ValueError("boolean relation blocks must contain bool values")
            if not item:
                raise ValueError("relation blocks must not store semiring zero values")
            stored = item
        elif semiring_name == "natural":
            if type(item) is not int or item < 0:
                raise ValueError(
                    "natural relation blocks must contain non-negative integers"
                )
            if item.bit_length() > MAX_NATURAL_BITS:
                raise ValueError(
                    "natural relation-block values exceed bounded bit length "
                    f"{MAX_NATURAL_BITS}"
                )
            if item == 0:
                raise ValueError("relation blocks must not store semiring zero values")
            stored = item
        elif semiring_name == "tropical":
            if type(item) not in (int, float):
                raise ValueError("tropical relation blocks must contain numeric costs")
            try:
                stored = float(item)
            except OverflowError as exc:
                raise ValueError("tropical relation-block costs must be finite") from exc
            if not math.isfinite(stored) or stored < 0:
                raise ValueError(
                    "tropical relation-block costs must be finite and non-negative"
                )
            stored = 0.0 if stored == 0.0 else stored
        elif semiring_name == "evidence-dag":
            if not isinstance(item, EvidenceValue):
                raise ValueError(
                    "evidence-dag relation blocks require EvidenceValue values"
                )
            if not item.alternatives:
                raise ValueError("relation blocks must not store semiring zero values")
            stored = item
        else:
            raise ValueError(
                f"unsupported persisted semiring {semiring_name!r}; "
                "add an explicit scalar contract first"
            )

        if output is None and stored is not item:
            output = [raw_values[position] for position in range(index)]
        if output is not None:
            output.append(stored)

    return raw_values if output is None else tuple(output)  # type: ignore[return-value]


def _current_stored_values(
    raw_values: Sequence[Any],
    semiring_name: str,
) -> tuple[Any, ...]:
    output: list[Any] | None = None if type(raw_values) is tuple else []
    for index, item in enumerate(raw_values):
        stored = _relation_blocks._stored(item, semiring_name)
        if output is None and stored is not item:
            output = [raw_values[position] for position in range(index)]
        if output is not None:
            output.append(stored)
    return raw_values if output is None else tuple(output)  # type: ignore[return-value]


def outcome(operation: Callable[[], tuple[Any, ...]]) -> tuple[str, Any]:
    try:
        return ("value", operation())
    except ValueError as exc:
        return ("error", str(exc))


def semantic_parity(raw_values: Sequence[Any], semiring_name: str) -> bool:
    return outcome(lambda: _current_stored_values(raw_values, semiring_name)) == outcome(
        lambda: _candidate_stored_values(raw_values, semiring_name)
    )


def _validate_timing_bounds(repeats: int, warmup: int) -> tuple[int, int]:
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    if type(warmup) is not int or not 0 <= warmup <= MAX_WARMUP:
        raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")
    return repeats, warmup


def _elapsed_ms(operation: Callable[[], tuple[Any, ...]]) -> tuple[tuple[Any, ...], float]:
    started = time.perf_counter_ns()
    result = operation()
    return result, (time.perf_counter_ns() - started) / 1_000_000.0


def _summary(samples: Sequence[float]) -> dict[str, float | int]:
    if not samples:
        raise ValueError("timing samples must not be empty")
    return {
        "median": float(statistics.median(samples)),
        "min": float(min(samples)),
        "max": float(max(samples)),
        "samples": len(samples),
    }


def _measure_paired(
    control: Callable[[], tuple[Any, ...]],
    candidate: Callable[[], tuple[Any, ...]],
    *,
    repeats: int,
    warmup: int,
) -> tuple[dict[str, float | int], dict[str, float | int]]:
    repeats, warmup = _validate_timing_bounds(repeats, warmup)
    for index in range(warmup):
        first, second = (control, candidate) if index % 2 == 0 else (candidate, control)
        if first() != second():
            raise AssertionError("paired warmup changed scalar-admission output")

    control_samples: list[float] = []
    candidate_samples: list[float] = []
    for index in range(repeats):
        ordered = (
            (("control", control), ("candidate", candidate))
            if index % 2 == 0
            else (("candidate", candidate), ("control", control))
        )
        outputs: dict[str, tuple[Any, ...]] = {}
        for name, operation in ordered:
            output, elapsed = _elapsed_ms(operation)
            outputs[name] = output
            if name == "control":
                control_samples.append(elapsed)
            else:
                candidate_samples.append(elapsed)
        if outputs["control"] != outputs["candidate"]:
            raise AssertionError("paired timing changed scalar-admission output")
    return _summary(control_samples), _summary(candidate_samples)


def run_case(case: ProbeCase) -> dict[str, Any]:
    if not isinstance(case, ProbeCase):
        raise ValueError("case must be ProbeCase")
    if case.repeats > MAX_REPEATS or case.warmup > MAX_WARMUP:
        raise ValueError("case timing exceeds scalar-admission experiment bounds")

    left, right, fixture = build_boolean_case(case)
    masks = compose_packed_rows(pack_rows(left), pack_rows(right))
    _, columns = _csr_support_from_masks(left, right, masks)
    entries = len(columns)
    if entries > MAX_VALUES:
        raise ValueError(f"values exceed bounded experiment limit {MAX_VALUES}")
    values = (True,) * entries
    if not semantic_parity(values, "boolean"):
        raise AssertionError("candidate scalar admission changed Boolean semantics")

    control, candidate = _measure_paired(
        lambda: _current_stored_values(values, "boolean"),
        lambda: _candidate_stored_values(values, "boolean"),
        repeats=case.repeats,
        warmup=case.warmup,
    )
    control_median = float(control["median"])
    candidate_median = float(candidate["median"])
    return {
        "status": "verified",
        "claim": "none",
        "case": {
            "size": case.size,
            "density": case.density,
            "repeats": case.repeats,
            "warmup": case.warmup,
            **fixture,
        },
        "entries": entries,
        "control": {
            "contract": "per-entry daedalus.twin.relation_blocks._stored",
            "timing_ms": control,
        },
        "candidate": {
            "contract": "single sequence-level semiring dispatch with identical scalar checks",
            "timing_ms": candidate,
        },
        "candidate_to_control_ratio": (
            None if control_median <= 0.0 else candidate_median / control_median
        ),
        "interpretation": (
            "Same-process paired AB/BA microstage diagnostic only. The ratio measures "
            "persisted-scalar admission for this Boolean fixture; it is not a "
            "constructor-wide, CPU-wide, backend, or promotion claim."
        ),
    }


def run_probe(cases: Sequence[ProbeCase]) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")
    return {
        "schema": SCHEMA,
        "status": "completed",
        "authority": "diagnostic-only",
        "claim": "none",
        "gpu22_semantic_evidence": {
            "experiment_head": GPU22_EXPERIMENT_HEAD,
            "candidate_blob": GPU22_EXPERIMENT_BLOB,
        },
        "measurement_contract": (
            "Recreate the GPU-22 candidate against the current per-entry _stored control, "
            "derive entry counts from the frozen packed-CPU fixture family, and measure "
            "paired alternating AB/BA samples in one CPython process. No product code is "
            "bypassed or promoted by this diagnostic."
        ),
        "runtime": {
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        },
        "cases": [run_case(case) for case in cases],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the one-shot paired scalar-admission decision diagnostic."
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(64, 128, 256))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.01, 0.05))
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument("--warmup", type=int, default=3)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _validate_timing_bounds(args.repeats, args.warmup)
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
    report = run_probe(cases)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
