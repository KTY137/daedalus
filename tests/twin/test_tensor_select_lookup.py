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


class _ReadBoundLabels(tuple[str, ...]):
    def __new__(cls, values: tuple[str, ...]) -> "_ReadBoundLabels":
        instance = super().__new__(cls, values)
        instance.reads = 0
        return instance

    def __getitem__(self, index: int) -> str:
        if not isinstance(index, slice):
            self.reads += 1
            if self.reads > 16:
                raise AssertionError(
                    "entry lookup re-read canonical axis labels instead of reusing coordinates"
                )
        return super().__getitem__(index)


class _PrefixPredicateForbiddenCoordinates(tuple[tuple[str, str], ...]):
    def __getitem__(self, index):  # type: ignore[no-untyped-def]
        if isinstance(index, int) and index == 0:
            raise AssertionError("selector rechecked a prefix already proven by bisect bounds")
        return super().__getitem__(index)


_COORDINATE_READS: dict[int, int] = {}
_INDEX_PAYLOAD_READS = 0
_INDEX_PAYLOAD_PROBE = False


class _CoordinateReadBoundEntry(SparseTensorEntry):
    def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
        if name == "coordinates":
            entry_id = id(self)
            reads = _COORDINATE_READS.get(entry_id)
            if reads is not None:
                reads += 1
                _COORDINATE_READS[entry_id] = reads
                if reads > 2:
                    raise AssertionError(
                        "canonical TensorView construction re-walked entries for duplicate validation"
                    )
        return super().__getattribute__(name)


class _IndexPayloadReadBoundEntry(SparseTensorEntry):
    def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
        global _INDEX_PAYLOAD_READS
        if _INDEX_PAYLOAD_PROBE and name in {"value", "masked", "evidence_sha256s"}:
            _INDEX_PAYLOAD_READS += 1
            if _INDEX_PAYLOAD_READS > 8:
                raise AssertionError(
                    "entry lookup reread non-semantic payload while bisecting canonical claims"
                )
        return super().__getattribute__(name)


class _CanonicalOrderPayloadForbiddenEntry(SparseTensorEntry):
    def __getattribute__(self, name: str):  # type: ignore[no-untyped-def]
        if name in {"value", "masked", "evidence_sha256s"}:
            try:
                forbidden = object.__getattribute__(self, "_payload_reads_forbidden")
            except AttributeError:
                forbidden = False
            if forbidden:
                raise AssertionError(
                    "TensorView canonicalization read payload after the semantic claim was unique"
                )
        return super().__getattribute__(name)


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


def _full_prefix_tensor() -> TensorView:
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(TensorAxis("group", ("g",)),),
        entries=tuple(
            SparseTensorEntry(
                coordinates=(("group", "g"),),
                relation=f"relation-{index:03d}",
                evidence_sha256s=("d" * 64,),
            )
            for index in range(512)
        ),
        provenance=_provenance(),
    )


def test_canonical_entry_validation_does_not_rewalk_duplicate_claims() -> None:
    labels = tuple(f"node-{index:03d}" for index in range(128))
    entries = tuple(
        _CoordinateReadBoundEntry(
            coordinates=(("node", node),),
            relation="membership",
            evidence_sha256s=("d" * 64,),
        )
        for node in labels
    )
    for entry in entries:
        _COORDINATE_READS[id(entry)] = 0

    try:
        tensor = TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=(TensorAxis("node", labels),),
            entries=entries,
            provenance=_provenance(),
        )

        assert tensor.entries is entries
        assert max(_COORDINATE_READS[id(entry)] for entry in entries) == 2
    finally:
        for entry in entries:
            _COORDINATE_READS.pop(id(entry), None)


