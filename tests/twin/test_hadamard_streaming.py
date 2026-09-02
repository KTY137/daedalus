from __future__ import annotations

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring


SUBJECT = ProjectionSubject(
    repository_id="KTY137/daedalus",
    source_revision="a" * 40,
    source_fourfold_sha256="b" * 64,
)


def _block(
    relation: str,
    row_axis: TypedAxis,
    column_axis: TypedAxis,
    coordinates: tuple[tuple[str, str, bool], ...],
) -> TypedRelationBlock[bool]:
    return TypedRelationBlock.from_coordinates(
        subject=SUBJECT,
        signature=RelationSignature(row_axis.plane, relation, column_axis.plane),
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=coordinates,
        semiring=BooleanSemiring(),
    )


def test_hadamard_streams_only_intersection_values_and_preserves_budget() -> None:
    rows = TypedAxis("rows", "code", ("s",))
    columns = TypedAxis("columns", "type", ("T", "U", "V", "W"))
    semiring = BooleanSemiring()
    left = _block(
        "left",
        rows,
        columns,
        (("s", "T", True), ("s", "W", True)),
    )
    right = _block(
        "right",
        rows,
        columns,
        (("s", "U", True), ("s", "V", True), ("s", "W", True)),
    )
    original_values = right.values

    class ExplodingValues(tuple):
        def __getitem__(self, index: object) -> object:
            if isinstance(index, int) and index < 2:
                raise AssertionError("Hadamard materialized non-intersection CSR values")
            return super().__getitem__(index)

    object.__setattr__(right, "values", ExplodingValues(original_values))

    result = left.hadamard(right, semiring, relation="intersection", max_operations=1)
    assert tuple(result.iter_entries()) == (("s", "W", True),)

    with pytest.raises(ValueError, match="bounded operation limit"):
        left.hadamard(right, semiring, relation="bounded", max_operations=0)


def test_hadamard_emits_canonical_csr_without_reindexing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = TypedAxis("rows", "code", ("a", "b", "c"))
    columns = TypedAxis("columns", "type", ("T", "U", "V", "W"))
    semiring = BooleanSemiring()
    left = _block(
        "left",
        rows,
        columns,
        (
            ("a", "T", True),
            ("b", "U", True),
            ("c", "T", True),
            ("c", "W", True),
        ),
    )
    right = _block(
        "right",
        rows,
        columns,
        (
            ("a", "T", True),
            ("b", "V", True),
            ("c", "T", True),
            ("c", "U", True),
            ("c", "W", True),
        ),
    )

    def explode(*args: object, **kwargs: object) -> object:
        raise AssertionError("Hadamard rematerialized streamed intersections")

    monkeypatch.setattr(TypedRelationBlock, "_from_indexed", classmethod(explode))

    result = left.hadamard(right, semiring, relation="intersection")

    assert result.row_offsets == (0, 1, 1, 3)
    assert result.column_indices == (0, 0, 3)
    assert tuple(result.iter_entries()) == (
        ("a", "T", True),
        ("c", "T", True),
        ("c", "W", True),
    )
