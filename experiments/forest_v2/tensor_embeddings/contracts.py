"""Strict, content-addressed contracts for the tensor-embedding experiment.

This module is deliberately pure stdlib and inert: it performs no filesystem,
network, subprocess, or production-store operation.  The objects below are
regenerable experiment projections.  Their identifiers bind representation
bytes; they do not confer evidentiary authority.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from fractions import Fraction
from typing import Mapping, Sequence, Tuple, TypeAlias


PLANES: Tuple[str, ...] = ("code", "type", "data", "knowledge")
ROLES: Tuple[str, ...] = ("path", "symbol", "content", "neighbor")
NORMALIZATION = "global_l2"

SPEC_SCHEMA = "forest-v2.tensor-spec/1"
KERNEL_SCHEMA = "forest-v2.separable-kernel/1"
CP_SCHEMA = "forest-v2.cp-tensor/1"
DENSE_SCHEMA = "forest-v2.dense-tensor/1"
TT_SCHEMA = "forest-v2.tensor-train/1"


class ContractError(ValueError):
    """A serialized or in-memory experiment contract is malformed."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the experiment's one canonical JSON encoding.

    All contract constructors reject non-finite numbers before this function
    is reached.  ``allow_nan=False`` is retained as a fail-closed backstop.
    """

    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise ContractError(f"value is not canonical-JSON serializable: {exc}") from exc
    try:
        return text.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContractError("value contains an invalid Unicode surrogate") from exc


def canonical_digest(value: object, *, domain: str) -> str:
    """Domain-separated SHA-256 of canonical JSON bytes."""

    if type(domain) is not str or not domain:
        raise ContractError("digest domain must be a non-empty string")
    digest = hashlib.sha256()
    try:
        domain_bytes = domain.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise ContractError("digest domain contains an invalid Unicode surrogate") from exc
    digest.update(domain_bytes)
    digest.update(b"\x00")
    digest.update(canonical_json_bytes(value))
    return digest.hexdigest()


def _strict_json_loads(raw: bytes | str) -> object:
    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ContractError("serialized contract is not UTF-8") from exc
    elif type(raw) is str:
        text = raw
    else:
        raise ContractError("serialized contract must be bytes or str")

    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ContractError(f"duplicate JSON key: {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ContractError(f"non-finite JSON number is forbidden: {value}")

    try:
        return json.loads(
            text,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except ContractError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ContractError(f"invalid serialized contract: {exc}") from exc


def _object_with_keys(
    value: object, expected: frozenset[str], *, label: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ContractError(f"{label} must be an object")
    if any(type(key) is not str for key in value):
        raise ContractError(f"{label} keys must be strings")
    actual = frozenset(value.keys())
    unknown = actual - expected
    missing = expected - actual
    if unknown:
        raise ContractError(f"{label} has unknown keys: {sorted(unknown)!r}")
    if missing:
        raise ContractError(f"{label} is missing keys: {sorted(missing)!r}")
    return value


def _as_float(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{label} must be a real number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{label} must be finite")
    # One canonical representation for the two IEEE zero spellings.
    return 0.0 if result == 0.0 else result


def _as_vector(
    value: object, *, label: str, expected_length: int | None = None
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{label} must be a one-dimensional sequence")
    result = tuple(_as_float(item, label=f"{label}[{index}]") for index, item in enumerate(value))
    if not result:
        raise ContractError(f"{label} must not be empty")
    if expected_length is not None and len(result) != expected_length:
        raise ContractError(
            f"{label} has length {len(result)}; expected {expected_length}"
        )
    return result


def _as_matrix(
    value: object,
    *,
    label: str,
    expected_rows: int | None = None,
    expected_columns: int | None = None,
) -> tuple[tuple[float, ...], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{label} must be a two-dimensional sequence")
    rows = tuple(
        _as_vector(row, label=f"{label}[{index}]", expected_length=expected_columns)
        for index, row in enumerate(value)
    )
    if not rows:
        raise ContractError(f"{label} must not be empty")
    width = len(rows[0])
    if any(len(row) != width for row in rows):
        raise ContractError(f"{label} must be rectangular")
    if expected_rows is not None and len(rows) != expected_rows:
        raise ContractError(
            f"{label} has {len(rows)} rows; expected {expected_rows}"
        )
    return rows


def _as_dense_values(
    value: object, shape: tuple[int, int, int], *, label: str = "values"
) -> tuple[tuple[tuple[float, ...], ...], ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ContractError(f"{label} must be a rank-3 sequence")
    if len(value) != shape[0]:
        raise ContractError(f"{label} plane dimension is {len(value)}; expected {shape[0]}")
    planes: list[tuple[tuple[float, ...], ...]] = []
    for plane_index, plane in enumerate(value):
        if isinstance(plane, (str, bytes)) or not isinstance(plane, Sequence):
            raise ContractError(f"{label}[{plane_index}] must be a rank-2 sequence")
        if len(plane) != shape[1]:
            raise ContractError(
                f"{label}[{plane_index}] role dimension is {len(plane)}; expected {shape[1]}"
            )
        roles = tuple(
            _as_vector(
                fiber,
                label=f"{label}[{plane_index}][{role_index}]",
                expected_length=shape[2],
            )
            for role_index, fiber in enumerate(plane)
        )
        planes.append(roles)
    return tuple(planes)


def _as_core(value: object, *, label: str) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Coerce one standard TT core with shape ``left x mode x right``."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ContractError(f"{label} must be a non-empty rank-3 sequence")
    left_rows: list[tuple[tuple[float, ...], ...]] = []
    mode_size: int | None = None
    right_size: int | None = None
    for left_index, modes in enumerate(value):
        if isinstance(modes, (str, bytes)) or not isinstance(modes, Sequence) or not modes:
            raise ContractError(f"{label}[{left_index}] must be a non-empty rank-2 sequence")
        converted = tuple(
            _as_vector(fiber, label=f"{label}[{left_index}][{mode_index}]")
            for mode_index, fiber in enumerate(modes)
        )
        if mode_size is None:
            mode_size = len(converted)
            right_size = len(converted[0])
        if len(converted) != mode_size or any(len(row) != right_size for row in converted):
            raise ContractError(f"{label} must be rectangular in all three dimensions")
        left_rows.append(converted)
    return tuple(left_rows)


@dataclass(frozen=True)
class TensorSpec:
    """Frozen axis and feature identity for one tensor coordinate system."""

    planes: tuple[str, ...]
    roles: tuple[str, ...]
    feature_dimension: int
    seed: int
    normalization: str = NORMALIZATION
    spec_id: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.planes, (str, bytes)) or not isinstance(self.planes, Sequence):
            raise ContractError("planes must be a sequence of strings")
        if isinstance(self.roles, (str, bytes)) or not isinstance(self.roles, Sequence):
            raise ContractError("roles must be a sequence of strings")
        planes = tuple(self.planes)
        roles = tuple(self.roles)
        if any(type(label) is not str or not label or label.strip() != label for label in planes):
            raise ContractError("planes must contain non-empty, whitespace-trimmed strings")
        if any(type(label) is not str or not label or label.strip() != label for label in roles):
            raise ContractError("roles must contain non-empty, whitespace-trimmed strings")
        if planes != PLANES:
            raise ContractError(f"planes must be exactly {PLANES!r}")
        if roles != ROLES:
            raise ContractError(f"roles must be exactly {ROLES!r}")
        if isinstance(self.feature_dimension, bool) or type(self.feature_dimension) is not int:
            raise ContractError("feature_dimension must be an integer")
        if self.feature_dimension <= 0:
            raise ContractError("feature_dimension must be positive")
        if isinstance(self.seed, bool) or type(self.seed) is not int:
            raise ContractError("seed must be an integer")
        if self.seed < 0:
            raise ContractError("seed must be non-negative")
        if self.normalization != NORMALIZATION:
            raise ContractError(f"normalization must be {NORMALIZATION!r}")
        object.__setattr__(self, "planes", planes)
        object.__setattr__(self, "roles", roles)
        expected = self._computed_id()
        if type(self.spec_id) is not str:
            raise ContractError("spec_id must be a string")
        if self.spec_id:
            if self.spec_id != expected:
                raise ContractError("spec_id does not match the TensorSpec payload")
        else:
            object.__setattr__(self, "spec_id", expected)

    @property
    def shape(self) -> tuple[int, int, int]:
        return (len(self.planes), len(self.roles), self.feature_dimension)

    @property
    def dense_scalar_count(self) -> int:
        plane_count, role_count, feature_count = self.shape
        return plane_count * role_count * feature_count

    @property
    def digest(self) -> str:
        return self.spec_id

    @classmethod
    def frozen(cls, *, seed: int, feature_dimension: int = 32) -> "TensorSpec":
        return cls(PLANES, ROLES, feature_dimension, seed, NORMALIZATION)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": SPEC_SCHEMA,
            "planes": list(self.planes),
            "roles": list(self.roles),
            "feature_dimension": self.feature_dimension,
            "seed": self.seed,
            "normalization": self.normalization,
        }

    def _computed_id(self) -> str:
        return "tspec:" + canonical_digest(self._payload(), domain=SPEC_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "spec_id": self.spec_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object) -> "TensorSpec":
        data = _object_with_keys(
            value,
            frozenset(
                {
                    "schema",
                    "planes",
                    "roles",
                    "feature_dimension",
                    "seed",
                    "normalization",
                    "spec_id",
                }
            ),
            label="TensorSpec",
        )
        if data["schema"] != SPEC_SCHEMA:
            raise ContractError(f"unsupported TensorSpec schema: {data['schema']!r}")
        planes = data["planes"]
        roles = data["roles"]
        if not isinstance(planes, list) or not isinstance(roles, list):
            raise ContractError("serialized planes and roles must be JSON arrays")
        return cls(
            planes=tuple(planes),
            roles=tuple(roles),
            feature_dimension=data["feature_dimension"],  # type: ignore[arg-type]
            seed=data["seed"],  # type: ignore[arg-type]
            normalization=data["normalization"],  # type: ignore[arg-type]
            spec_id=data["spec_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str) -> "TensorSpec":
        return cls.from_dict(_strict_json_loads(raw))


Matrix: TypeAlias = tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class SeparableKernel:
    """Plane and role matrices bound to exactly one :class:`TensorSpec`."""

    spec: TensorSpec
    plane_matrix: Matrix
    role_matrix: Matrix
    kernel_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise ContractError("kernel spec must be a TensorSpec")
        plane_matrix = _as_matrix(
            self.plane_matrix,
            label="plane_matrix",
            expected_rows=len(self.spec.planes),
            expected_columns=len(self.spec.planes),
        )
        role_matrix = _as_matrix(
            self.role_matrix,
            label="role_matrix",
            expected_rows=len(self.spec.roles),
            expected_columns=len(self.spec.roles),
        )
        object.__setattr__(self, "plane_matrix", plane_matrix)
        object.__setattr__(self, "role_matrix", role_matrix)
        expected = self._computed_id()
        if type(self.kernel_id) is not str:
            raise ContractError("kernel_id must be a string")
        if self.kernel_id:
            if self.kernel_id != expected:
                raise ContractError("kernel_id does not match the SeparableKernel payload")
        else:
            object.__setattr__(self, "kernel_id", expected)

    @property
    def spec_id(self) -> str:
        return self.spec.spec_id

    @property
    def digest(self) -> str:
        return self.kernel_id

    @classmethod
    def identity(cls, spec: TensorSpec) -> "SeparableKernel":
        plane = tuple(
            tuple(1.0 if row == column else 0.0 for column in range(len(spec.planes)))
            for row in range(len(spec.planes))
        )
        role = tuple(
            tuple(1.0 if row == column else 0.0 for column in range(len(spec.roles)))
            for row in range(len(spec.roles))
        )
        return cls(spec=spec, plane_matrix=plane, role_matrix=role)

    def is_identity(self) -> bool:
        return self == SeparableKernel.identity(self.spec)

    def _payload(self) -> dict[str, object]:
        return {
            "schema": KERNEL_SCHEMA,
            "spec_id": self.spec.spec_id,
            "plane_matrix": [list(row) for row in self.plane_matrix],
            "role_matrix": [list(row) for row in self.role_matrix],
        }

    def _computed_id(self) -> str:
        return "kernel:" + canonical_digest(self._payload(), domain=KERNEL_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "kernel_id": self.kernel_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object, spec: TensorSpec) -> "SeparableKernel":
        data = _object_with_keys(
            value,
            frozenset({"schema", "spec_id", "plane_matrix", "role_matrix", "kernel_id"}),
            label="SeparableKernel",
        )
        if data["schema"] != KERNEL_SCHEMA:
            raise ContractError(f"unsupported SeparableKernel schema: {data['schema']!r}")
        if data["spec_id"] != spec.spec_id:
            raise ContractError("SeparableKernel spec_id does not match the supplied TensorSpec")
        return cls(
            spec=spec,
            plane_matrix=data["plane_matrix"],  # type: ignore[arg-type]
            role_matrix=data["role_matrix"],  # type: ignore[arg-type]
            kernel_id=data["kernel_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str, spec: TensorSpec) -> "SeparableKernel":
        return cls.from_dict(_strict_json_loads(raw), spec)


@dataclass(frozen=True)
class CPTerm:
    """One weighted rank-one ``plane x role x feature`` factorization term."""

    weight: float
    plane: tuple[float, ...]
    role: tuple[float, ...]
    feature: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "weight", _as_float(self.weight, label="weight"))
        object.__setattr__(self, "plane", _as_vector(self.plane, label="plane"))
        object.__setattr__(self, "role", _as_vector(self.role, label="role"))
        object.__setattr__(self, "feature", _as_vector(self.feature, label="feature"))

    @property
    def plane_factor(self) -> tuple[float, ...]:
        return self.plane

    @property
    def role_factor(self) -> tuple[float, ...]:
        return self.role

    @property
    def feature_factor(self) -> tuple[float, ...]:
        return self.feature

    def to_dict(self) -> dict[str, object]:
        return {
            "weight": self.weight,
            "plane": list(self.plane),
            "role": list(self.role),
            "feature": list(self.feature),
        }

    @classmethod
    def from_dict(cls, value: object) -> "CPTerm":
        data = _object_with_keys(
            value,
            frozenset({"weight", "plane", "role", "feature"}),
            label="CPTerm",
        )
        return cls(
            weight=data["weight"],  # type: ignore[arg-type]
            plane=data["plane"],  # type: ignore[arg-type]
            role=data["role"],  # type: ignore[arg-type]
            feature=data["feature"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CPTensor:
    """Exact CP representation in one tensor coordinate system."""

    spec: TensorSpec
    terms: tuple[CPTerm, ...]
    tensor_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise ContractError("CP tensor spec must be a TensorSpec")
        if isinstance(self.terms, (str, bytes)) or not isinstance(self.terms, Sequence):
            raise ContractError("CP terms must be a sequence")
        terms = tuple(self.terms)
        for index, term in enumerate(terms):
            if not isinstance(term, CPTerm):
                raise ContractError(f"terms[{index}] must be a CPTerm")
            if len(term.plane) != len(self.spec.planes):
                raise ContractError(f"terms[{index}].plane has the wrong shape for the TensorSpec")
            if len(term.role) != len(self.spec.roles):
                raise ContractError(f"terms[{index}].role has the wrong shape for the TensorSpec")
            if len(term.feature) != self.spec.feature_dimension:
                raise ContractError(f"terms[{index}].feature has the wrong shape for the TensorSpec")
        object.__setattr__(self, "terms", terms)
        expected = self._computed_id()
        if type(self.tensor_id) is not str:
            raise ContractError("tensor_id must be a string")
        if self.tensor_id:
            if self.tensor_id != expected:
                raise ContractError("tensor_id does not match the CPTensor payload")
        else:
            object.__setattr__(self, "tensor_id", expected)

    @property
    def spec_id(self) -> str:
        return self.spec.spec_id

    @property
    def rank(self) -> int:
        return len(self.terms)

    @property
    def digest(self) -> str:
        return self.tensor_id

    def _payload(self) -> dict[str, object]:
        return {
            "schema": CP_SCHEMA,
            "spec_id": self.spec.spec_id,
            "terms": [term.to_dict() for term in self.terms],
        }

    def _computed_id(self) -> str:
        return "cp:" + canonical_digest(self._payload(), domain=CP_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "tensor_id": self.tensor_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object, spec: TensorSpec) -> "CPTensor":
        data = _object_with_keys(
            value,
            frozenset({"schema", "spec_id", "terms", "tensor_id"}),
            label="CPTensor",
        )
        if data["schema"] != CP_SCHEMA:
            raise ContractError(f"unsupported CPTensor schema: {data['schema']!r}")
        if data["spec_id"] != spec.spec_id:
            raise ContractError("CPTensor spec_id does not match the supplied TensorSpec")
        terms = data["terms"]
        if not isinstance(terms, list):
            raise ContractError("serialized CP terms must be a JSON array")
        return cls(
            spec=spec,
            terms=tuple(CPTerm.from_dict(term) for term in terms),
            tensor_id=data["tensor_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str, spec: TensorSpec) -> "CPTensor":
        return cls.from_dict(_strict_json_loads(raw), spec)

    def to_dense(self) -> "DenseTensor":
        from .algebra import cp_to_dense

        return cp_to_dense(self)

    def to_tensor_train(self) -> "TensorTrain":
        return TensorTrain.from_cp(self)


DenseValues: TypeAlias = tuple[tuple[tuple[float, ...], ...], ...]


@dataclass(frozen=True)
class DenseTensor:
    """A strict rank-three dense tensor with explicit coordinate identity."""

    spec: TensorSpec
    values: DenseValues
    tensor_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise ContractError("dense tensor spec must be a TensorSpec")
        values = _as_dense_values(self.values, self.spec.shape)
        object.__setattr__(self, "values", values)
        expected = self._computed_id()
        if type(self.tensor_id) is not str:
            raise ContractError("tensor_id must be a string")
        if self.tensor_id:
            if self.tensor_id != expected:
                raise ContractError("tensor_id does not match the DenseTensor payload")
        else:
            object.__setattr__(self, "tensor_id", expected)

    @property
    def spec_id(self) -> str:
        return self.spec.spec_id

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.spec.shape

    @property
    def flat_values(self) -> tuple[float, ...]:
        return tuple(value for plane in self.values for role in plane for value in role)

    @property
    def digest(self) -> str:
        return self.tensor_id

    @classmethod
    def from_flat(cls, spec: TensorSpec, values: Sequence[float]) -> "DenseTensor":
        flat = _as_vector(values, label="flat_values", expected_length=spec.dense_scalar_count)
        cursor = 0
        planes: list[tuple[tuple[float, ...], ...]] = []
        for _ in spec.planes:
            roles: list[tuple[float, ...]] = []
            for _ in spec.roles:
                end = cursor + spec.feature_dimension
                roles.append(flat[cursor:end])
                cursor = end
            planes.append(tuple(roles))
        return cls(spec=spec, values=tuple(planes))

    @classmethod
    def from_cp(cls, tensor: CPTensor) -> "DenseTensor":
        return tensor.to_dense()

    def _payload(self) -> dict[str, object]:
        return {
            "schema": DENSE_SCHEMA,
            "spec_id": self.spec.spec_id,
            "values": [[list(fiber) for fiber in plane] for plane in self.values],
        }

    def _computed_id(self) -> str:
        return "dense:" + canonical_digest(self._payload(), domain=DENSE_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "tensor_id": self.tensor_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object, spec: TensorSpec) -> "DenseTensor":
        data = _object_with_keys(
            value,
            frozenset({"schema", "spec_id", "values", "tensor_id"}),
            label="DenseTensor",
        )
        if data["schema"] != DENSE_SCHEMA:
            raise ContractError(f"unsupported DenseTensor schema: {data['schema']!r}")
        if data["spec_id"] != spec.spec_id:
            raise ContractError("DenseTensor spec_id does not match the supplied TensorSpec")
        return cls(
            spec=spec,
            values=data["values"],  # type: ignore[arg-type]
            tensor_id=data["tensor_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str, spec: TensorSpec) -> "DenseTensor":
        return cls.from_dict(_strict_json_loads(raw), spec)


TTCore: TypeAlias = tuple[tuple[tuple[float, ...], ...], ...]


@dataclass(frozen=True)
class TensorTrain:
    """Order-three Tensor Train using standard ``left x mode x right`` cores."""

    spec: TensorSpec
    cores: tuple[TTCore, TTCore, TTCore]
    tensor_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.spec, TensorSpec):
            raise ContractError("TensorTrain spec must be a TensorSpec")
        if isinstance(self.cores, (str, bytes)) or not isinstance(self.cores, Sequence):
            raise ContractError("TensorTrain cores must be a sequence")
        if len(self.cores) != 3:
            raise ContractError("TensorTrain must contain exactly three cores")
        cores = tuple(
            _as_core(core, label=f"cores[{index}]") for index, core in enumerate(self.cores)
        )
        shape0 = (len(cores[0]), len(cores[0][0]), len(cores[0][0][0]))
        shape1 = (len(cores[1]), len(cores[1][0]), len(cores[1][0][0]))
        shape2 = (len(cores[2]), len(cores[2][0]), len(cores[2][0][0]))
        if shape0[0] != 1 or shape0[1] != len(self.spec.planes):
            raise ContractError(
                f"first TT core shape {shape0!r} must be (1, {len(self.spec.planes)}, r1)"
            )
        if shape1[0] != shape0[2] or shape1[1] != len(self.spec.roles):
            raise ContractError(
                f"middle TT core shape {shape1!r} must be ({shape0[2]}, {len(self.spec.roles)}, r2)"
            )
        if shape2[0] != shape1[2] or shape2[1] != self.spec.feature_dimension or shape2[2] != 1:
            raise ContractError(
                "final TT core shape "
                f"{shape2!r} must be ({shape1[2]}, {self.spec.feature_dimension}, 1)"
            )
        object.__setattr__(self, "cores", cores)
        expected = self._computed_id()
        if type(self.tensor_id) is not str:
            raise ContractError("tensor_id must be a string")
        if self.tensor_id:
            if self.tensor_id != expected:
                raise ContractError("tensor_id does not match the TensorTrain payload")
        else:
            object.__setattr__(self, "tensor_id", expected)

    @property
    def spec_id(self) -> str:
        return self.spec.spec_id

    @property
    def ranks(self) -> tuple[int, int]:
        return (len(self.cores[0][0][0]), len(self.cores[1][0][0]))

    @property
    def core_shapes(self) -> tuple[tuple[int, int, int], ...]:
        return tuple((len(core), len(core[0]), len(core[0][0])) for core in self.cores)

    @property
    def digest(self) -> str:
        return self.tensor_id

    @classmethod
    def from_cp(cls, tensor: CPTensor) -> "TensorTrain":
        if not isinstance(tensor, CPTensor):
            raise ContractError("TensorTrain.from_cp expects a CPTensor")
        terms = tensor.terms
        rank = len(terms)
        if rank == 0:
            first: TTCore = (
                tuple((0.0,) for _ in tensor.spec.planes),
            )
            middle: TTCore = (
                tuple((1.0,) for _ in tensor.spec.roles),
            )
            final: TTCore = (
                tuple((1.0,) for _ in range(tensor.spec.feature_dimension)),
            )
            return cls(spec=tensor.spec, cores=(first, middle, final))

        first = (
            tuple(
                tuple(term.weight * term.plane[plane_index] for term in terms)
                for plane_index in range(len(tensor.spec.planes))
            ),
        )
        if any(
            not math.isfinite(value)
            for slab in first
            for row in slab
            for value in row
        ):
            return cls._from_cp_exact_dense(tensor)
        middle = tuple(
            tuple(
                tuple(
                    terms[left].role[role_index] if left == right else 0.0
                    for right in range(rank)
                )
                for role_index in range(len(tensor.spec.roles))
            )
            for left in range(rank)
        )
        final = tuple(
            tuple((terms[left].feature[feature_index],) for feature_index in range(tensor.spec.feature_dimension))
            for left in range(rank)
        )
        candidate = cls(spec=tensor.spec, cores=(first, middle, final))

        # A finite ``weight * plane`` is not sufficient evidence that this
        # factor placement is exact: it may already have rounded a cancellation
        # residual, or it may have underflowed before a later role/feature
        # factor amplifies the path.  Compare both representations through the
        # exact-rational materializers and route through the deterministic
        # dense TT when any binary64 coordinate differs.
        if candidate.to_dense().flat_values != tensor.to_dense().flat_values:
            return cls._from_cp_exact_dense(tensor)
        return candidate

    @classmethod
    def _from_cp_exact_dense(cls, tensor: CPTensor) -> "TensorTrain":
        """Fallback through exact coordinates when ``weight * plane`` overflows.

        A CP term has four finite multiplicative factors whereas one TT path
        has three.  Multiplying the weight into the first core can therefore
        overflow even when cancellation leaves a perfectly representable
        tensor.  Exact rational accumulation resolves that cancellation first;
        a deterministic identity-routing TT then stores each finite dense
        coordinate without another large intermediate product.
        """

        plane_count, role_count, feature_count = tensor.spec.shape
        dense: list[list[list[float]]] = []
        for plane in range(plane_count):
            role_values: list[list[float]] = []
            for role in range(role_count):
                feature_values: list[float] = []
                for feature in range(feature_count):
                    exact = sum(
                        (
                            Fraction.from_float(term.weight)
                            * Fraction.from_float(term.plane[plane])
                            * Fraction.from_float(term.role[role])
                            * Fraction.from_float(term.feature[feature])
                            for term in tensor.terms
                        ),
                        Fraction(0),
                    )
                    try:
                        value = float(exact)
                    except OverflowError as exc:
                        raise ContractError(
                            "exact CP-to-TT value exceeds float64"
                        ) from exc
                    if not math.isfinite(value):
                        raise ContractError("exact CP-to-TT value exceeds float64")
                    feature_values.append(value)
                role_values.append(feature_values)
            dense.append(role_values)

        # One unique route per (plane, role) pair.  Exactly one path contributes
        # to each output coordinate, so reconstruction performs no unstable
        # cancellation and uses ranks independent of the original CP rank.
        rank_one = plane_count
        rank_two = plane_count * role_count
        first: TTCore = (
            tuple(
                tuple(1.0 if plane == left else 0.0 for left in range(rank_one))
                for plane in range(plane_count)
            ),
        )
        middle: TTCore = tuple(
            tuple(
                tuple(
                    1.0 if right == left * role_count + role else 0.0
                    for right in range(rank_two)
                )
                for role in range(role_count)
            )
            for left in range(rank_one)
        )
        final: TTCore = tuple(
            tuple(
                (dense[right // role_count][right % role_count][feature],)
                for feature in range(feature_count)
            )
            for right in range(rank_two)
        )
        return cls(spec=tensor.spec, cores=(first, middle, final))

    def _payload(self) -> dict[str, object]:
        return {
            "schema": TT_SCHEMA,
            "spec_id": self.spec.spec_id,
            "cores": [
                [[list(right) for right in modes] for modes in core]
                for core in self.cores
            ],
        }

    def _computed_id(self) -> str:
        return "tt:" + canonical_digest(self._payload(), domain=TT_SCHEMA)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "tensor_id": self.tensor_id}

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, value: object, spec: TensorSpec) -> "TensorTrain":
        data = _object_with_keys(
            value,
            frozenset({"schema", "spec_id", "cores", "tensor_id"}),
            label="TensorTrain",
        )
        if data["schema"] != TT_SCHEMA:
            raise ContractError(f"unsupported TensorTrain schema: {data['schema']!r}")
        if data["spec_id"] != spec.spec_id:
            raise ContractError("TensorTrain spec_id does not match the supplied TensorSpec")
        cores = data["cores"]
        if not isinstance(cores, list) or len(cores) != 3:
            raise ContractError("serialized TensorTrain cores must be a three-item JSON array")
        return cls(
            spec=spec,
            cores=tuple(cores),  # type: ignore[arg-type]
            tensor_id=data["tensor_id"],  # type: ignore[arg-type]
        )

    @classmethod
    def from_bytes(cls, raw: bytes | str, spec: TensorSpec) -> "TensorTrain":
        return cls.from_dict(_strict_json_loads(raw), spec)

    def to_dense(self) -> DenseTensor:
        from .algebra import tt_to_dense

        return tt_to_dense(self)


TensorLike: TypeAlias = DenseTensor | CPTensor | TensorTrain


__all__ = [
    "PLANES",
    "ROLES",
    "NORMALIZATION",
    "SPEC_SCHEMA",
    "KERNEL_SCHEMA",
    "CP_SCHEMA",
    "DENSE_SCHEMA",
    "TT_SCHEMA",
    "ContractError",
    "canonical_json_bytes",
    "canonical_digest",
    "TensorSpec",
    "SeparableKernel",
    "CPTerm",
    "CPTensor",
    "DenseTensor",
    "TensorTrain",
    "TensorLike",
]