def test_entry_canonicalization_orders_only_by_unique_semantic_claim_key() -> None:
    labels = tuple(f"node-{index:03d}" for index in range(128))
    entries = tuple(
        _CanonicalOrderPayloadForbiddenEntry(
            coordinates=(("node", node),),
            relation="membership",
            value=float(index + 1),
            evidence_sha256s=(f"{index + 1:064x}",),
        )
        for index, node in reversed(tuple(enumerate(labels)))
    )
    for entry in entries:
        object.__setattr__(entry, "_payload_reads_forbidden", True)

    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(TensorAxis("node", labels),),
        entries=entries,
        provenance=_provenance(),
    )

    assert tuple(entry.coordinates[0][1] for entry in tensor.entries) == labels


def test_canonical_entry_validation_still_rejects_duplicate_claims() -> None:
    entries = (
        SparseTensorEntry(
            coordinates=(("node", "node-000"),),
            relation="membership",
            value=1.0,
            evidence_sha256s=("d" * 64,),
        ),
        SparseTensorEntry(
            coordinates=(("node", "node-000"),),
            relation="membership",
            value=2.0,
            evidence_sha256s=("e" * 64,),
        ),
    )

    with pytest.raises(ValueError, match="must not repeat a coordinate/relation claim"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=(TensorAxis("node", ("node-000",)),),
            entries=entries,
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


def test_select_reuses_full_range_when_prefix_proves_every_entry() -> None:
    tensor = _full_prefix_tensor()
    probed_entries = _ReadBoundEntries(tensor.entries)
    object.__setattr__(tensor, "entries", probed_entries)

    selected = tensor.select(group="g")

    assert selected is probed_entries
    assert probed_entries.reads <= 28


def test_select_does_not_recheck_bisected_prefix_predicate() -> None:
    tensor = _tensor()
    expected = tensor.entries[-2:]
    for entry in expected:
        object.__setattr__(
            entry,
            "coordinates",
            _PrefixPredicateForbiddenCoordinates(entry.coordinates),
        )

    selected = tensor.select(node="node-255")

    assert selected == expected


def test_index_coordinate_bisects_only_the_unique_semantic_claim_key() -> None:
    global _INDEX_PAYLOAD_PROBE, _INDEX_PAYLOAD_READS
    labels = tuple(f"node-{index:03d}" for index in range(256))
    entries = tuple(
        _IndexPayloadReadBoundEntry(
            coordinates=(("node", node),),
            relation="membership",
            value=float(index + 1),
            evidence_sha256s=(f"{index + 1:064x}",),
        )
        for index, node in enumerate(labels)
    )
    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(TensorAxis("node", labels),),
        entries=entries,
        provenance=_provenance(),
    )

    _INDEX_PAYLOAD_READS = 0
    _INDEX_PAYLOAD_PROBE = True
    try:
        assert tensor.index_coordinate(entries[-1]) == (255,)
        assert _INDEX_PAYLOAD_READS <= 8
    finally:
        _INDEX_PAYLOAD_PROBE = False


def test_select_and_index_reuse_validated_coordinate_label_order() -> None:
    tensor = _tensor()
    target = tensor.select(node="node-255")[0]
    probes: dict[str, _ReadBoundLabels] = {}
    for axis in tensor.axes:
        probe = _ReadBoundLabels(axis.labels)
        object.__setattr__(axis, "labels", probe)
        probes[axis.name] = probe

    selected = tensor.select(node="node-255")

    assert selected[0] == target
    assert probes["node"].reads <= 16
    assert probes["plane"].reads == 0

    for probe in probes.values():
        probe.reads = 0

    assert tensor.index_coordinate(target) == (255, 0)
    assert probes["node"].reads <= 16
    assert probes["plane"].reads <= 4


def test_select_preserves_non_prefix_filter_and_fail_closed_validation() -> None:
    tensor = _tensor()

    selected = tensor.select(plane="code")
    assert len(selected) == 256
    assert all(entry.coordinate_map["plane"] == "code" for entry in selected)

    with pytest.raises(ValueError, match="unknown tensor axis"):
        tensor.select(missing="value")
    with pytest.raises(ValueError, match="not declared by axis"):
        tensor.select(node="node-999")