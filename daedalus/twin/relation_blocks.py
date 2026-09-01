"""Canonical typed sparse blocks for exact, revision-bound Fourfold queries.

Blocks are regenerable computational projections, never a replacement for the
Forest, FourfoldSnapshot, TensorView, evidence verification, or promotion.
This bounded stdlib CSR implementation is the executable oracle for optional
future sparse backends.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Generic, Iterator, Mapping, Sequence, TypeVar

from ..schemas import _identifier, _non_empty, _revision, _sha256
from ..spine.envelope import canonical_json, canonical_sha
from .contracts import FOURFOLD_PLANES
from .semiring import MAX_NATURAL_BITS, EvidenceValue, Semiring

T = TypeVar("T")
MAX_BLOCK_AXIS_LABELS = 100_000
MAX_BLOCK_ENTRIES = 1_000_000
MAX_REFERENCE_OPERATIONS = 5_000_000


def _sequence(value: Any, name: str, limit: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a bounded sequence")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds bounded limit {limit}")
    return value


def _label(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=2_000)
    if "\x00" in text:
        raise ValueError(f"{name} contains a NUL byte")
    return text


def _stored(value: Any, semiring_name: str) -> Any:
    if semiring_name == "boolean":
        if type(value) is not bool:
            raise ValueError("boolean relation blocks must contain bool values")
        if not value:
            raise ValueError("relation blocks must not store semiring zero values")
        return value
    if semiring_name == "natural":
        if type(value) is not int or value < 0:
            raise ValueError("natural relation blocks must contain non-negative integers")
        if value.bit_length() > MAX_NATURAL_BITS:
            raise ValueError(
                f"natural relation-block values exceed bounded bit length {MAX_NATURAL_BITS}"
            )
        if value == 0:
            raise ValueError("relation blocks must not store semiring zero values")
        return value
    if semiring_name == "tropical":
        if type(value) not in (int, float):
            raise ValueError("tropical relation blocks must contain numeric costs")
        try:
            value = float(value)
        except OverflowError as exc:
            raise ValueError("tropical relation-block costs must be finite") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError("tropical relation-block costs must be finite and non-negative")
        return 0.0 if value == 0.0 else value
    if semiring_name == "evidence-dag":
        if not isinstance(value, EvidenceValue):
            raise ValueError("evidence-dag relation blocks require EvidenceValue values")
        if not value.alternatives:
            raise ValueError("relation blocks must not store semiring zero values")
        return value
    if type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return 0.0 if value == 0.0 else value
    if isinstance(value, EvidenceValue):
        return value
    raise ValueError("relation-block values must be JSON-safe scalar values")


def _json_scalar(value: Any) -> Any:
    if isinstance(value, EvidenceValue):
        return {"scalar_type": "evidence", "value": value.to_dict()}
    if type(value) is float and not math.isfinite(value):
        raise ValueError("stored relation-block floats must be finite")
    if type(value) in (bool, int, float):
        return value
    raise ValueError("unsupported relation-block scalar")


def _operation_limit(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= MAX_REFERENCE_OPERATIONS:
        raise ValueError(
            f"max_operations must be an integer from 0 to {MAX_REFERENCE_OPERATIONS}"
        )
    return value


@dataclass(frozen=True)
class ProjectionSubject:
    repository_id: str
    source_revision: str
    source_fourfold_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _identifier(self.repository_id, "subject.repository_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "subject.source_revision"),
        )
        object.__setattr__(
            self,
            "source_fourfold_sha256",
            _sha256(self.source_fourfold_sha256, "subject.source_fourfold_sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "repository_id": self.repository_id,
            "source_revision": self.source_revision,
            "source_fourfold_sha256": self.source_fourfold_sha256,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class TypedAxis:
    name: str
    plane: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "axis.name"))
        if self.plane not in FOURFOLD_PLANES:
            raise ValueError(f"axis.plane must be one of {FOURFOLD_PLANES}")
        labels = tuple(
            _label(item, f"axis.labels[{index}]")
            for index, item in enumerate(
                _sequence(self.labels, "axis.labels", MAX_BLOCK_AXIS_LABELS)
            )
        )
        if len(labels) != len(set(labels)):
            raise ValueError("axis.labels must not contain duplicates")
        object.__setattr__(self, "labels", tuple(sorted(labels)))

    @property
    def label_index(self) -> Mapping[str, int]:
        return MappingProxyType({label: index for index, label in enumerate(self.labels)})

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "plane": self.plane, "labels": list(self.labels)}

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class RelationSignature:
    source_plane: str
    relation: str
    target_plane: str

    def __post_init__(self) -> None:
        if self.source_plane not in FOURFOLD_PLANES:
            raise ValueError(f"source_plane must be one of {FOURFOLD_PLANES}")
        if self.target_plane not in FOURFOLD_PLANES:
            raise ValueError(f"target_plane must be one of {FOURFOLD_PLANES}")
        object.__setattr__(self, "relation", _identifier(self.relation, "signature.relation"))

    def to_dict(self) -> dict[str, str]:
        return {
            "source_plane": self.source_plane,
            "relation": self.relation,
            "target_plane": self.target_plane,
        }


@dataclass(frozen=True)
class TypedRelationBlock(Generic[T]):
    subject: ProjectionSubject
    signature: RelationSignature
    row_axis: TypedAxis
    column_axis: TypedAxis
    semiring_name: str
    row_offsets: tuple[int, ...]
    column_indices: tuple[int, ...]
    values: tuple[T, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.subject, ProjectionSubject):
            raise ValueError("block.subject must be ProjectionSubject")
        if not isinstance(self.signature, RelationSignature):
            raise ValueError("block.signature must be RelationSignature")
        if not isinstance(self.row_axis, TypedAxis) or not isinstance(self.column_axis, TypedAxis):
            raise ValueError("block axes must be TypedAxis records")
        if self.row_axis.plane != self.signature.source_plane:
            raise ValueError("row axis plane must match signature.source_plane")
        if self.column_axis.plane != self.signature.target_plane:
            raise ValueError("column axis plane must match signature.target_plane")
        object.__setattr__(
            self,
            "semiring_name",
            _identifier(self.semiring_name, "block.semiring_name"),
        )

        offsets = tuple(_sequence(self.row_offsets, "block.row_offsets", MAX_BLOCK_AXIS_LABELS + 1))
        columns = tuple(_sequence(self.column_indices, "block.column_indices", MAX_BLOCK_ENTRIES))
        values = tuple(
            _stored(item, self.semiring_name)
            for item in _sequence(self.values, "block.values", MAX_BLOCK_ENTRIES)
        )
        if any(type(item) is not int for item in offsets):
            raise ValueError("block.row_offsets must contain integers")
        if len(offsets) != len(self.row_axis.labels) + 1 or not offsets or offsets[0] != 0:
            raise ValueError("block.row_offsets must contain every row boundary and start at zero")
        if any(left > right for left, right in zip(offsets, offsets[1:])):
            raise ValueError("block.row_offsets must be monotone")
        if any(type(item) is not int for item in columns):
            raise ValueError("block.column_indices must contain integers")
        if any(not 0 <= item < len(self.column_axis.labels) for item in columns):
            raise ValueError("block.column_indices contains an out-of-range index")
        if len(columns) != len(values) or offsets[-1] != len(values):
            raise ValueError("CSR arrays must terminate at the common entry count")
        for row in range(len(self.row_axis.labels)):
            selected = columns[offsets[row] : offsets[row + 1]]
            if any(left >= right for left, right in zip(selected, selected[1:])):
                raise ValueError("column indices must be strictly increasing inside each row")
        object.__setattr__(self, "row_offsets", offsets)
        object.__setattr__(self, "column_indices", columns)
        object.__setattr__(self, "values", values)

    @classmethod
    def from_coordinates(
        cls,
        *,
        subject: ProjectionSubject,
        signature: RelationSignature,
        row_axis: TypedAxis,
        column_axis: TypedAxis,
        coordinates: Sequence[Sequence[Any]],
        semiring: Semiring[T],
    ) -> "TypedRelationBlock[T]":
        if not isinstance(semiring, Semiring):
            raise ValueError("semiring must implement the Semiring protocol")
        if not isinstance(subject, ProjectionSubject) or not isinstance(
            signature, RelationSignature
        ):
            raise ValueError("subject and signature must use typed contract records")
        if not isinstance(row_axis, TypedAxis) or not isinstance(column_axis, TypedAxis):
            raise ValueError("row_axis and column_axis must be TypedAxis records")
        rows, columns = row_axis.label_index, column_axis.label_index
        entries: dict[tuple[int, int], T] = {}
        for index, raw in enumerate(
            _sequence(coordinates, "block.coordinates", MAX_BLOCK_ENTRIES)
        ):
            if (
                isinstance(raw, (str, bytes, Mapping))
                or not isinstance(raw, Sequence)
                or len(raw) != 3
            ):
                raise ValueError(f"block.coordinates[{index}] must be (row, column, value)")
            row = _label(raw[0], f"block.coordinates[{index}].row")
            column = _label(raw[1], f"block.coordinates[{index}].column")
            if row not in rows:
                raise ValueError(f"unknown row label {row!r}")
            if column not in columns:
                raise ValueError(f"unknown column label {column!r}")
            key = (rows[row], columns[column])
            value = semiring.add(entries.get(key, semiring.zero), raw[2])
            if value == semiring.zero:
                entries.pop(key, None)
            else:
                entries[key] = value
        return cls._from_indexed(
            subject, signature, row_axis, column_axis, entries, semiring
        )

    @classmethod
    def _from_indexed(
        cls,
        subject: ProjectionSubject,
        signature: RelationSignature,
        row_axis: TypedAxis,
        column_axis: TypedAxis,
        entries: Mapping[tuple[int, int], T],
        semiring: Semiring[T],
    ) -> "TypedRelationBlock[T]":
        if len(entries) > MAX_BLOCK_ENTRIES:
            raise ValueError(f"block entries exceed bounded limit {MAX_BLOCK_ENTRIES}")
        ordered = sorted(entries.items())
        offsets, indices, values, cursor = [0], [], [], 0
        for row in range(len(row_axis.labels)):
            while cursor < len(ordered) and ordered[cursor][0][0] == row:
                (_, column), value = ordered[cursor]
                indices.append(column)
                values.append(value)
                cursor += 1
            offsets.append(len(values))
        return cls(
            subject,
            signature,
            row_axis,
            column_axis,
            semiring.name,
            tuple(offsets),
            tuple(indices),
            tuple(values),
        )

    @property
    def entry_count(self) -> int:
        return len(self.values)

    def iter_entries(self) -> Iterator[tuple[str, str, T]]:
        for row, row_label in enumerate(self.row_axis.labels):
            for position in range(self.row_offsets[row], self.row_offsets[row + 1]):
                yield (
                    row_label,
                    self.column_axis.labels[self.column_indices[position]],
                    self.values[position],
                )

    def get(self, row_label: str, column_label: str, semiring: Semiring[T]) -> T:
        self._require_semiring(semiring)
        row, column = _label(row_label, "row_label"), _label(column_label, "column_label")
        rows, columns = self.row_axis.label_index, self.column_axis.label_index
        if row not in rows:
            raise ValueError(f"unknown row label {row!r}")
        if column not in columns:
            raise ValueError(f"unknown column label {column!r}")
        target = columns[column]
        start, stop = self.row_offsets[rows[row]], self.row_offsets[rows[row] + 1]
        for position in range(start, stop):
            current = self.column_indices[position]
            if current == target:
                return self.values[position]
            if current > target:
                break
        return semiring.zero

    def matmul(
        self,
        other: "TypedRelationBlock[T]",
        semiring: Semiring[T],
        *,
        relation: str,
        max_operations: int = MAX_REFERENCE_OPERATIONS,
    ) -> "TypedRelationBlock[T]":
        self._require_compatible(other, semiring)
        if self.column_axis != other.row_axis:
            raise ValueError("matrix composition requires an exactly shared typed middle axis")
        limit, operations = _operation_limit(max_operations), 0
        right_rows = [
            tuple(
                (other.column_indices[position], other.values[position])
                for position in range(other.row_offsets[row], other.row_offsets[row + 1])
            )
            for row in range(len(other.row_axis.labels))
        ]
        result: dict[tuple[int, int], T] = {}
        for row in range(len(self.row_axis.labels)):
            for position in range(self.row_offsets[row], self.row_offsets[row + 1]):
                for column, right_value in right_rows[self.column_indices[position]]:
                    operations += 1
                    if operations > limit:
                        raise ValueError("reference contraction exceeds bounded operation limit")
                    key = (row, column)
                    value = semiring.add(
                        result.get(key, semiring.zero),
                        semiring.multiply(self.values[position], right_value),
                    )
                    if value == semiring.zero:
                        result.pop(key, None)
                    else:
                        result[key] = value
        return self._derived(
            RelationSignature(self.signature.source_plane, relation, other.signature.target_plane),
            self.row_axis,
            other.column_axis,
            result,
            semiring,
        )

    def hadamard(
        self,
        other: "TypedRelationBlock[T]",
        semiring: Semiring[T],
        *,
        relation: str,
        max_operations: int = MAX_REFERENCE_OPERATIONS,
    ) -> "TypedRelationBlock[T]":
        self._require_compatible(other, semiring)
        if self.row_axis != other.row_axis or self.column_axis != other.column_axis:
            raise ValueError("Hadamard composition requires identical typed axes")
        limit = _operation_limit(max_operations)
        left = {(row, column): value for row, column, value in self._indexed_entries()}
        right = {(row, column): value for row, column, value in other._indexed_entries()}
        result: dict[tuple[int, int], T] = {}
        for count, key in enumerate(sorted(left.keys() & right.keys()), 1):
            if count > limit:
                raise ValueError("reference contraction exceeds bounded operation limit")
            value = semiring.multiply(left[key], right[key])
            if value != semiring.zero:
                result[key] = value
        return self._derived(
            RelationSignature(self.signature.source_plane, relation, self.signature.target_plane),
            self.row_axis,
            self.column_axis,
            result,
            semiring,
        )

    def _indexed_entries(self) -> Iterator[tuple[int, int, T]]:
        for row in range(len(self.row_axis.labels)):
            for position in range(self.row_offsets[row], self.row_offsets[row + 1]):
                yield row, self.column_indices[position], self.values[position]

    def _derived(
        self,
        signature: RelationSignature,
        row_axis: TypedAxis,
        column_axis: TypedAxis,
        entries: Mapping[tuple[int, int], T],
        semiring: Semiring[T],
    ) -> "TypedRelationBlock[T]":
        return type(self)._from_indexed(
            self.subject, signature, row_axis, column_axis, entries, semiring
        )

    def _require_semiring(self, semiring: Semiring[T]) -> None:
        if not isinstance(semiring, Semiring):
            raise ValueError("semiring must implement the Semiring protocol")
        if semiring.name != self.semiring_name:
            raise ValueError(f"block uses semiring {self.semiring_name!r}, not {semiring.name!r}")

    def _require_compatible(self, other: "TypedRelationBlock[T]", semiring: Semiring[T]) -> None:
        if not isinstance(other, TypedRelationBlock):
            raise ValueError("other must be TypedRelationBlock")
        self._require_semiring(semiring)
        other._require_semiring(semiring)
        if self.subject != other.subject:
            raise ValueError("relation blocks must bind the same exact Fourfold subject")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject.to_dict(),
            "signature": self.signature.to_dict(),
            "row_axis": self.row_axis.to_dict(),
            "column_axis": self.column_axis.to_dict(),
            "semiring_name": self.semiring_name,
            "row_offsets": list(self.row_offsets),
            "column_indices": list(self.column_indices),
            "values": [_json_scalar(value) for value in self.values],
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


__all__ = [
    "MAX_BLOCK_AXIS_LABELS",
    "MAX_BLOCK_ENTRIES",
    "MAX_REFERENCE_OPERATIONS",
    "ProjectionSubject",
    "RelationSignature",
    "TypedAxis",
    "TypedRelationBlock",
]
