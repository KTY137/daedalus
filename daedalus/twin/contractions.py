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


__all__ = [
    "BlockRef",
    "Compose",
    "ContractionExpression",
    "ContractionPlan",
    "Hadamard",
    "ReferenceContractionInterpreter",
]
