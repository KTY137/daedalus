from __future__ import annotations

import inspect

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

REVISION = "a" * 40
FOURFOLD = "b" * 64


def _subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


def _axes() -> tuple[TypedAxis, TypedAxis]:
    return (
        TypedAxis("rows", "code", ("r0", "r1")),
        TypedAxis("columns", "type", ("c0", "c1", "c2")),
    )


def _kwargs(
    *,
    row_offsets: tuple[object, ...] = (0, 2, 3),
    column_indices: tuple[object, ...] = (0, 2, 1),
    values: tuple[object, ...] = (True, True, True),
) -> dict[str, object]:
    rows, columns = _axes()
    return {
        "subject": _subject(),
        "signature": RelationSignature("code", "declares", "type"),
        "row_axis": rows,
        "column_axis": columns,
        "semiring_name": "boolean",
        "row_offsets": row_offsets,
        "column_indices": column_indices,
        "values": values,
    }


def _error(**overrides: object) -> str:
    kwargs = _kwargs()
    kwargs.update(overrides)
    with pytest.raises(ValueError) as exc_info:
        TypedRelationBlock(**kwargs)  # type: ignore[arg-type]
    return str(exc_info.value)


def test_fused_validation_retains_canonical_block_identity_and_digest() -> None:
    direct = TypedRelationBlock(**_kwargs())  # type: ignore[arg-type]
    rows, columns = _axes()
    from_coordinates = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=(
            ("r0", "c0", True),
            ("r0", "c2", True),
            ("r1", "c1", True),
        ),
        semiring=BooleanSemiring(),
    )

    assert direct == from_coordinates
    assert direct.to_json() == from_coordinates.to_json()
    assert direct.digest == from_coordinates.digest


@pytest.mark.parametrize(
    ("overrides", "expected"),
    (
        (
            {"row_offsets": (0, "bad", 3)},
            "block.row_offsets must contain integers",
        ),
        (
            {"row_offsets": (1, 0, 3)},
            "block.row_offsets must contain every row boundary and start at zero",
        ),
        (
            {"row_offsets": (0, 3, 2)},
            "block.row_offsets must be monotone",
        ),
        (
            {"column_indices": (3, "bad", 1)},
            "block.column_indices must contain integers",
        ),
        (
            {"column_indices": (2, 1, 3)},
            "block.column_indices contains an out-of-range index",
        ),
        (
            {"row_offsets": (0, 2, 2), "column_indices": (2, 1, 0)},
            "CSR arrays must terminate at the common entry count",
        ),
        (
            {"column_indices": (2, 1, 0)},
            "column indices must be strictly increasing inside each row",
        ),
    ),
)
def test_fused_validation_preserves_prehead_error_precedence(
    overrides: dict[str, object],
    expected: str,
) -> None:
    assert _error(**overrides) == expected


def test_scalar_admission_still_precedes_structural_validation() -> None:
    assert _error(values=(False, True, True), row_offsets=(0, 3, 2)) == (
        "relation blocks must not store semiring zero values"
    )


def test_constructor_no_longer_uses_generic_any_or_per_row_column_slices() -> None:
    source = inspect.getsource(TypedRelationBlock.__post_init__)
    assert "any(" not in source
    assert "columns[offsets[row]" not in source
