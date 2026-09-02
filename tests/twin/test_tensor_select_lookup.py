from __future__ import annotations

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
NOW = "2026-09-02T15:01:00Z"


class _ReadBoundEntries(tuple[SparseTensorEntry, ...]):
    def __new__(cls, values: tuple[SparseTensorEntry, ...]) -> "_ReadBoundEntries":
        instance = super().__new__(cls, values)
        instance.reads = 0
        return instance

    def __iter__(self):
        raise AssertionError("prefix selection must not linearly iterate TensorView.entries")

    def __getitem__(self, index: int) -> SparseTensorEntry:
        if isinstance(index, slice):
            raise AssertionError("prefix selection must not materialize an entry slice")
        self.reads += 1
        if self.reads > 28:
            raise AssertionError("prefix selection exceeded the bounded binary-search read budget")
        return super().__getitem__(index)


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="test.tensor.select",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(FOREST, FOURFOLD),
    )


def _entry(node: str, plane: str) -> SparseTensorEntry:
    return SparseTensorEntry(
        coordinates=(("node", node), ("plane", plane)),
        relation="membership",
        evidence_sha256s=("d" * 64,),
    )


def _tensor() -> TensorView:
    labels = tuple(f"node-{index:03d}" for index in range(256))
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(
            TensorAxis("plane", ("knowledge", "code")),
            TensorAxis("node", tuple(reversed(labels))),
        ),
        entries=tuple(
            _entry(node, plane)
            for node in reversed(labels)
            for plane in ("knowledge", "code")
        ),
        provenance=_provenance(),
    )


def test_select_reuses_entries_for_unfiltered_query() -> None:
    tensor = _tensor()

    assert tensor.select() is tensor.entries


def test_select_bisects_canonical_prefix_without_full_entry_scan() -> None:
    tensor = _tensor()
    probed_entries = _ReadBoundEntries(tensor.entries)
    object.__setattr__(tensor, "entries", probed_entries)

    selected = tensor.select(node="node-255")

    assert tuple(entry.coordinate_map["plane"] for entry in selected) == (
        "code",
        "knowledge",
    )
    assert probed_entries.reads <= 28


def test_select_preserves_non_prefix_filter_and_fail_closed_validation() -> None:
    tensor = _tensor()

    selected = tensor.select(plane="code")
    assert len(selected) == 256
    assert all(entry.coordinate_map["plane"] == "code" for entry in selected)

    with pytest.raises(ValueError, match="unknown tensor axis"):
        tensor.select(missing="value")
    with pytest.raises(ValueError, match="not declared by axis"):
        tensor.select(node="node-999")
