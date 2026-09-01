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
