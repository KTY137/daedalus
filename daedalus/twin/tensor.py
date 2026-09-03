"""Deterministic sparse tensor view of one exact Fourfold/Forest subject.

This is an internal computational projection only. Source artifacts, Forest and
Fourfold remain authoritative; this module adds no fifth plane or state store.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
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


def _sorted_label_index(labels: Sequence[str], label: str) -> int | None:
    """Return the exact position in canonical sorted labels without a full scan."""
    position = bisect_left(labels, label)
    if position == len(labels) or labels[position] != label:
        return None
    return position


def _coordinate(values: Sequence[Sequence[Any]]) -> tuple[tuple[str, str], ...]:
    values = _bounded_sequence(values, "entry.coordinates", MAX_TENSOR_AXES)
    out = None if type(values) is tuple else []
    previous_axis: str | None = None
    for index, raw in enumerate(values):
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence) or len(raw) != 2:
            raise ValueError(f"entry.coordinates[{index}] must be an (axis, label) pair")
        axis = _identifier(raw[0], f"entry.coordinates[{index}].axis")
        label = _non_empty(raw[1], f"entry.coordinates[{index}].label", max_length=1000)
        if "\x00" in label:
            raise ValueError("entry coordinate labels must not contain NUL bytes")
        pair = (axis, label)
        if out is None:
            if type(raw) is not tuple or (
                previous_axis is not None and axis < previous_axis
            ):
                out = [values[position] for position in range(index)]
            elif previous_axis is not None and axis == previous_axis:
                raise ValueError("entry.coordinates must name every axis at most once")
        if out is not None:
            out.append(pair)
        previous_axis = axis
    if out is None:
        return values  # type: ignore[return-value]
    out.sort()
    for index in range(1, len(out)):
        if out[index - 1][0] == out[index][0]:
            raise ValueError("entry.coordinates must name every axis at most once")
    return tuple(out)


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
        axes = raw_axes if type(raw_axes) is tuple else tuple(raw_axes)
        axes_are_canonical = True
        previous_name: str | None = None
        for axis in axes:
            if not isinstance(axis, TensorAxis):
                raise ValueError("tensor.axes must contain TensorAxis records")
            if previous_name is not None and axis.name < previous_name:
                axes_are_canonical = False
            previous_name = axis.name
        ordered_axes = (
            axes
            if axes_are_canonical
            else tuple(sorted(axes, key=lambda axis: axis.name))
        )
        for index in range(1, len(ordered_axes)):
            if ordered_axes[index - 1].name == ordered_axes[index].name:
                raise ValueError("tensor.axes must have unique names")
        axes = ordered_axes
        object.__setattr__(self, "axes", axes)

        raw_entries = _bounded_sequence(self.entries, "tensor.entries", MAX_TENSOR_ENTRIES)
        entries = raw_entries if type(raw_entries) is tuple else tuple(raw_entries)
        entries_are_canonical = True
        previous_semantic_key: tuple[Any, ...] | None = None
        for entry in entries:
            if not isinstance(entry, SparseTensorEntry):
                raise ValueError("tensor.entries must contain SparseTensorEntry records")
            coordinates = entry.coordinates
            if len(coordinates) != len(axes):
                raise ValueError("every sparse entry must bind exactly the TensorView axes")
            for position in range(len(axes)):
                axis_name, label = coordinates[position]
                axis = axes[position]
                if axis_name != axis.name:
                    raise ValueError("every sparse entry must bind exactly the TensorView axes")
                if _sorted_label_index(axis.labels, label) is None:
                    raise ValueError(f"entry label {label!r} is not declared by axis {axis_name!r}")
            semantic_key = (coordinates, entry.relation)
            if previous_semantic_key is not None:
                if semantic_key < previous_semantic_key:
                    entries_are_canonical = False
                elif entries_are_canonical and semantic_key == previous_semantic_key:
                    raise ValueError("tensor.entries must not repeat a coordinate/relation claim")
            previous_semantic_key = semantic_key

        if entries_are_canonical:
            ordered_entries = entries
        else:
            ordered_entries = tuple(sorted(entries, key=lambda entry: entry.semantic_key))
            for index in range(1, len(ordered_entries)):
                if ordered_entries[index - 1].semantic_key == ordered_entries[index].semantic_key:
                    raise ValueError("tensor.entries must not repeat a coordinate/relation claim")
        object.__setattr__(self, "entries", ordered_entries)
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

    def index_coordinate(self, entry: SparseTensorEntry) -> tuple[int, ...]:
        if not isinstance(entry, SparseTensorEntry):
            raise ValueError("entry is not retained by this TensorView")
        semantic_key = entry.semantic_key
        position = bisect_left(
            self.entries,
            semantic_key,
            key=lambda candidate: candidate.semantic_key,
        )
        if position == len(self.entries) or self.entries[position] != entry:
            raise ValueError("entry is not retained by this TensorView")

        indices: list[int] = []
        for axis_position, (_, label) in enumerate(entry.coordinates):
            label_index = _sorted_label_index(
                self.axes[axis_position].labels,
                label,
            )
            if label_index is None:
                raise ValueError("entry is not retained by this TensorView")
            indices.append(label_index)
        return tuple(indices)

    def select(self, **coordinates: str) -> tuple[SparseTensorEntry, ...]:
        if not coordinates:
            return self.entries

        normalized: dict[int, str] = {}
        for name, raw in coordinates.items():
            position = bisect_left(self.axes, name, key=lambda axis: axis.name)
            if position == len(self.axes) or self.axes[position].name != name:
                raise ValueError(f"unknown tensor axis {name!r}")
            label = _non_empty(raw, f"selector.{name}", max_length=1000)
            if _sorted_label_index(self.axes[position].labels, label) is None:
                raise ValueError(f"selector label {label!r} is not declared by axis {name!r}")
            normalized[position] = label

        prefix_coordinates: list[tuple[str, str]] = []
        while len(prefix_coordinates) in normalized:
            position = len(prefix_coordinates)
            prefix_coordinates.append((self.axes[position].name, normalized.pop(position)))
        if prefix_coordinates:
            prefix = tuple(prefix_coordinates)
            prefix_length = len(prefix)
            lower = bisect_left(
                self.entries,
                prefix,
                key=lambda candidate: candidate.coordinates[:prefix_length],
            )
            upper = bisect_right(
                self.entries,
                prefix,
                key=lambda candidate: candidate.coordinates[:prefix_length],
            )
        else:
            lower = 0
            upper = len(self.entries)

        if prefix_coordinates and not normalized:
            if lower == 0 and upper == len(self.entries):
                return self.entries
            return tuple(self.entries[index] for index in range(lower, upper))

        def matching_entries():
            for index in range(lower, upper):
                entry = self.entries[index]
                if all(
                    entry.coordinates[position][1] == label
                    for position, label in normalized.items()
                ):
                    yield entry

        return tuple(matching_entries())

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
