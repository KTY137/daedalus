"""Minimal evidence-bearing double-category contracts for Fourfold evolution.

Objects are typed boundaries, horizontal arrows are open components, vertical
arrows are boundary migrations, and squares are transformation 2-cells.  These
immutable records are a regenerable semantic projection: they verify no
receipt, schedule no effect, and grant neither promotion nor owner approval.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from ..schemas import _identifier, _non_empty, _revision, _sha256
from ..spine.envelope import canonical_json, canonical_sha
from .contracts import FOURFOLD_PLANES

MAX_BOUNDARY_PORTS = 10_000
MAX_CELL_REFERENCES = 10_000


def _sequence(value: Any, name: str, limit: int) -> Sequence[Any]:
    if isinstance(value, (str, bytes, Mapping)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be a bounded sequence")
    if len(value) > limit:
        raise ValueError(f"{name} exceeds bounded limit {limit}")
    return value


def _digests(values: Any, name: str) -> tuple[str, ...]:
    normalized = tuple(
        _sha256(value, f"{name}[{index}]")
        for index, value in enumerate(_sequence(values, name, MAX_CELL_REFERENCES))
    )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(normalized))


def _claims(values: Any, name: str) -> tuple[str, ...]:
    normalized = tuple(
        _identifier(value, f"{name}[{index}]")
        for index, value in enumerate(_sequence(values, name, MAX_CELL_REFERENCES))
    )
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(normalized))


@dataclass(frozen=True)
class BoundaryPort:
    port_id: str
    plane: str
    contract: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "port_id", _identifier(self.port_id, "port.port_id"))
        if self.plane not in FOURFOLD_PLANES:
            raise ValueError(f"port.plane must be one of {FOURFOLD_PLANES}")
        contract = _non_empty(self.contract, "port.contract", max_length=2_000)
        if "\x00" in contract:
            raise ValueError("port.contract contains a NUL byte")
        object.__setattr__(self, "contract", contract)

    def to_dict(self) -> dict[str, str]:
        return {"port_id": self.port_id, "plane": self.plane, "contract": self.contract}


@dataclass(frozen=True)
class TypedBoundary:
    ports: tuple[BoundaryPort, ...]

    def __post_init__(self) -> None:
        ports = tuple(_sequence(self.ports, "boundary.ports", MAX_BOUNDARY_PORTS))
        if any(not isinstance(port, BoundaryPort) for port in ports):
            raise ValueError("boundary.ports must contain BoundaryPort records")
        if len({port.port_id for port in ports}) != len(ports):
            raise ValueError("boundary port ids must be unique")
        object.__setattr__(self, "ports", tuple(sorted(ports, key=lambda port: port.port_id)))

    @property
    def port_map(self) -> Mapping[str, BoundaryPort]:
        return MappingProxyType({port.port_id: port for port in self.ports})

    def to_dict(self) -> dict[str, Any]:
        return {"ports": [port.to_dict() for port in self.ports]}

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class BoundaryMap:
    source: TypedBoundary
    target: TypedBoundary
    assignments: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, TypedBoundary) or not isinstance(self.target, TypedBoundary):
            raise ValueError("boundary map endpoints must be TypedBoundary records")
        raw = _sequence(self.assignments, "boundary_map.assignments", MAX_BOUNDARY_PORTS)
        assignments: list[tuple[str, str]] = []
        for index, pair in enumerate(raw):
            if (
                isinstance(pair, (str, bytes, Mapping))
                or not isinstance(pair, Sequence)
                or len(pair) != 2
            ):
                raise ValueError(f"boundary_map.assignments[{index}] must be a pair")
            assignments.append(
                (
                    _identifier(pair[0], f"boundary_map.assignments[{index}].source"),
                    _identifier(pair[1], f"boundary_map.assignments[{index}].target"),
                )
            )
        source_ids = [source for source, _ in assignments]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("boundary map source assignments must be unique")
        if set(source_ids) != set(self.source.port_map):
            raise ValueError("boundary map must be total over its source boundary")
        for source_id, target_id in assignments:
            if target_id not in self.target.port_map:
                raise ValueError(f"unknown target port {target_id!r}")
            if self.source.port_map[source_id].plane != self.target.port_map[target_id].plane:
                raise ValueError("boundary maps must preserve Fourfold planes")
        object.__setattr__(self, "assignments", tuple(sorted(assignments)))

    @classmethod
    def identity(cls, boundary: TypedBoundary) -> "BoundaryMap":
        return cls(
            boundary,
            boundary,
            tuple((port.port_id, port.port_id) for port in boundary.ports),
        )

    @property
    def assignment_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.assignments))

    @property
    def is_identity(self) -> bool:
        return self.source == self.target and all(left == right for left, right in self.assignments)

    def then(self, other: "BoundaryMap") -> "BoundaryMap":
        if not isinstance(other, BoundaryMap):
            raise ValueError("other must be BoundaryMap")
        if self.target != other.source:
            raise ValueError("boundary maps require an exactly shared middle boundary")
        right = other.assignment_map
        return BoundaryMap(
            self.source,
            other.target,
            tuple((source, right[target]) for source, target in self.assignments),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "target": self.target.to_dict(),
            "assignments": [list(pair) for pair in self.assignments],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class OpenFourfoldComponent:
    repository_id: str
    source_revision: str
    left: TypedBoundary
    right: TypedBoundary
    component_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "repository_id",
            _identifier(self.repository_id, "component.repository_id"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "component.source_revision"),
        )
        if not isinstance(self.left, TypedBoundary) or not isinstance(self.right, TypedBoundary):
            raise ValueError("component boundaries must be TypedBoundary records")
        factors = tuple(
            _sha256(value, f"component.component_sha256s[{index}]")
            for index, value in enumerate(
                _sequence(
                    self.component_sha256s,
                    "component.component_sha256s",
                    MAX_CELL_REFERENCES,
                )
            )
        )
        if not factors and self.left != self.right:
            raise ValueError("an empty component must have one identity boundary")
        object.__setattr__(self, "component_sha256s", factors)

    @classmethod
    def atomic(
        cls,
        *,
        repository_id: str,
        source_revision: str,
        left: TypedBoundary,
        right: TypedBoundary,
        component_sha256: str,
    ) -> "OpenFourfoldComponent":
        return cls(repository_id, source_revision, left, right, (component_sha256,))

    @classmethod
    def identity(
        cls,
        boundary: TypedBoundary,
        *,
        repository_id: str,
        source_revision: str,
    ) -> "OpenFourfoldComponent":
        return cls(repository_id, source_revision, boundary, boundary, ())

    @property
    def is_identity(self) -> bool:
        return not self.component_sha256s and self.left == self.right

    def then(self, other: "OpenFourfoldComponent") -> "OpenFourfoldComponent":
        if not isinstance(other, OpenFourfoldComponent):
            raise ValueError("other must be OpenFourfoldComponent")
        if self.repository_id != other.repository_id:
            raise ValueError("components cannot cross repositories")
        if self.source_revision != other.source_revision:
            raise ValueError("components cannot cross source revisions")
        if self.right != other.left:
            raise ValueError("components require an exactly shared boundary")
        if self.is_identity:
            return other
        if other.is_identity:
            return self
        return OpenFourfoldComponent(
            self.repository_id,
            self.source_revision,
            self.left,
            other.right,
            self.component_sha256s + other.component_sha256s,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "source_revision": self.source_revision,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
            "component_sha256s": list(self.component_sha256s),
        }

    @property
    def component_sha256(self) -> str:
        return canonical_sha(self.to_dict())

    @property
    def digest(self) -> str:
        return self.component_sha256


class VerificationStatus(str, Enum):
    REJECTED = "rejected"
    PROPOSED = "proposed"
    STRUCTURALLY_CHECKED = "structurally_checked"
    EVALUATOR_VERIFIED = "evaluator_verified"


_STATUS_RANK = {
    VerificationStatus.REJECTED: 0,
    VerificationStatus.PROPOSED: 1,
    VerificationStatus.STRUCTURALLY_CHECKED: 2,
    VerificationStatus.EVALUATOR_VERIFIED: 3,
}


def _conservative_status(left: VerificationStatus, right: VerificationStatus) -> VerificationStatus:
    return left if _STATUS_RANK[left] <= _STATUS_RANK[right] else right


@dataclass(frozen=True)
class Transformation2Cell:
    source: OpenFourfoldComponent
    target: OpenFourfoldComponent
    left_map: BoundaryMap
    right_map: BoundaryMap
    rewrite_sha256s: tuple[str, ...] = ()
    observer_receipts: tuple[str, ...] = ()
    preserved_invariants: tuple[str, ...] = ()
    changed_invariants: tuple[str, ...] = ()
    status: VerificationStatus = VerificationStatus.PROPOSED

    def __post_init__(self) -> None:
        if not isinstance(self.source, OpenFourfoldComponent) or not isinstance(
            self.target, OpenFourfoldComponent
        ):
            raise ValueError("2-cell endpoints must be OpenFourfoldComponent records")
        if not isinstance(self.left_map, BoundaryMap) or not isinstance(
            self.right_map, BoundaryMap
        ):
            raise ValueError("2-cell boundary maps must be BoundaryMap records")
        if self.left_map.source != self.source.left or self.left_map.target != self.target.left:
            raise ValueError("left boundary map does not bind the component boundaries")
        if self.right_map.source != self.source.right or self.right_map.target != self.target.right:
            raise ValueError("right boundary map does not bind the component boundaries")
        if self.source.repository_id != self.target.repository_id:
            raise ValueError("2-cell endpoints must belong to one repository")
        object.__setattr__(
            self,
            "rewrite_sha256s",
            _digests(self.rewrite_sha256s, "cell.rewrite_sha256s"),
        )
        object.__setattr__(
            self,
            "observer_receipts",
            _digests(self.observer_receipts, "cell.observer_receipts"),
        )
        changed = _claims(self.changed_invariants, "cell.changed_invariants")
        preserved = tuple(
            claim
            for claim in _claims(self.preserved_invariants, "cell.preserved_invariants")
            if claim not in set(changed)
        )
        object.__setattr__(self, "changed_invariants", changed)
        object.__setattr__(self, "preserved_invariants", preserved)
        if not isinstance(self.status, VerificationStatus):
            raise ValueError("cell.status must be VerificationStatus")
        if (
            self.status is VerificationStatus.EVALUATOR_VERIFIED
            and not self.observer_receipts
            and not self._is_law_identity()
        ):
            raise ValueError("evaluator_verified 2-cells require observer receipt evidence")

    @classmethod
    def identity(cls, component: OpenFourfoldComponent) -> "Transformation2Cell":
        return cls(
            component,
            component,
            BoundaryMap.identity(component.left),
            BoundaryMap.identity(component.right),
            status=VerificationStatus.EVALUATOR_VERIFIED,
        )

    @classmethod
    def horizontal_identity(
        cls,
        boundary_map: BoundaryMap,
        *,
        repository_id: str,
        source_revision: str,
        target_revision: str,
    ) -> "Transformation2Cell":
        return cls(
            OpenFourfoldComponent.identity(
                boundary_map.source,
                repository_id=repository_id,
                source_revision=source_revision,
            ),
            OpenFourfoldComponent.identity(
                boundary_map.target,
                repository_id=repository_id,
                source_revision=target_revision,
            ),
            boundary_map,
            boundary_map,
            status=VerificationStatus.EVALUATOR_VERIFIED,
        )

    def _is_law_identity(self) -> bool:
        vertical = (
            self.source == self.target
            and self.left_map.is_identity
            and self.right_map.is_identity
        )
        horizontal = (
            self.source.is_identity
            and self.target.is_identity
            and self.left_map == self.right_map
        )
        return (
            (vertical or horizontal)
            and not self.rewrite_sha256s
            and not self.preserved_invariants
            and not self.changed_invariants
        )

    @property
    def is_vertical_identity(self) -> bool:
        return (
            self.source == self.target
            and self.left_map.is_identity
            and self.right_map.is_identity
            and self._is_law_identity()
        )

    def then(self, other: "Transformation2Cell") -> "Transformation2Cell":
        if not isinstance(other, Transformation2Cell):
            raise ValueError("other must be Transformation2Cell")
        if self.target != other.source:
            raise ValueError("vertical 2-cell composition requires an exact middle component")
        if self.is_vertical_identity:
            return other
        if other.is_vertical_identity:
            return self
        return self._composite(
            source=self.source,
            target=other.target,
            left_map=self.left_map.then(other.left_map),
            right_map=self.right_map.then(other.right_map),
            other=other,
        )

    def beside(self, other: "Transformation2Cell") -> "Transformation2Cell":
        if not isinstance(other, Transformation2Cell):
            raise ValueError("other must be Transformation2Cell")
        if self.right_map != other.left_map:
            raise ValueError("horizontal 2-cell composition requires one shared boundary map")
        return self._composite(
            source=self.source.then(other.source),
            target=self.target.then(other.target),
            left_map=self.left_map,
            right_map=other.right_map,
            other=other,
        )

    def _composite(
        self,
        *,
        source: OpenFourfoldComponent,
        target: OpenFourfoldComponent,
        left_map: BoundaryMap,
        right_map: BoundaryMap,
        other: "Transformation2Cell",
    ) -> "Transformation2Cell":
        changed = set(self.changed_invariants) | set(other.changed_invariants)
        preserved = (
            set(self.preserved_invariants) | set(other.preserved_invariants)
        ) - changed
        return Transformation2Cell(
            source,
            target,
            left_map,
            right_map,
            tuple(sorted(set(self.rewrite_sha256s) | set(other.rewrite_sha256s))),
            tuple(sorted(set(self.observer_receipts) | set(other.observer_receipts))),
            tuple(sorted(preserved)),
            tuple(sorted(changed)),
            _conservative_status(self.status, other.status),
        )

    @property
    def source_component_sha256(self) -> str:
        return self.source.component_sha256

    @property
    def target_component_sha256(self) -> str:
        return self.target.component_sha256

    @property
    def left_map_sha256(self) -> str:
        return self.left_map.digest

    @property
    def right_map_sha256(self) -> str:
        return self.right_map.digest

    @property
    def rewrite_sha256(self) -> str:
        return canonical_sha({"rewrite_sha256s": list(self.rewrite_sha256s)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_component_sha256": self.source_component_sha256,
            "target_component_sha256": self.target_component_sha256,
            "source_revision": self.source.source_revision,
            "target_revision": self.target.source_revision,
            "left_map_sha256": self.left_map_sha256,
            "right_map_sha256": self.right_map_sha256,
            "rewrite_sha256s": list(self.rewrite_sha256s),
            "observer_receipts": list(self.observer_receipts),
            "preserved_invariants": list(self.preserved_invariants),
            "changed_invariants": list(self.changed_invariants),
            "status": self.status.value,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


__all__ = [
    "BoundaryMap",
    "BoundaryPort",
    "MAX_BOUNDARY_PORTS",
    "MAX_CELL_REFERENCES",
    "OpenFourfoldComponent",
    "Transformation2Cell",
    "TypedBoundary",
    "VerificationStatus",
]
