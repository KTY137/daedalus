from __future__ import annotations

from collections.abc import Sequence

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import (
    MAX_AXIS_LABELS,
    MAX_TENSOR_AXES,
    MAX_TENSOR_ENTRIES,
    SparseTensorEntry,
    TensorAxis,
    TensorView,
)

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
NOW = "2026-08-30T05:59:00Z"


class ExplodingSequence(Sequence[object]):
    """A sized sequence that proves refusal happened before element access."""

    def __init__(self, length: int) -> None:
        self.length = length
        self.accessed = False

    def __len__(self) -> int:
        return self.length

    def __getitem__(self, index: int) -> object:
        self.accessed = True
        raise AssertionError(f"oversized input was consumed at index {index}")


def provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="test.tensor.bounds",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(FOREST, FOURFOLD),
        trace_id="tensor-construction-bounds",
    )


def test_axis_label_limit_refuses_before_sort_or_element_access() -> None:
    labels = ExplodingSequence(MAX_AXIS_LABELS + 1)

    with pytest.raises(ValueError, match="axis.labels exceeds bounded limit"):
        TensorAxis("node", labels)  # type: ignore[arg-type]

    assert labels.accessed is False


def test_coordinate_limit_refuses_before_coordinate_parsing() -> None:
    coordinates = ExplodingSequence(MAX_TENSOR_AXES + 1)

    with pytest.raises(ValueError, match="entry.coordinates exceeds bounded limit"):
        SparseTensorEntry(
            coordinates=coordinates,  # type: ignore[arg-type]
            relation="membership",
            evidence_sha256s=("d" * 64,),
        )

    assert coordinates.accessed is False


def test_axis_count_limit_refuses_before_copying_records() -> None:
    axes = ExplodingSequence(MAX_TENSOR_AXES + 1)

    with pytest.raises(ValueError, match="tensor.axes exceeds bounded limit"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=axes,  # type: ignore[arg-type]
            entries=(),
            provenance=provenance(),
        )

    assert axes.accessed is False


def test_entry_count_limit_refuses_before_copying_records() -> None:
    entries = ExplodingSequence(MAX_TENSOR_ENTRIES + 1)

    with pytest.raises(ValueError, match="tensor.entries exceeds bounded limit"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="absent",
            axes=(),
            entries=entries,  # type: ignore[arg-type]
            provenance=provenance(),
            reason="projection intentionally absent",
        )

    assert entries.accessed is False


def test_tensor_view_avoids_full_axis_label_index_materialization() -> None:
    axis = TensorAxis("node", ("a", "m", "z"))

    class BisectOnlyLabels(tuple):
        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("TensorView iterated every axis label to build an index")

    object.__setattr__(axis, "labels", BisectOnlyLabels(axis.labels))
    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(axis,),
        entries=(
            SparseTensorEntry(
                coordinates=(("node", "m"),),
                relation="membership",
                evidence_sha256s=("d" * 64,),
            ),
        ),
        provenance=provenance(),
    )

    assert tensor.index_coordinate(tensor.entries[0]) == (1,)


def test_tensor_view_select_avoids_linear_axis_label_membership_scan() -> None:
    axis = TensorAxis("node", ("a", "m", "z"))
    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(axis,),
        entries=(
            SparseTensorEntry(
                coordinates=(("node", "m"),),
                relation="membership",
                evidence_sha256s=("d" * 64,),
            ),
        ),
        provenance=provenance(),
    )

    class BisectOnlyLabels(tuple):
        def __contains__(self, value: object) -> bool:
            raise AssertionError(f"selector linearly scanned axis labels for {value!r}")

    object.__setattr__(tensor.axes[0], "labels", BisectOnlyLabels(tensor.axes[0].labels))

    assert tensor.select(node="m") == tensor.entries
    with pytest.raises(ValueError, match="selector label 'x' is not declared by axis 'node'"):
        tensor.select(node="x")


def test_tensor_view_duplicate_tracking_does_not_hash_every_semantic_key() -> None:
    axis = TensorAxis("node", ("a", "z"))
    left = SparseTensorEntry(
        coordinates=(("node", "a"),),
        relation="membership",
        evidence_sha256s=("d" * 64,),
    )
    right = SparseTensorEntry(
        coordinates=(("node", "z"),),
        relation="membership",
        evidence_sha256s=("e" * 64,),
    )

    class HashForbiddenRelation(str):
        def __hash__(self) -> int:
            raise AssertionError("TensorView hashed every semantic key into a duplicate set")

    object.__setattr__(left, "relation", HashForbiddenRelation(left.relation))
    object.__setattr__(right, "relation", HashForbiddenRelation(right.relation))

    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(axis,),
        entries=(right, left),
        provenance=provenance(),
    )

    assert tuple(entry.coordinates[0][1] for entry in tensor.entries) == ("a", "z")


def test_tensor_view_still_rejects_duplicate_claims_after_canonical_sort() -> None:
    axis = TensorAxis("node", ("a",))
    first = SparseTensorEntry(
        coordinates=(("node", "a"),),
        relation="membership",
        masked=False,
        evidence_sha256s=("d" * 64,),
    )
    duplicate = SparseTensorEntry(
        coordinates=(("node", "a"),),
        relation="membership",
        masked=True,
        evidence_sha256s=("e" * 64,),
    )

    with pytest.raises(ValueError, match="must not repeat a coordinate/relation claim"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=(axis,),
            entries=(duplicate, first),
            provenance=provenance(),
        )


def test_unsized_iterables_are_not_silently_consumed() -> None:
    consumed = False

    def labels():
        nonlocal consumed
        consumed = True
        yield "a"

    with pytest.raises(ValueError, match="axis.labels must be a bounded sequence"):
        TensorAxis("node", labels())  # type: ignore[arg-type]

    assert consumed is False
