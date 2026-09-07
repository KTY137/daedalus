"""Compatibility projection of one Fourfold relation into a Boolean block.

The canonical projection owner is :func:`compile_relation_blocks`.  This module
keeps the historical single-relation API stable without retaining a second
Forest/Fourfold admission or materialization path.  Forest and Fourfold remain
the only fact authorities; the returned block is regenerable and grants no
trust, approval, execution authority, or promotion capability.
"""
from __future__ import annotations

from ..structcore.forest import KnowledgeForest
from .contracts import FourfoldSnapshot
from .relation_blocks import RelationSignature, TypedRelationBlock
from .relation_compiler import compile_relation_blocks
from .semiring import BooleanSemiring


def boolean_relation_block_from_fourfold(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    signature: RelationSignature,
) -> TypedRelationBlock[bool]:
    """Compile one Boolean relation through the canonical relation compiler.

    The function is intentionally only a compatibility call shape. Admission,
    diagnostics, endpoint completeness, exact Forest/Fourfold partitioning,
    retention, cross-plane binding authority, hyperedge/undirected refusal and
    indexed block construction all belong to ``compile_relation_blocks``.
    """

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(signature,),
    )

    # Exactly one explicit signature is requested, so the compiler returns one
    # canonical block even when the retained relation is empty.
    return compiled.blocks[0][1]


__all__ = ["boolean_relation_block_from_fourfold"]
