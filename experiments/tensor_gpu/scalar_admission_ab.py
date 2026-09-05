"""One-shot scalar-admission candidate for canonical TypedRelationBlock values.

This contained experiment asks one narrow question before production mutation:
can the current per-entry ``_stored`` contract be represented by one
sequence-level admission owner without changing accepted values, normalization,
or first-error semantics? It is not a trusted constructor, backend, cache, or
second persisted scalar contract.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any, Callable, Sequence

from daedalus.twin import relation_blocks as _relation_blocks
from daedalus.twin.relation_blocks import MAX_NATURAL_BITS
from daedalus.twin.semiring import EvidenceValue

MAX_REPEATS = 200
MAX_VALUES = 100_000


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


def outcome(
    operation: Callable[[], tuple[Any, ...]],
) -> tuple[str, Any]:
    try:
        return ("value", operation())
    except ValueError as exc:
        return ("error", str(exc))


def semantic_parity(
    raw_values: Sequence[Any],
    semiring_name: str,
) -> bool:
    return outcome(lambda: _current_stored_values(raw_values, semiring_name)) == outcome(
        lambda: _candidate_stored_values(raw_values, semiring_name)
    )


def _median_ms(operation: Callable[[], tuple[Any, ...]], repeats: int) -> float:
    if type(repeats) is not int or not 1 <= repeats <= MAX_REPEATS:
        raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
    samples: list[float] = []
    for _ in range(repeats):
        started = time.perf_counter_ns()
        operation()
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    return float(statistics.median(samples))


def run_boolean_probe(*, entries: int = 10_000, repeats: int = 25) -> dict[str, Any]:
    if type(entries) is not int or not 1 <= entries <= MAX_VALUES:
        raise ValueError(f"entries must be an integer from 1 to {MAX_VALUES}")
    values = (True,) * entries
    if not semantic_parity(values, "boolean"):
        raise AssertionError("candidate scalar admission changed Boolean semantics")

    current_ms = _median_ms(
        lambda: _current_stored_values(values, "boolean"),
        repeats,
    )
    candidate_ms = _median_ms(
        lambda: _candidate_stored_values(values, "boolean"),
        repeats,
    )
    return {
        "schema": "daedalus-tensor-scalar-admission-ab/1",
        "status": "verified",
        "claim": "none",
        "entries": entries,
        "repeats": repeats,
        "current_ms_median": current_ms,
        "candidate_ms_median": candidate_ms,
        "candidate_to_current_ratio": (
            None if current_ms <= 0.0 else candidate_ms / current_ms
        ),
        "interpretation": (
            "Same-process diagnostic only. Independent timing loops are not a "
            "constructor-wide speedup claim."
        ),
    }
