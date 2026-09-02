from __future__ import annotations

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


class _HashProbeLabel(str):
    def __hash__(self) -> int:
        raise AssertionError("TypedAxis duplicate detection materialized a full hash set")


def _subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


def _forbid_full_label_index(_axis: TypedAxis) -> object:
    raise AssertionError("relation-block lookup materialized a full axis label index")


def test_typed_axis_detects_duplicates_after_canonical_sort() -> None:
    axis = TypedAxis(
        "code",
        "code",
        (_HashProbeLabel("src/z.py"), _HashProbeLabel("src/a.py")),
    )

    assert axis.labels == ("src/a.py", "src/z.py")

    with pytest.raises(ValueError, match="axis.labels must not contain duplicates"):
        TypedAxis("code", "code", ("src/a.py", "src/a.py"))


def test_coordinate_build_and_get_reuse_sorted_axis_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    row_axis = TypedAxis("code", "code", ("src/z.py", "src/a.py", "src/m.py"))
    column_axis = TypedAxis("type", "type", ("Widget", "Adapter", "Service"))
    semiring = BooleanSemiring()

    monkeypatch.setattr(TypedAxis, "label_index", property(_forbid_full_label_index))

    block = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=row_axis,
        column_axis=column_axis,
        coordinates=(("src/z.py", "Widget", True), ("src/a.py", "Service", True)),
        semiring=semiring,
    )

    assert tuple(block.iter_entries()) == (
        ("src/a.py", "Service", True),
        ("src/z.py", "Widget", True),
    )
    assert block.get("src/z.py", "Widget", semiring) is True
    assert block.get("src/m.py", "Adapter", semiring) is False

    with pytest.raises(ValueError, match="unknown row label"):
        block.get("src/missing.py", "Widget", semiring)
    with pytest.raises(ValueError, match="unknown column label"):
        block.get("src/z.py", "Missing", semiring)


def test_coordinate_build_still_refuses_unknown_axis_labels() -> None:
    semiring = BooleanSemiring()
    row_axis = TypedAxis("code", "code", ("src/a.py",))
    column_axis = TypedAxis("type", "type", ("Widget",))

    with pytest.raises(ValueError, match="unknown row label"):
        TypedRelationBlock.from_coordinates(
            subject=_subject(),
            signature=RelationSignature("code", "declares", "type"),
            row_axis=row_axis,
            column_axis=column_axis,
            coordinates=(("src/missing.py", "Widget", True),),
            semiring=semiring,
        )

    with pytest.raises(ValueError, match="unknown column label"):
        TypedRelationBlock.from_coordinates(
            subject=_subject(),
            signature=RelationSignature("code", "declares", "type"),
            row_axis=row_axis,
            column_axis=column_axis,
            coordinates=(("src/a.py", "Missing", True),),
            semiring=semiring,
        )
