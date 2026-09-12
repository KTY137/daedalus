"""Revision-bound executable tensor projection for canonical software workloads.

No new store or source authority: this runs the existing relation compiler over
one reference-compiled Forest/Fourfold and emits a compact evidence payload.
"""
from __future__ import annotations

from typing import Any

from daedalus.kernel.contracts.base import _sha256
from daedalus.twin.reference_compiler import ReferenceCompileResult
from daedalus.twin.relation_compiler import compile_relation_blocks
from daedalus.twin.semiring import BooleanSemiring

SCHEMA = "daedalus-runtime-tensor-projection/1"


def compile_runtime_projection(
    compiled: ReferenceCompileResult, *, candidate_tree_sha256: str,
) -> dict[str, Any]:
    """Execute the canonical sparse relation kernel on the *same* CAS candidate.

    Partial planes, unsupported retained relations and revision mismatches are
    refused by the canonical compiler, never converted to empty/complete data.
    A successful projection proves representability, NOT semantic correctness
    of generated software or superiority over ordinary retrieval.
    """
    if not isinstance(compiled, ReferenceCompileResult):
        raise ValueError("compiled must be a ReferenceCompileResult")
    candidate = _sha256(candidate_tree_sha256, "candidate_tree_sha256")
    if compiled.source_tree_sha256 != candidate:
        raise ValueError("tensor projection must bind the exact compiled candidate tree")
    if candidate not in compiled.snapshot.provenance.input_digests:
        raise ValueError("Fourfold provenance does not bind the candidate tree")
    projection = compile_relation_blocks(compiled.forest, compiled.snapshot, BooleanSemiring())
    return {
        "schema": SCHEMA,
        "candidate_tree_sha256": candidate,
        "source_revision": compiled.snapshot.source_revision,
        "source_forest_sha256": compiled.forest.content_sha256,
        "source_fourfold_sha256": compiled.snapshot.digest,
        "projection_sha256": projection.digest,
        "semiring": projection.semiring_name,
        "relation_blocks": len(projection.blocks),
        "semantic_facts": projection.semantic_fact_count,
        "verified_bindings": projection.verified_binding_count,
        "kernel_owned": True,
        "authoritative": False,
        "quality_claim": "representation verified; software behavior is evaluated separately",
    }
