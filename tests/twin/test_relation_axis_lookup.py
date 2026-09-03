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


class _BoundedColumnProbe(tuple[int, ...]):
    def __new__(cls, values: tuple[int, ...], *, max_reads: int) -> "_BoundedColumnProbe":
        instance = super().__new__(cls, values)
        instance.max_reads = max_reads
        instance.reads = 0
        return instance

    def __getitem__(self, index: int | slice) -> int | tuple[int, ...]:
        if isinstance(index, int):
            self.reads += 1
            if self.reads > self.max_reads:
                raise AssertionError("relation-block point lookup linearly scanned a canonical CSR row")
        return super().__getitem__(index)


def _subject() -> ProjectionSubject:
    return ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_fourfold_sha256=FOURFOLD,
    )


def test_typed_axis_detects_duplicates_after_canonical_sort() -> None:
    axis = TypedAxis(
        "code",
        "code",
        (_HashProbeLabel("src/z.py"), _HashProbeLabel("src/a.py")),
    )

    assert axis.labels == ("src/a.py", "src/z.py")

    with pytest.raises(ValueError, match="axis.labels must not contain duplicates"):
        TypedAxis("code", "code", ("src/a.py", "src/a.py"))


def test_coordinate_build_and_get_use_only_canonical_axis_labels() -> None:
    row_axis = TypedAxis("code", "code", ("src/z.py", "src/a.py", "src/m.py"))
    column_axis = TypedAxis("type", "type", ("Widget", "Adapter", "Service"))
    semiring = BooleanSemiring()

    assert not hasattr(row_axis, "label_index")
    assert not hasattr(column_axis, "label_index")

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


def test_point_lookup_bisects_the_canonical_csr_row() -> None:
    semiring = BooleanSemiring()
    column_labels = tuple(f"Type{index:03d}" for index in range(256))
    block = TypedRelationBlock(
        _subject(),
        RelationSignature("code", "declares", "type"),
        TypedAxis("code", "code", ("src/a.py",)),
        TypedAxis("type", "type", column_labels),
        "boolean",
        (0, len(column_labels)),
        tuple(range(len(column_labels))),
        (True,) * len(column_labels),
    )
    probe = _BoundedColumnProbe(block.column_indices, max_reads=12)
    object.__setattr__(block, "column_indices", probe)

    assert block.get("src/a.py", "Type255", semiring) is True
    assert probe.reads <= probe.max_reads


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