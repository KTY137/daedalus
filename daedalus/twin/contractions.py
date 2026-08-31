"""A minimal typed contraction IR with bounded reference and compiled Boolean paths.

The recursive interpreter is the executable semantic oracle. The compiled
Boolean path is deliberately narrower: it pre-resolves one immutable plan and
executes rows directly so nested contractions do not materialize intermediate
TypedRelationBlock objects. It is a regenerable computational projection, not
a new source of truth, cache, scheduler, or promotion authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, Mapping, Union, TypeVar

from ..schemas import _identifier
from ..spine.envelope import canonical_json, canonical_sha
from .relation_blocks import (
    MAX_REFERENCE_OPERATIONS,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from .semiring import BooleanSemiring, Semiring

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


@dataclass(frozen=True)
class _CompiledBooleanNode:
    op: str
    signature: RelationSignature
    row_axis: TypedAxis
    column_axis: TypedAxis
    block: TypedRelationBlock[bool] | None = None
    left: "_CompiledBooleanNode | None" = None
    right: "_CompiledBooleanNode | None" = None


@dataclass(frozen=True)
class CompiledBooleanContractionPlan:
    """Pre-resolved Boolean plan that fuses nested operations into final CSR.

    Compilation validates subject, semiring and typed-axis compatibility once.
    Evaluation keeps only execution-local row memoization and constructs exactly
    one derived relation block at the boundary; no intermediate block is retained.
    """

    plan: ContractionPlan
    subject: ProjectionSubject
    root: _CompiledBooleanNode
    max_operations: int = MAX_REFERENCE_OPERATIONS

    @classmethod
    def compile(
        cls,
        plan: ContractionPlan,
        blocks: Mapping[str, TypedRelationBlock[bool]],
        *,
        max_operations: int = MAX_REFERENCE_OPERATIONS,
    ) -> "CompiledBooleanContractionPlan":
        if not isinstance(plan, ContractionPlan):
            raise ValueError("plan must be ContractionPlan")
        if not isinstance(blocks, Mapping):
            raise ValueError("blocks must be a mapping")
        if (
            type(max_operations) is not int
            or max_operations < 0
            or max_operations > MAX_REFERENCE_OPERATIONS
        ):
            raise ValueError("max_operations must be a bounded non-negative integer")
        boolean = BooleanSemiring()
        subject_box: list[ProjectionSubject] = []

        def compile_node(expression: ContractionExpression) -> _CompiledBooleanNode:
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
                block._require_semiring(boolean)
                if subject_box and block.subject != subject_box[0]:
                    raise ValueError(
                        "compiled contraction inputs must bind the same exact Fourfold subject"
                    )
                if not subject_box:
                    subject_box.append(block.subject)
                return _CompiledBooleanNode(
                    "block",
                    block.signature,
                    block.row_axis,
                    block.column_axis,
                    block=block,
                )

            if isinstance(expression, Compose):
                left = compile_node(expression.left)
                right = compile_node(expression.right)
                if left.column_axis != right.row_axis:
                    raise ValueError(
                        "matrix composition requires an exactly shared typed middle axis"
                    )
                return _CompiledBooleanNode(
                    "compose",
                    RelationSignature(
                        left.signature.source_plane,
                        expression.relation,
                        right.signature.target_plane,
                    ),
                    left.row_axis,
                    right.column_axis,
                    left=left,
                    right=right,
                )

            if isinstance(expression, Hadamard):
                left = compile_node(expression.left)
                right = compile_node(expression.right)
                if left.row_axis != right.row_axis or left.column_axis != right.column_axis:
                    raise ValueError(
                        "Hadamard composition requires identical typed axes"
                    )
                return _CompiledBooleanNode(
                    "hadamard",
                    RelationSignature(
                        left.signature.source_plane,
                        expression.relation,
                        left.signature.target_plane,
                    ),
                    left.row_axis,
                    left.column_axis,
                    left=left,
                    right=right,
                )
            raise ValueError("unsupported contraction expression")

        root = compile_node(plan.expression)
        if not subject_box:
            raise ValueError("compiled contraction must reference at least one block")
        return cls(plan, subject_box[0], root, max_operations)

    def evaluate(self) -> TypedRelationBlock[bool]:
        boolean = BooleanSemiring()
        operations = 0
        memo: dict[tuple[int, int], frozenset[int]] = {}

        def spend(count: int = 1) -> None:
            nonlocal operations
            operations += count
            if operations > self.max_operations:
                raise ValueError("compiled contraction exceeds bounded operation limit")

        def row(node: _CompiledBooleanNode, row_index: int) -> frozenset[int]:
            key = (id(node), row_index)
            cached = memo.get(key)
            if cached is not None:
                return cached

            if node.op == "block":
                assert node.block is not None
                start = node.block.row_offsets[row_index]
                stop = node.block.row_offsets[row_index + 1]
                result = frozenset(node.block.column_indices[start:stop])
            elif node.op == "compose":
                assert node.left is not None and node.right is not None
                targets: set[int] = set()
                for middle in row(node.left, row_index):
                    right_targets = row(node.right, middle)
                    spend(len(right_targets))
                    targets.update(right_targets)
                result = frozenset(targets)
            elif node.op == "hadamard":
                assert node.left is not None and node.right is not None
                left_targets = row(node.left, row_index)
                right_targets = row(node.right, row_index)
                spend(min(len(left_targets), len(right_targets)))
                result = left_targets & right_targets
            else:
                raise ValueError("unsupported compiled contraction operation")

            memo[key] = result
            return result

        entries: dict[tuple[int, int], bool] = {}
        for row_index in range(len(self.root.row_axis.labels)):
            for column_index in row(self.root, row_index):
                entries[(row_index, column_index)] = True

        return TypedRelationBlock._from_indexed(
            self.subject,
            self.root.signature,
            self.root.row_axis,
            self.root.column_axis,
            entries,
            boolean,
        )


__all__ = [
    "BlockRef",
    "CompiledBooleanContractionPlan",
    "Compose",
    "ContractionExpression",
    "ContractionPlan",
    "Hadamard",
    "ReferenceContractionInterpreter",
]
