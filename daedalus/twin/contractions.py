"""A minimal typed contraction IR with one bounded reference interpreter.

The IR deliberately exposes only operations whose exact semantics are supplied
by a Semiring and TypedRelationBlock.  GraphBLAS or specialized kernels may be
added as optional compilers later; they must remain observationally equal to
this interpreter on the same revision-bound blocks.

This module also carries the smallest executable bridge from the experimental
Fourfold double-category contracts to tensor algebra: a Boolean observer for
one atomic transformation square.  It checks commutation without upgrading the
2-cell status or minting evidence; callers still need the canonical evaluator
and evidence spine for any trust claim.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, Union, TypeVar

from ..schemas import _identifier
from ..spine.envelope import canonical_json, canonical_sha
from .relation_blocks import (
    MAX_REFERENCE_OPERATIONS,
    TypedAxis,
    TypedRelationBlock,
)
from .semiring import Semiring
from .two_category import Transformation2Cell, TypedBoundary

T = TypeVar("T")


@dataclass(frozen=True)
class BlockRef:
    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "block_ref.name"))

    def to_dict(self) -> dict[str, str]:
        return {"op": "block", "name": self.name}


@dataclass(frozen=True)
class Compose:
    left: "ContractionExpression"
    right: "ContractionExpression"
    relation: str

    def __post_init__(self) -> None:
        _require_expression(self.left, "compose.left")
        _require_expression(self.right, "compose.right")
        object.__setattr__(
            self,
            "relation",
            _identifier(self.relation, "compose.relation"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": "compose",
            "relation": self.relation,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


@dataclass(frozen=True)
class Hadamard:
    left: "ContractionExpression"
    right: "ContractionExpression"
    relation: str

    def __post_init__(self) -> None:
        _require_expression(self.left, "hadamard.left")
        _require_expression(self.right, "hadamard.right")
        object.__setattr__(
            self,
            "relation",
            _identifier(self.relation, "hadamard.relation"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "op": "hadamard",
            "relation": self.relation,
            "left": self.left.to_dict(),
            "right": self.right.to_dict(),
        }


ContractionExpression = Union[BlockRef, Compose, Hadamard]


def _require_expression(value: Any, name: str) -> None:
    if not isinstance(value, (BlockRef, Compose, Hadamard)):
        raise ValueError(f"{name} must be a contraction expression")


@dataclass(frozen=True)
class ContractionPlan:
    output_name: str
    expression: ContractionExpression

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "output_name",
            _identifier(self.output_name, "plan.output_name"),
        )
        _require_expression(self.expression, "plan.expression")

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_name": self.output_name,
            "expression": self.expression.to_dict(),
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


class ReferenceContractionInterpreter(Generic[T]):
    """Recursive, deterministic oracle for the contraction IR."""

    def __init__(
        self,
        semiring: Semiring[T],
        *,
        max_operations: int = MAX_REFERENCE_OPERATIONS,
    ) -> None:
        if not isinstance(semiring, Semiring):
            raise ValueError("semiring must implement the Semiring protocol")
        if (
            type(max_operations) is not int
            or max_operations < 0
            or max_operations > MAX_REFERENCE_OPERATIONS
        ):
            raise ValueError(
                "max_operations must be a bounded non-negative integer"
            )
        self._semiring = semiring
        self._max_operations = max_operations

    @property
    def semiring(self) -> Semiring[T]:
        return self._semiring

    def evaluate(
        self,
        plan: ContractionPlan,
        blocks: Mapping[str, TypedRelationBlock[T]],
    ) -> TypedRelationBlock[T]:
        if not isinstance(plan, ContractionPlan):
            raise ValueError("plan must be ContractionPlan")
        if not isinstance(blocks, Mapping):
            raise ValueError("blocks must be a mapping")
        return self._evaluate_expression(plan.expression, blocks)

    def _evaluate_expression(
        self,
        expression: ContractionExpression,
        blocks: Mapping[str, TypedRelationBlock[T]],
    ) -> TypedRelationBlock[T]:
        if isinstance(expression, BlockRef):
            try:
                block = blocks[expression.name]
            except KeyError as exc:
                raise ValueError(
                    f"contraction references unknown block {expression.name!r}"
                ) from exc
            if not isinstance(block, TypedRelationBlock):
                raise ValueError(
                    f"contraction input {expression.name!r} is not a relation block"
                )
            block._require_semiring(self._semiring)
            return block
        if isinstance(expression, Compose):
            left = self._evaluate_expression(expression.left, blocks)
            right = self._evaluate_expression(expression.right, blocks)
            return left.matmul(
                right,
                self._semiring,
                relation=expression.relation,
                max_operations=self._max_operations,
            )
        if isinstance(expression, Hadamard):
            left = self._evaluate_expression(expression.left, blocks)
            right = self._evaluate_expression(expression.right, blocks)
            return left.hadamard(
                right,
                self._semiring,
                relation=expression.relation,
                max_operations=self._max_operations,
            )
        raise ValueError("unsupported contraction expression")


def _require_boundary_axis(
    boundary: TypedBoundary,
    axis: TypedAxis,
    name: str,
) -> None:
    if set(boundary.port_map) != set(axis.labels):
        raise ValueError(f"{name} boundary ports must match the relation-block axis")
    if any(port.plane != axis.plane for port in boundary.ports):
        raise ValueError(f"{name} boundary plane must match the relation-block axis")


def _require_atomic_boolean_realization(
    cell: Transformation2Cell,
    source_block: TypedRelationBlock[bool],
    target_block: TypedRelationBlock[bool],
) -> None:
    if not isinstance(cell, Transformation2Cell):
        raise ValueError("cell must be Transformation2Cell")
    if not isinstance(source_block, TypedRelationBlock) or not isinstance(
        target_block, TypedRelationBlock
    ):
        raise ValueError("square realizations must be TypedRelationBlock records")
    if source_block.semiring_name != "boolean" or target_block.semiring_name != "boolean":
        raise ValueError("2-cell square observation currently requires boolean relation blocks")

    source_subject = source_block.subject
    target_subject = target_block.subject
    if source_subject.repository_id != cell.source.repository_id:
        raise ValueError("source relation block belongs to a different repository")
    if target_subject.repository_id != cell.target.repository_id:
        raise ValueError("target relation block belongs to a different repository")
    if source_subject.source_revision != cell.source.source_revision:
        raise ValueError("source relation block revision does not match the 2-cell source")
    if target_subject.source_revision != cell.target.source_revision:
        raise ValueError("target relation block revision does not match the 2-cell target")

    if cell.source.component_sha256s != (source_block.digest,):
        raise ValueError("source component must bind exactly the observed relation block")
    if cell.target.component_sha256s != (target_block.digest,):
        raise ValueError("target component must bind exactly the observed relation block")

    _require_boundary_axis(cell.source.left, source_block.row_axis, "source-left")
    _require_boundary_axis(cell.source.right, source_block.column_axis, "source-right")
    _require_boundary_axis(cell.target.left, target_block.row_axis, "target-left")
    _require_boundary_axis(cell.target.right, target_block.column_axis, "target-right")


def boolean_square_commutes(
    cell: Transformation2Cell,
    source_block: TypedRelationBlock[bool],
    target_block: TypedRelationBlock[bool],
    *,
    max_operations: int = MAX_REFERENCE_OPERATIONS,
) -> bool:
    """Return whether one atomic Boolean realization makes ``cell`` commute.

    For a source relation ``F: A -> B``, a target relation ``G: A' -> B'``,
    and boundary maps ``u: A -> A'`` and ``v: B -> B'``, this checks the exact
    finite-relation law ``F ; v == u ; G``.  The observer is intentionally
    narrower than a general 2-functor: one relation block must be the sole
    factor of each component, both blocks must be Boolean, and all boundary
    labels must bind exactly.  Unsupported cases fail closed instead of being
    interpreted approximately.

    The result is diagnostic only.  It neither mutates the cell nor upgrades
    ``VerificationStatus``; an evaluator must record any trusted observation in
    the canonical evidence spine separately.
    """
    if (
        type(max_operations) is not int
        or max_operations < 0
        or max_operations > MAX_REFERENCE_OPERATIONS
    ):
        raise ValueError("max_operations must be a bounded non-negative integer")
    _require_atomic_boolean_realization(cell, source_block, target_block)

    operations = 0

    def charge() -> None:
        nonlocal operations
        operations += 1
        if operations > max_operations:
            raise ValueError("2-cell square observation exceeds bounded operation limit")

    target_rows: dict[str, set[str]] = {}
    for row, column, value in target_block.iter_entries():
        charge()
        if value is not True:
            raise ValueError("boolean relation blocks must contain only true entries")
        target_rows.setdefault(row, set()).add(column)

    right_assignment = cell.right_map.assignment_map
    left_path: set[tuple[str, str]] = set()
    for row, column, value in source_block.iter_entries():
        charge()
        if value is not True:
            raise ValueError("boolean relation blocks must contain only true entries")
        left_path.add((row, right_assignment[column]))

    left_assignment = cell.left_map.assignment_map
    right_path: set[tuple[str, str]] = set()
    for row in source_block.row_axis.labels:
        target_row = left_assignment[row]
        for column in target_rows.get(target_row, ()):
            charge()
            right_path.add((row, column))

    return left_path == right_path


__all__ = [
    "BlockRef",
    "Compose",
    "ContractionExpression",
    "ContractionPlan",
    "Hadamard",
    "ReferenceContractionInterpreter",
    "boolean_square_commutes",
]
