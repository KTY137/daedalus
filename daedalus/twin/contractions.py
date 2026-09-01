"""A minimal typed contraction IR with one bounded reference interpreter.

The IR deliberately exposes only operations whose exact semantics are supplied
by a Semiring and TypedRelationBlock.  GraphBLAS or specialized kernels may be
added as optional compilers later; they must remain observationally equal to
this interpreter on the same revision-bound blocks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, Union, TypeVar

from ..schemas import _identifier
from ..spine.envelope import canonical_json, canonical_sha
from .relation_blocks import (
    MAX_REFERENCE_OPERATIONS,
    TypedRelationBlock,
)
from .semiring import Semiring

T = TypeVar("T")
_MAX_CONTRACTION_PLAN_NODES = 256


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


def _require_bounded_expression(value: Any, name: str) -> None:
    """Validate a complete expression iteratively before recursive use."""

    _require_expression(value, name)
    pending: list[ContractionExpression] = [value]
    node_count = 0
    while pending:
        expression = pending.pop()
        node_count += 1
        if node_count > _MAX_CONTRACTION_PLAN_NODES:
            raise ValueError(
                "contraction expression exceeds bounded node limit "
                f"{_MAX_CONTRACTION_PLAN_NODES}"
            )
        if isinstance(expression, BlockRef):
            continue
        _require_expression(expression.left, f"{name}.left")
        _require_expression(expression.right, f"{name}.right")
        pending.append(expression.right)
        pending.append(expression.left)


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
        _require_bounded_expression(self.expression, "plan.expression")

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
        result, _ = self._evaluate_expression(
            plan.expression,
            blocks,
            self._max_operations,
        )
        return result

    def _evaluate_expression(
        self,
        expression: ContractionExpression,
        blocks: Mapping[str, TypedRelationBlock[T]],
        remaining_operations: int,
    ) -> tuple[TypedRelationBlock[T], int]:
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
            return block, remaining_operations
        if isinstance(expression, Compose):
            left, remaining_operations = self._evaluate_expression(
                expression.left,
                blocks,
                remaining_operations,
            )
            right, remaining_operations = self._evaluate_expression(
                expression.right,
                blocks,
                remaining_operations,
            )
            operations = sum(
                right.row_offsets[middle + 1] - right.row_offsets[middle]
                for middle in left.column_indices
            )
            if operations > remaining_operations:
                raise ValueError("reference contraction exceeds bounded operation limit")
            result = left.matmul(
                right,
                self._semiring,
                relation=expression.relation,
                max_operations=remaining_operations,
            )
            return result, remaining_operations - operations
        if isinstance(expression, Hadamard):
            left, remaining_operations = self._evaluate_expression(
                expression.left,
                blocks,
                remaining_operations,
            )
            right, remaining_operations = self._evaluate_expression(
                expression.right,
                blocks,
                remaining_operations,
            )
            operations = 0
            for row in range(len(left.row_axis.labels)):
                left_position = left.row_offsets[row]
                left_stop = left.row_offsets[row + 1]
                right_position = right.row_offsets[row]
                right_stop = right.row_offsets[row + 1]
                while left_position < left_stop and right_position < right_stop:
                    left_column = left.column_indices[left_position]
                    right_column = right.column_indices[right_position]
                    if left_column == right_column:
                        operations += 1
                        if operations > remaining_operations:
                            raise ValueError(
                                "reference contraction exceeds bounded operation limit"
                            )
                        left_position += 1
                        right_position += 1
                    elif left_column < right_column:
                        left_position += 1
                    else:
                        right_position += 1
            result = left.hadamard(
                right,
                self._semiring,
                relation=expression.relation,
                max_operations=remaining_operations,
            )
            return result, remaining_operations - operations
        raise ValueError("unsupported contraction expression")


__all__ = [
    "BlockRef",
    "Compose",
    "ContractionExpression",
    "ContractionPlan",
    "Hadamard",
    "ReferenceContractionInterpreter",
]
