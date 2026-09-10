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


def _slice_fixture() -> TypedRelationBlock[bool]:
    semiring = BooleanSemiring()
    return TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=RelationSignature("code", "declares", "type"),
        row_axis=TypedAxis(
            "code",
            "code",
            ("src/c.py", "src/a.py", "src/b.py"),
        ),
        column_axis=TypedAxis(
            "type",
            "type",
            ("Widget", "Adapter", "Service"),
        ),
        coordinates=(
            ("src/a.py", "Adapter", True),
            ("src/a.py", "Widget", True),
            ("src/b.py", "Service", True),
            ("src/c.py", "Adapter", True),
            ("src/c.py", "Widget", True),
        ),
        semiring=semiring,
    )


def test_typed_axis_reuses_canonical_tuple_and_sorts_only_fallback() -> None:
    canonical = tuple(f"src/{index:03d}.py" for index in range(256))
    canonical_axis = TypedAxis("code", "code", canonical)

    assert canonical_axis.labels is canonical

    axis = TypedAxis(
        "code",
        "code",
        (_HashProbeLabel("src/z.py"), _HashProbeLabel("src/a.py")),
    )

    assert axis.labels == ("src/a.py", "src/z.py")

    with pytest.raises(ValueError, match="axis.labels must not contain duplicates"):
        TypedAxis("code", "code", ("src/a.py", "src/a.py"))


def test_typed_relation_block_reuses_exact_canonical_index_tuples() -> None:
    row_axis = TypedAxis("code", "code", ("src/a.py", "src/b.py"))
    column_axis = TypedAxis("type", "type", ("Adapter", "Widget"))
    offsets = (0, 1, 2)
    columns = (0, 1)

    block = TypedRelationBlock(
        _subject(),
        RelationSignature("code", "declares", "type"),
        row_axis,
        column_axis,
        "boolean",
        offsets,
        columns,
        (True, True),
    )

    assert block.row_offsets is offsets
    assert block.column_indices is columns


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


def test_slice_canonicalizes_requested_axes_and_preserves_exact_subject() -> None:
    block = _slice_fixture()

    sliced = block.slice(
        row_labels=("src/c.py", "src/a.py"),
        column_labels=("Widget", "Adapter"),
    )

    assert sliced.subject is block.subject
    assert sliced.signature is block.signature
    assert sliced.semiring_name == block.semiring_name
    assert sliced.row_axis.labels == ("src/a.py", "src/c.py")
    assert sliced.column_axis.labels == ("Adapter", "Widget")
    assert tuple(sliced.iter_entries()) == (
        ("src/a.py", "Adapter", True),
        ("src/a.py", "Widget", True),
        ("src/c.py", "Adapter", True),
        ("src/c.py", "Widget", True),
    )


def test_slice_is_deterministic_and_full_selection_reuses_immutable_block() -> None:
    block = _slice_fixture()

    left = block.slice(
        row_labels=("src/c.py", "src/a.py"),
        column_labels=("Widget", "Adapter"),
    )
    right = block.slice(
        row_labels=("src/a.py", "src/c.py"),
        column_labels=("Adapter", "Widget"),
    )

    assert left == right
    assert left.digest == right.digest
    assert block.slice(
        row_labels=("src/c.py", "src/b.py", "src/a.py"),
        column_labels=("Widget", "Service", "Adapter"),
    ) is block


def test_slice_refuses_unknown_and_duplicate_labels() -> None:
    block = _slice_fixture()

    with pytest.raises(ValueError, match="unknown row label"):
        block.slice(row_labels=("src/missing.py",))
    with pytest.raises(ValueError, match="unknown column label"):
        block.slice(column_labels=("Missing",))
    with pytest.raises(ValueError, match="row_labels must not contain duplicates"):
        block.slice(row_labels=("src/a.py", "src/a.py"))
    with pytest.raises(ValueError, match="column_labels must not contain duplicates"):
        block.slice(column_labels=("Adapter", "Adapter"))


def test_slice_preserves_shared_same_plane_axis_identity_and_empty_csr() -> None:
    axis = TypedAxis("code", "code", ("src/a.py", "src/b.py", "src/c.py"))
    block = TypedRelationBlock.from_coordinates(
        subject=_subject(),
        signature=RelationSignature("code", "imports", "code"),
        row_axis=axis,
        column_axis=axis,
        coordinates=(
            ("src/a.py", "src/b.py", True),
            ("src/b.py", "src/c.py", True),
        ),
        semiring=BooleanSemiring(),
    )

    sliced = block.slice(
        row_labels=("src/b.py", "src/a.py"),
        column_labels=("src/a.py", "src/b.py"),
    )
    empty = block.slice(row_labels=())

    assert sliced.row_axis is sliced.column_axis
    assert tuple(sliced.iter_entries()) == (("src/a.py", "src/b.py", True),)
    assert empty.row_axis.labels == ()
    assert empty.row_offsets == (0,)
    assert empty.column_indices == ()
    assert empty.values == ()
