from __future__ import annotations

import pytest

from daedalus.twin.contractions import boolean_overlap_disagreements
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring, NaturalSemiring

REVISION = "a" * 40
FOURFOLD = "b" * 64


def _subject(*, revision: str = REVISION) -> ProjectionSubject:
    return ProjectionSubject("KTY137/daedalus", revision, FOURFOLD)


def _block(
    *,
    rows: tuple[str, ...],
    columns: tuple[str, ...],
    coordinates: tuple[tuple[str, str, object], ...],
    subject: ProjectionSubject | None = None,
    relation: str = "observes",
    semiring: object | None = None,
) -> TypedRelationBlock[object]:
    selected_semiring = semiring or BooleanSemiring()
    return TypedRelationBlock.from_coordinates(
        subject=subject or _subject(),
        signature=RelationSignature("code", relation, "type"),
        row_axis=TypedAxis("local-code", "code", rows),
        column_axis=TypedAxis("local-type", "type", columns),
        coordinates=coordinates,
        semiring=selected_semiring,  # type: ignore[arg-type]
    )


def test_sparse_zero_inside_shared_extent_is_a_real_disagreement() -> None:
    left = _block(
        rows=("left", "shared"),
        columns=("left-type", "shared-type"),
        coordinates=(("shared", "shared-type", True),),
    )
    right = _block(
        rows=("right", "shared"),
        columns=("right-type", "shared-type"),
        coordinates=(),
    )

    assert boolean_overlap_disagreements(left, right) == (
        ("shared", "shared-type"),
    )


def test_entries_outside_the_shared_extent_are_unobserved_not_false() -> None:
    left = _block(
        rows=("left", "shared"),
        columns=("left-type", "shared-type"),
        coordinates=(
            ("left", "left-type", True),
            ("shared", "shared-type", True),
        ),
    )
    right = _block(
        rows=("right", "shared"),
        columns=("right-type", "shared-type"),
        coordinates=(
            ("right", "right-type", True),
            ("shared", "shared-type", True),
        ),
    )

    assert boolean_overlap_disagreements(left, right) == ()


def test_empty_declared_overlap_refuses_vacuous_agreement() -> None:
    left = _block(rows=("left",), columns=("shared-type",), coordinates=())
    right = _block(rows=("right",), columns=("shared-type",), coordinates=())

    with pytest.raises(ValueError, match="non-empty declared axis overlap"):
        boolean_overlap_disagreements(left, right)


def test_overlap_comparison_is_exactly_subject_and_signature_bound() -> None:
    left = _block(rows=("shared",), columns=("shared-type",), coordinates=())
    other_revision = _block(
        rows=("shared",),
        columns=("shared-type",),
        coordinates=(),
        subject=_subject(revision="c" * 40),
    )
    other_relation = _block(
        rows=("shared",),
        columns=("shared-type",),
        coordinates=(),
        relation="declares",
    )

    with pytest.raises(ValueError, match="same exact Fourfold subject"):
        boolean_overlap_disagreements(left, other_revision)
    with pytest.raises(ValueError, match="same relation signature"):
        boolean_overlap_disagreements(left, other_relation)


def test_overlap_comparison_refuses_non_boolean_blocks() -> None:
    natural = NaturalSemiring()
    left = _block(
        rows=("shared",),
        columns=("shared-type",),
        coordinates=(("shared", "shared-type", 1),),
        semiring=natural,
    )
    right = _block(
        rows=("shared",),
        columns=("shared-type",),
        coordinates=(("shared", "shared-type", 1),),
        semiring=natural,
    )

    with pytest.raises(ValueError, match="boolean relation blocks"):
        boolean_overlap_disagreements(left, right)  # type: ignore[arg-type]
