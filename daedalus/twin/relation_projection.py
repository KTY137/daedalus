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
    """Compile one relation through the canonical Boolean relation compiler.

    The function is intentionally only a compatibility shim.  Admission,
    endpoint completeness, exact Forest/Fourfold partitioning, retention,
    cross-plane binding authority, hyperedge/undirected refusal and indexed
    block construction all belong to ``compile_relation_blocks``.

    A small set of legacy error strings is translated because callers and tests
    historically used those diagnostics.  The translation changes wording
    only; it does not reimplement admission decisions.
    """

    try:
        compiled = compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(signature,),
        )
    except ValueError as error:
        message = str(error)
        if message == "snapshot does not bind the supplied Forest digest":
            raise ValueError(
                "relation projection requires the exact Forest bound by Fourfold"
            ) from error
        if message == "signatures must contain RelationSignature records":
            raise ValueError("signature must be a RelationSignature") from error
        if "cannot flatten undirected ForestEdge" in message:
            raise ValueError(
                "binary relation projection requires an explicitly directed ForestEdge"
            ) from error
        if (
            "requires an exact included verified Fourfold binding before relation compilation"
            in message
        ):
            raise ValueError(
                "cross-plane ForestEdge requires an exact verified Fourfold "
                "binding before relation projection"
            ) from error
        if (
            isinstance(signature, RelationSignature)
            and signature.source_plane != signature.target_plane
            and "cannot flatten a retained ForestHyperedge" in message
        ):
            raise ValueError(
                "binary relation projection cannot flatten a cross-plane "
                "ForestHyperedge without losing semantics"
            ) from error
        raise

    # Exactly one explicit signature is requested, so the compiler returns one
    # canonical block even when the retained relation is empty.
    return compiled.blocks[0][1]


__all__ = ["boolean_relation_block_from_fourfold"]
