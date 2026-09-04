from __future__ import annotations

import pytest

from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)

REVISION = "a" * 40
FOURFOLD = "b" * 64


def subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


class OpaqueIntegerSemiring:
    name = "opaque-integer"
    zero = 0
    one = 1

    @staticmethod
    def add(left: int, right: int) -> int:
        return left + right

    @staticmethod
    def multiply(left: int, right: int) -> int:
        return left * right


class AlternateBooleanBackend:
    name = "boolean"
    zero = False
    one = True

    @staticmethod
    def add(left: bool, right: bool) -> bool:
        return left or right

    @staticmethod
    def multiply(left: bool, right: bool) -> bool:
        return left and right


class DivergentBooleanBackend:
    name = "boolean"
    zero = True
    one = False

    @staticmethod
    def add(left: bool, right: bool) -> bool:
        return left and right

    @staticmethod
    def multiply(left: bool, right: bool) -> bool:
        return left or right


class DivergentNaturalBackend:
    name = "natural"
    zero = 0
    one = 1

    @staticmethod
    def add(left: int, right: int) -> int:
        return left + right

    @staticmethod
    def multiply(left: int, right: int) -> int:
        return left + right


def axes() -> tuple[TypedAxis, TypedAxis]:
    return (
        TypedAxis("rows", "code", ("a",)),
        TypedAxis("columns", "type", ("T",)),
    )


def test_nonempty_unknown_semiring_cannot_persist_opaque_scalars() -> None:
    rows, columns = axes()

    with pytest.raises(ValueError, match="unsupported persisted semiring"):
        TypedRelationBlock.from_coordinates(
            subject=subject(),
            signature=RelationSignature("code", "declares", "type"),
            row_axis=rows,
            column_axis=columns,
            coordinates=(("a", "T", 1),),
            semiring=OpaqueIntegerSemiring(),
        )


def test_direct_unknown_semiring_cannot_bypass_scalar_contract() -> None:
    rows, columns = axes()

    with pytest.raises(ValueError, match="unsupported persisted semiring"):
        TypedRelationBlock(
            subject=subject(),
            signature=RelationSignature("code", "declares", "type"),
            row_axis=rows,
            column_axis=columns,
            semiring_name="opaque-integer",
            row_offsets=(0, 1),
            column_indices=(0,),
            values=(1,),
        )


def test_empty_unknown_semiring_cannot_bypass_persisted_semantics() -> None:
    rows, columns = axes()

    with pytest.raises(ValueError, match="unsupported persisted semiring"):
        TypedRelationBlock(
            subject=subject(),
            signature=RelationSignature("code", "declares", "type"),
            row_axis=rows,
            column_axis=columns,
            semiring_name="opaque-integer",
            row_offsets=(0, 0),
            column_indices=(),
            values=(),
        )


def test_known_semiring_name_still_allows_protocol_backend_substitution() -> None:
    rows, columns = axes()

    block = TypedRelationBlock.from_coordinates(
        subject=subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=(("a", "T", True),),
        semiring=AlternateBooleanBackend(),
    )

    assert block.semiring_name == "boolean"
    assert tuple(block.iter_entries()) == (("a", "T", True),)


def test_known_semiring_name_cannot_spoof_reference_identity_or_addition() -> None:
    rows, columns = axes()

    block = TypedRelationBlock.from_coordinates(
        subject=subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=rows,
        column_axis=columns,
        coordinates=(("a", "T", True), ("a", "T", True)),
        semiring=DivergentBooleanBackend(),
    )

    assert tuple(block.iter_entries()) == (("a", "T", True),)
    assert block.get("a", "T", DivergentBooleanBackend()) is True

    empty = TypedRelationBlock(
        subject=subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=rows,
        column_axis=columns,
        semiring_name="boolean",
        row_offsets=(0, 0),
        column_indices=(),
        values=(),
    )
    assert empty.get("a", "T", DivergentBooleanBackend()) is False


def test_known_semiring_name_cannot_spoof_reference_multiplication() -> None:
    code_axis = TypedAxis("code", "code", ("a",))
    type_axis = TypedAxis("type", "type", ("T",))
    data_axis = TypedAxis("data", "data", ("field",))
    semiring = DivergentNaturalBackend()

    left = TypedRelationBlock.from_coordinates(
        subject=subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=code_axis,
        column_axis=type_axis,
        coordinates=(("a", "T", 2),),
        semiring=semiring,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=subject(),
        signature=RelationSignature("type", "shapes", "data"),
        row_axis=type_axis,
        column_axis=data_axis,
        coordinates=(("T", "field", 3),),
        semiring=semiring,
    )

    product = left.matmul(right, semiring, relation="reaches")

    assert tuple(product.iter_entries()) == (("a", "field", 6),)
