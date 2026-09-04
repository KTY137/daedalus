from __future__ import annotations

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
NOW = "2026-09-02T13:58:00Z"


class _ReadBoundEntries(tuple[SparseTensorEntry, ...]):
    def __new__(cls, values: tuple[SparseTensorEntry, ...]) -> "_ReadBoundEntries":
        instance = super().__new__(cls, values)
        instance.reads = 0
        return instance

    def __contains__(self, item: object) -> bool:
        raise AssertionError("index_coordinate must not linearly scan TensorView.entries")

    def __getitem__(self, index: int) -> SparseTensorEntry:
        self.reads += 1
        if self.reads > 12:
            raise AssertionError("index_coordinate exceeded the bounded binary-search read budget")
        return super().__getitem__(index)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="test.tensor.index-coordinate",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(FOREST, FOURFOLD),
    )


def _entry(node: str, *, value: float = 1.0) -> SparseTensorEntry:
    return SparseTensorEntry(
        coordinates=(("node", node), ("plane", "code")),
        relation="membership",
        value=value,
        evidence_sha256s=("d" * 64,),
    )


def test_index_coordinate_bisects_canonical_entries_without_linear_membership() -> None:
    labels = tuple(f"node-{index:03d}" for index in range(256))
    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(TensorAxis("plane", ("code",)), TensorAxis("node", labels)),
        entries=tuple(_entry(label) for label in reversed(labels)),
        provenance=_provenance(),
    )
    target = tensor.entries[-1]
    probed_entries = _ReadBoundEntries(tensor.entries)
    object.__setattr__(tensor, "entries", probed_entries)

    assert tensor.index_coordinate(target) == (255, 0)
    assert probed_entries.reads <= 12

    probed_entries.reads = 0
    with pytest.raises(ValueError, match="entry is not retained"):
        tensor.index_coordinate(_entry(labels[-1], value=2.0))
    assert probed_entries.reads <= 12
