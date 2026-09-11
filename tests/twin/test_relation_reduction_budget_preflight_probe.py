from __future__ import annotations

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import MAX_NATURAL_BITS, NaturalSemiring


def _natural_block(values: tuple[int, ...]) -> TypedRelationBlock[int]:
    semiring = NaturalSemiring()
    labels = tuple(f"row-{index}" for index in range(len(values)))
    rows = TypedAxis("rows", "code", labels)
    columns = TypedAxis("columns", "type", ("T",))
    return TypedRelationBlock.from_coordinates(
        subject=ProjectionSubject(
            repository_id="KTY137/daedalus",
            source_revision="a" * 40,
            source_fourfold_sha256="b" * 64,
        ),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=tuple(
            (label, "T", value) for label, value in zip(labels, values, strict=True)
        ),
        semiring=semiring,
    )


def _preflight_candidate(
    block: TypedRelationBlock[int],
    semiring: NaturalSemiring,
    *,
    max_operations: int,
) -> int:
    """Candidate that rejects by entry count before executing semiring adds."""

    if block.entry_count > max_operations:
        raise ValueError("reference reduction exceeds bounded operation limit")
    result = semiring.zero
    for value in block.values:
        result = semiring.add(result, value)
    return result


def test_preflight_candidate_matches_current_reduce_inside_budget() -> None:
    semiring = NaturalSemiring()
    block = _natural_block((2, 3))

    assert block.reduce(semiring, max_operations=2) == 5
    assert _preflight_candidate(block, semiring, max_operations=2) == 5


def test_preflight_candidate_changes_fail_closed_error_precedence() -> None:
    semiring = NaturalSemiring()
    maximum = (1 << MAX_NATURAL_BITS) - 1
    block = _natural_block((maximum, 1, 1))

    # The canonical interpreter reaches the second permitted semiring addition
    # before it encounters the third over-budget entry, so natural overflow is
    # the first observable refusal. A count preflight would reverse that order.
    with pytest.raises(ValueError, match="bounded natural bit length"):
        block.reduce(semiring, max_operations=2)
    with pytest.raises(ValueError, match="reference reduction exceeds bounded operation limit"):
        _preflight_candidate(block, semiring, max_operations=2)
