"""Deterministic sparse tensor view of one exact Fourfold/Forest subject.

This is an internal computational projection only. Source artifacts, Forest and
Fourfold remain authoritative; this module adds no fifth plane or state store.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence

from ..schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _non_empty,
    _record_payload,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _sorted_strings,
)

TENSOR_STATUSES = frozenset({"complete", "partial", "absent"})
MAX_TENSOR_AXES = 16
MAX_AXIS_LABELS = 100_000
MAX_TENSOR_ENTRIES = 1_000_000
MAX_ENTRY_EVIDENCE_DIGESTS = 64


def _bounded_sequence(values: Any, name: str, limit: int) -> Sequence[Any]:
    """Refuse oversized construction input before copying or sorting it.

    The tensor contract advertises bounded construction. Checking a limit only
    after ``tuple(...)`` or ``sorted(...)`` has already consumed an attacker-
    sized input would bound the retained object but not the work needed to build
    it. All high-cardinality surfaces therefore pass through this one
    pre-canonicalization guard.
    """
    if isinstance(values, (str, bytes, Mapping)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be a bounded sequence")
    if len(values) > limit:
        raise ValueError(f"{name} exceeds bounded limit {limit}")
    return values


def _coordinate(values: Sequence[Sequence[Any]]) -> tuple[tuple[str, str], ...]:
    values = _bounded_sequence(values, "entry.coordinates", MAX_TENSOR_AXES)
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence) or len(raw) != 2:
            raise ValueError(f"entry.coordinates[{index}] must be an (axis, label) pair")
        axis = _identifier(raw[0], f"entry.coordinates[{index}].axis")
        label = _non_empty(raw[1], f"entry.coordinates[{index}].label", max_length=1000)
        if "\x00" in label:
            raise ValueError("entry coordinate labels must not contain NUL bytes")
        if axis in seen:
            raise ValueError("entry.coordinates must name every axis at most once")
        seen.add(axis)
        out.append((axis, label))
    return tuple(sorted(out))


@dataclass(frozen=True)
class TensorAxis:
    name: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "axis.name"))
        raw_labels = _bounded_sequence(self.labels, "axis.labels", MAX_AXIS_LABELS)
        labels = _sorted_strings(raw_labels, "axis.labels")
        if any("\x00" in label for label in labels):
            raise ValueError("axis.labels must not contain NUL bytes")
        object.__setattr__(self, "labels", labels)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TensorAxis":
        return cls(**_record_payload(cls, payload, "tensor axis"))


@dataclass(frozen=True)
class SparseTensorEntry:
    coordinates: tuple[tuple[str, str], ...]
    relation: str
    value: float = 1.0
    masked: bool = False
    evidence_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "coordinates", _coordinate(self.coordinates))
        object.__setattr__(self, "relation", _identifier(self.relation, "entry.relation"))
        if type(self.value) not in (int, float):
            raise ValueError("entry.value must be a finite number")
        try:
            value = float(self.value)
        except OverflowError as exc:
            raise ValueError("entry.value must be a finite number") from exc
        if not math.isfinite(value):
            raise ValueError("entry.value must be a finite number")
        if type(self.value) is int and int(value) != self.value:
            raise ValueError("entry.value integer must be exactly representable as binary64")
        if value == 0.0:
            value = 0.0
        object.__setattr__(self, "value", value)
        if type(self.masked) is not bool:
            raise ValueError("entry.masked must be boolean")
        raw_evidence = _bounded_sequence(
            self.evidence_sha256s,
            "entry.evidence_sha256s",
            MAX_ENTRY_EVIDENCE_DIGESTS,
        )
        evidence = _sorted_strings(
            raw_evidence, "entry.evidence_sha256s", digests=True
        )
        if not evidence:
            raise ValueError("entry must retain evidence digests")
        object.__setattr__(self, "evidence_sha256s", evidence)

    @property
    def coordinate_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.coordinates))

    @property
    def semantic_key(self) -> tuple[tuple[tuple[str, str], ...], str]:
        return self.coordinates, self.relation

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SparseTensorEntry":
        return cls(**_record_payload(cls, payload, "sparse tensor entry"))


@dataclass(frozen=True)
class TensorView(CanonicalContract):
    """Immutable derived view; completeness describes the projection only."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.twin.tensor-view"

    repository_id: str
    source_revision: str
    source_forest_sha256: str
    source_fourfold_sha256: str
    status: str
    axes: tuple[TensorAxis, ...]
    entries: tuple[SparseTensorEntry, ...]
    provenance: ContractProvenance
    reason: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "repository_id", _identifier(self.repository_id, "repository_id"))
        object.__setattr__(self, "source_revision", _revision(self.source_revision, "source_revision"))
        object.__setattr__(self, "source_forest_sha256", _sha256(self.source_forest_sha256, "source_forest_sha256"))
        object.__setattr__(self, "source_fourfold_sha256", _sha256(self.source_fourfold_sha256, "source_fourfold_sha256"))
        if not isinstance(self.status, str) or self.status not in TENSOR_STATUSES:
            raise ValueError("tensor.status must be complete, partial, or absent")

        raw_axes = _bounded_sequence(self.axes, "tensor.axes", MAX_TENSOR_AXES)
        axes = tuple(raw_axes)
        if any(not isinstance(axis, TensorAxis) for axis in axes):
            raise ValueError("tensor.axes must contain TensorAxis records")
        by_name = {axis.name: axis for axis in axes}
        if len(by_name) != len(axes):
            raise ValueError("tensor.axes must have unique names")
        axes = tuple(by_name[name] for name in sorted(by_name))
        object.__setattr__(self, "axes", axes)

        raw_entries = _bounded_sequence(self.entries, "tensor.entries", MAX_TENSOR_ENTRIES)
        entries = tuple(raw_entries)
        if any(not isinstance(entry, SparseTensorEntry) for entry in entries):
            raise ValueError("tensor.entries must contain SparseTensorEntry records")
        axis_names = tuple(axis.name for axis in axes)
        label_index = {
            axis.name: {label: index for index, label in enumerate(axis.labels)}
            for axis in axes
        }
        seen: set[tuple[tuple[tuple[str, str], ...], str]] = set()
        for entry in entries:
            # SparseTensorEntry already canonicalizes coordinates by axis name.
            # TensorView canonicalizes axes by the same key, so positional
            # comparison is sufficient and avoids allocating one mapping per
            # entry during construction.
            if tuple(axis for axis, _ in entry.coordinates) != axis_names:
                raise ValueError("every sparse entry must bind exactly the TensorView axes")
            for axis, label in entry.coordinates:
                if label not in label_index[axis]:
                    raise ValueError(f"entry label {label!r} is not declared by axis {axis!r}")
            if entry.semantic_key in seen:
                raise ValueError("tensor.entries must not repeat a coordinate/relation claim")
            seen.add(entry.semantic_key)

        def order(entry: SparseTensorEntry) -> tuple[Any, ...]:
            indices = tuple(label_index[axis][label] for axis, label in entry.coordinates)
            return indices, entry.relation, entry.masked, entry.value, entry.evidence_sha256s

        object.__setattr__(self, "entries", tuple(sorted(entries, key=order)))
        reason = self.reason
        if not isinstance(reason, str):
            raise ValueError("tensor.reason must be a string")
        if reason:
            reason = _non_empty(reason, "tensor.reason", max_length=2000)
            object.__setattr__(self, "reason", reason)
        if self.status == "absent":
            if self.axes or self.entries:
                raise ValueError("an absent tensor cannot contain axes or entries")
            if not reason:
                raise ValueError("an absent tensor must retain a reason")
        elif self.status == "partial":
            if not self.axes:
                raise ValueError("a partial tensor must retain its known axes")
            if not reason:
                raise ValueError("a partial tensor must explain what is incomplete")
        elif not self.axes:
            raise ValueError("a complete tensor must contain at least one axis")
        elif reason:
            raise ValueError("a complete tensor must not carry an incompleteness reason")

        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("tensor.provenance must be ContractProvenance")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("tensor source_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance,
            (self.source_forest_sha256, self.source_fourfold_sha256),
            "tensor view",
        )

    @property
    def shape(self) -> tuple[int, ...]:
        return tuple(len(axis.labels) for axis in self.axes)

    @property
    def axis_map(self) -> Mapping[str, TensorAxis]:
        return MappingProxyType({axis.name: axis for axis in self.axes})

    def index_coordinate(self, entry: SparseTensorEntry) -> tuple[int, ...]:
        if entry not in self.entries:
            raise ValueError("entry is not retained by this TensorView")
        coordinate = entry.coordinate_map
        return tuple(axis.labels.index(coordinate[axis.name]) for axis in self.axes)

    def select(self, **coordinates: str) -> tuple[SparseTensorEntry, ...]:
        normalized: dict[int, str] = {}
        axis_positions = {axis.name: index for index, axis in enumerate(self.axes)}
        for name, raw in coordinates.items():
            if name not in axis_positions:
                raise ValueError(f"unknown tensor axis {name!r}")
            position = axis_positions[name]
            label = _non_empty(raw, f"selector.{name}", max_length=1000)
            if label not in self.axes[position].labels:
                raise ValueError(f"selector label {label!r} is not declared by axis {name!r}")
            normalized[position] = label
        return tuple(
            entry
            for entry in self.entries
            if all(entry.coordinates[position][1] == label for position, label in normalized.items())
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TensorView":
        body = cls._contract_payload(payload)
        raw_axes = _bounded_sequence(body["axes"], "tensor.axes", MAX_TENSOR_AXES)
        raw_entries = _bounded_sequence(body["entries"], "tensor.entries", MAX_TENSOR_ENTRIES)
        body["axes"] = tuple(TensorAxis.from_dict(item) for item in raw_axes)
        body["entries"] = tuple(SparseTensorEntry.from_dict(item) for item in raw_entries)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def parse_tensor_view(payload: Mapping[str, Any]) -> TensorView:
    return TensorView.from_dict(payload)
