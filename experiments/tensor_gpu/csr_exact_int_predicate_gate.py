"""One-shot semantic gate for fusing exact-int admission into the CSR common path.

This experiment mirrors only the matched-count column-validation loop from the
current canonical ``TypedRelationBlock`` constructor.  It is not a second
validator and must be removed after the bounded decision evidence is captured.
"""
from __future__ import annotations

from itertools import product
from typing import Any, Sequence

SCHEMA = "daedalus-tensor-csr-exact-int-predicate-gate/1"
SOURCE_BLOB_SHA = "5911f42485fc1683c02686cdb7af908beab23f07"
DOMAIN: tuple[Any, ...] = (-1, 0, 1, 2, 3, "bad", True)


def _current_classification(
    offsets: Sequence[int],
    columns: Sequence[Any],
    *,
    row_count: int,
    column_count: int,
) -> str:
    out_of_range = False
    not_strict = False
    for row in range(row_count):
        previous = -1
        for position in range(offsets[row], offsets[row + 1]):
            item = columns[position]
            if type(item) is not int:
                return "type"
            if previous < item < column_count:
                previous = item
                continue
            if item < 0 or item >= column_count:
                out_of_range = True
            else:
                not_strict = True
            previous = item
    if out_of_range:
        return "range"
    if not_strict:
        return "strict"
    return "ok"


def _candidate_classification(
    offsets: Sequence[int],
    columns: Sequence[Any],
    *,
    row_count: int,
    column_count: int,
) -> str:
    out_of_range = False
    not_strict = False
    for row in range(row_count):
        previous = -1
        for position in range(offsets[row], offsets[row + 1]):
            item = columns[position]
            if type(item) is int and previous < item < column_count:
                previous = item
                continue
            if type(item) is not int:
                return "type"
            if item < 0 or item >= column_count:
                out_of_range = True
            else:
                not_strict = True
            previous = item
    if out_of_range:
        return "range"
    if not_strict:
        return "strict"
    return "ok"


def run_equivalence_gate(*, max_entries: int = 5, column_count: int = 3) -> dict[str, Any]:
    if type(max_entries) is not int or not 0 <= max_entries <= 5:
        raise ValueError("max_entries must be an integer from 0 to 5")
    if type(column_count) is not int or not 1 <= column_count <= 8:
        raise ValueError("column_count must be an integer from 1 to 8")

    cases = 0
    mismatches: list[dict[str, Any]] = []
    for entry_count in range(max_entries + 1):
        for split in range(entry_count + 1):
            offsets = (0, split, entry_count)
            for columns in product(DOMAIN, repeat=entry_count):
                cases += 1
                current = _current_classification(
                    offsets,
                    columns,
                    row_count=2,
                    column_count=column_count,
                )
                candidate = _candidate_classification(
                    offsets,
                    columns,
                    row_count=2,
                    column_count=column_count,
                )
                if current != candidate:
                    mismatches.append(
                        {
                            "offsets": offsets,
                            "columns": columns,
                            "current": current,
                            "candidate": candidate,
                        }
                    )
                    if len(mismatches) >= 16:
                        break
            if mismatches:
                break
        if mismatches:
            break

    return {
        "schema": SCHEMA,
        "status": "verified" if not mismatches else "mismatch",
        "claim": "semantic-equivalence-only",
        "source_blob_sha": SOURCE_BLOB_SHA,
        "domain": [repr(value) for value in DOMAIN],
        "max_entries": max_entries,
        "column_count": column_count,
        "cases": cases,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
    }
