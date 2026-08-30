"""Bounded typed tensor view over the canonical Fourfold/Forest subject.

This module is deliberately an internal computational projection, not a fifth
semantic plane, graph authority, store, scheduler, evaluator, or promotion
surface.  Forest/source artifacts and :class:`FourfoldSnapshot` remain the
semantic authority.  A ``TensorView`` only gives algorithms a deterministic,
sparse, named-axis representation of one exact Fourfold/Forest pair.

The contract is intentionally standard-library only.  A later NumPy/PyTorch or
sparse backend must be an adapter over this representation and must demonstrate
a measured benefit plus a replacement path; backend state must never become
candidate identity.
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


def _coordinates(
    values: Sequence[Sequence[Any]], name: str = "entry.coordinates"
) -> tuple[tuple[str, str], ...]:
    """Canonicalize a named sparse coordinate without inventing axis order.

    Coordinates are stored as ``(axis_name, label)`` pairs instead of raw
    integer positions.  This keeps the wire identity stable when callers build
    the same tensor with axes in a different input order.  ``TensorView`` can
    cheaply project the names to integer indices for computational backends.
    """

    if isinstance(values, (str, bytes, Mapping)):
        raise ValueError(f"{name} must be a sequence of (axis, label) pairs")
    converted: list[tuple[str, str]] = []
    seen: set[str] = set()
    for index, raw in enumerate(values):
        if isinstance(raw, (str, bytes, Mapping)) or not isinstance(raw, Sequence):
            raise ValueError(f"{name}[{index}] must be an (axis, label) pair")
        if len(raw) != 2:
            raise ValueError(f"{name}[{index}] must contain exactly axis and label")
        axis = _identifier(raw[0], f"{name}[{index}].axis")
        label = _non_empty(raw[1], f"{name}[{index}].label", max_length=1000)
        if "\x00" in label:
            raise ValueError(f"{name}[{index}].label contains a NUL byte")
        if axis in seen:
            raise ValueError(f"{name} must name every axis at most once")
        seen.add(axis)
        converted.append((axis, label))
    return tuple(sorted(converted))


@dataclass(frozen=True)
class TensorAxis:
    """One named dimension and its canonical finite label vocabulary."""

    name: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "axis.name"))
        labels = _sorted_strings(self.labels, "axis.labels")
        if len(labels) > MAX_AXIS_LABELS:
            raise ValueError(
                f"axis.labels exceeds the bounded limit of {MAX_AXIS_LABELS}"
            )
        if any("\x00" in label for label in labels):
            raise ValueError("axis.labels must not contain NUL bytes")
        object.__setattr__(self, "labels", labels)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "labels": list(self.labels)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TensorAxis":
        return cls(**_record_payload(cls, payload, "tensor axis"))


@dataclass(frozen=True)
class SparseTensorEntry:
    """One sparse typed relation/value at a fully named coordinate.

    ``masked`` is explicit rather than encoded as a magic numeric value.
    Evidence digests remain attached to the derived row; they do not make the
    tensor authoritative over the Fourfold/Forest source.
    """

    coordinates: tuple[tuple[str, str], ...]
    relation: str
    value: float = 1.0
    masked: bool = False
    evidence_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "coordinates", _coordinates(self.coordinates))
        object.__setattr__(
            self, "relation", _identifier(self.relation, "entry.relation")
        )
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise ValueError("entry.value must be a finite number")
        numeric = float(self.value)
        if not math.isfinite(numeric):
            raise ValueError("entry.value must be a finite number")
        object.__setattr__(self, "value", numeric)
        if type(self.masked) is not bool:
            raise ValueError("entry.masked must be boolean")
        object.__setattr__(
            self,
            "evidence_sha256s",
            _sorted_strings(
                self.evidence_sha256s,
                "entry.evidence_sha256s",
                digests=True,
            ),
        )

    @property
    def coordinate_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.coordinates))

    @property
    def semantic_key(self) -> tuple[tuple[tuple[str, str], ...], str]:
        """Coordinate/relation identity independent of value/evidence packaging."""

        return self.coordinates, self.relation

    def to_dict(self) -> dict[str, Any]:
        return {
            "coordinates": [list(item) for item in self.coordinates],
            "relation": self.relation,
            "value": self.value,
            "masked": self.masked,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "SparseTensorEntry":
        return cls(**_record_payload(cls, payload, "sparse tensor entry"))


@dataclass(frozen=True)
class TensorView(CanonicalContract):
    """Immutable sparse computational view of one exact Fourfold/Forest pair.

    Completeness uses the same ``complete`` / ``partial`` / ``absent``
    vocabulary as the Fourfold planes, but this status describes only the
    *projection*.  It cannot change the status of any source plane.
    """

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
        object.__setattr__(
            self, "repository_id", _identifier(self.repository_id, "repository_id")
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "source_forest_sha256",
            _sha256(self.source_forest_sha256, "source_forest_sha256"),
        )
        object.__setattr__(
            self,
            "source_fourfold_sha256",
            _sha256(self.source_fourfold_sha256, "source_fourfold_sha256"),
        )
        if self.status not in TENSOR_STATUSES:
            raise ValueError("tensor.status must be complete, partial, or absent")

        axes = tuple(self.axes)
        if len(axes) > MAX_TENSOR_AXES:
            raise ValueError(f"tensor.axes exceeds the bounded limit of {MAX_TENSOR_AXES}")
        if any(not isinstance(axis, TensorAxis) for axis in axes):
            raise ValueError("tensor.axes must contain TensorAxis records")
        by_name = {axis.name: axis for axis in axes}
        if len(by_name) != len(axes):
            raise ValueError("tensor.axes must have unique names")
        canonical_axes = tuple(by_name[name] for name in sorted(by_name))
        object.__setattr__(self, "axes", canonical_axes)

        entries = tuple(self.entries)
        if len(entries) > MAX_TENSOR_ENTRIES:
            raise ValueError(
                f"tensor.entries exceeds the bounded limit of {MAX_TENSOR_ENTRIES}"
            )
        if any(not isinstance(entry, SparseTensorEntry) for entry in entries):
            raise ValueError("tensor.entries must contain SparseTensorEntry records")

        axis_names = tuple(axis.name for axis in canonical_axes)
        axis_sets = {axis.name: frozenset(axis.labels) for axis in canonical_axes}
        seen: set[tuple[tuple[tuple[str, str], ...], str]] = set()
        for entry in entries:
            coordinates = entry.coordinate_map
            if tuple(sorted(coordinates)) != axis_names:
                raise ValueError(
                    "every sparse entry must bind exactly the TensorView axes"
                )
            for axis_name, label in entry.coordinates:
                if label not in axis_sets[axis_name]:
                    raise ValueError(
                        f"entry label {label!r} is not declared by axis {axis_name!r}"
                    )
            if entry.semantic_key in seen:
                raise ValueError(
                    "tensor.entries must not repeat a coordinate/relation claim"
                )
            seen.add(entry.semantic_key)

        label_index = {
            axis.name: {label: index for index, label in enumerate(axis.labels)}
            for axis in canonical_axes
        }

        def entry_key(entry: SparseTensorEntry) -> tuple[Any, ...]:
            mapping = entry.coordinate_map
            indices = tuple(label_index[name][mapping[name]] for name in axis_names)
            return (
                indices,
                entry.relation,
                entry.masked,
                entry.value,
                entry.evidence_sha256s,
            )

        object.__setattr__(self, "entries", tuple(sorted(entries, key=entry_key)))

        reason = self.reason
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
        else:
            if not self.axes:
                raise ValueError("a complete tensor must contain at least one axis")
            if reason:
                raise ValueError("a complete tensor must not carry an incompleteness reason")

        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("tensor.provenance must be ContractProvenance")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "tensor source_revision must match provenance.source_revision"
            )
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
        """Project one retained named coordinate to deterministic integer indices."""

        if entry not in self.entries:
            raise ValueError("entry is not retained by this TensorView")
        coordinate = entry.coordinate_map
        return tuple(
            axis.labels.index(coordinate[axis.name])
            for axis in self.axes
        )

    def select(self, **coordinates: str) -> tuple[SparseTensorEntry, ...]:
        """Deterministic sparse slice by zero or more named axis labels."""

        normalized: dict[str, str] = {}
        axes = self.axis_map
        for axis_name, raw_label in coordinates.items():
            if axis_name not in axes:
                raise ValueError(f"unknown tensor axis {axis_name!r}")
            label = _non_empty(raw_label, f"selector.{axis_name}", max_length=1000)
            if label not in axes[axis_name].labels:
                raise ValueError(
                    f"selector label {label!r} is not declared by axis {axis_name!r}"
                )
            normalized[axis_name] = label
        return tuple(
            entry
            for entry in self.entries
            if all(entry.coordinate_map[name] == label for name, label in normalized.items())
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TensorView":
        body = cls._contract_payload(payload)
        body["axes"] = tuple(TensorAxis.from_dict(item) for item in body["axes"])
        body["entries"] = tuple(
            SparseTensorEntry.from_dict(item) for item in body["entries"]
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def parse_tensor_view(payload: Mapping[str, Any]) -> TensorView:
    """Strict parser for the internal view; intentionally absent from registries."""

    return TensorView.from_dict(payload)
