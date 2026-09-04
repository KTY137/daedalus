from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import KnowledgeForest
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.relation_blocks import RelationSignature, TypedRelationBlock
from daedalus.twin.relation_projection import boolean_relation_block_from_fourfold
from daedalus.twin.semiring import BooleanSemiring
from daedalus.twin.tensor import TensorView

_SHARED = runpy.run_path(str(Path(__file__).with_name("test_tensor_heldout_multihop_probe.py")))
_measure = _SHARED["_measure"]
_fourfold = _SHARED["_fourfold"]
_heldout_forest = _SHARED["_heldout_forest"]
_heldout_forest_index = _SHARED["_heldout_forest_index"]
_heldout_forest_query = _SHARED["_heldout_forest_query"]
_heldout_forest_suite_query = _SHARED["_heldout_forest_suite_query"]
_heldout_preindexed_query = _SHARED["_heldout_preindexed_query"]
_heldout_preindexed_suite_query = _SHARED["_heldout_preindexed_suite_query"]
_heldout_tensor = _SHARED["_heldout_tensor"]
_heldout_tensor_query = _SHARED["_heldout_tensor_query"]
_heldout_tensor_suite_query = _SHARED["_heldout_tensor_suite_query"]
_break_even_query_count = _SHARED["_break_even_query_count"]
HELDOUT_WORKLOAD_SHA256 = _SHARED["HELDOUT_WORKLOAD_SHA256"]
HELDOUT_QUERY_SUITE_SHA256 = _SHARED["HELDOUT_QUERY_SUITE_SHA256"]
MAX_HELDOUT_SUBJECTS = _SHARED["MAX_HELDOUT_SUBJECTS"]
REVISION = _SHARED["REVISION"]
NOW = _SHARED["NOW"]

CSRSubject = tuple[
    KnowledgeForest,
    FourfoldSnapshot,
    TypedRelationBlock[bool],
    TypedRelationBlock[bool],
    TypedRelationBlock[bool],
    TypedRelationBlock[bool],
]


def _complete_fourfold(forest: KnowledgeForest) -> FourfoldSnapshot:
    """Promote only fixture completeness; retain exact Forest/binding evidence."""

    legacy = _fourfold(forest, trace_id="tensor-heldout-csr-probe")
    planes = tuple(
        PlaneSnapshot(
            plane=plane.plane,
            source_revision=plane.source_revision,
            status="complete",
            node_ids=plane.node_ids,
            relation_sha256s=plane.relation_sha256s,
            evidence_sha256s=plane.evidence_sha256s,
        )
        if plane.plane in {"code", "type", "knowledge"}
        else plane
        for plane in legacy.planes
    )
    provenance = ContractProvenance(
        origin="test.tensor-heldout-csr-probe.complete-fixture",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in legacy.bindings),
        ),
        trace_id="tensor-heldout-csr-probe-complete",
    )
    return FourfoldSnapshot(
        repository_id=legacy.repository_id,
        source_revision=legacy.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=legacy.bindings,
        provenance=provenance,
    )


def _build_csr_subject(size: int) -> CSRSubject:
    forest = _heldout_forest(size)
    fourfold = _complete_fourfold(forest)
    signatures = (
        RelationSignature("code", "imports", "code"),
        RelationSignature("code", "declares", "type"),
        RelationSignature("code", "documents", "knowledge"),
        RelationSignature("knowledge", "mentions_type", "type"),
    )
    blocks = tuple(
        boolean_relation_block_from_fourfold(forest, fourfold, signature)
        for signature in signatures
    )
    return forest, fourfold, *blocks


def _csr_type_paths(subject: CSRSubject) -> tuple[TypedRelationBlock[bool], TypedRelationBlock[bool]]:
    _, _, imports, declarations, documents, mentions = subject
    semiring = BooleanSemiring()
    imported_types = imports.matmul(
        declarations,
        semiring,
        relation="imported_declared_type",
    )
    documented_types = documents.matmul(
        mentions,
        semiring,
        relation="documented_mentioned_type",
    )
    return imported_types, documented_types


def _csr_consistent_query(subject: CSRSubject) -> tuple[str, ...]:
    imported_types, documented_types = _csr_type_paths(subject)
    consistent = imported_types.hadamard(
        documented_types,
        BooleanSemiring(),
        relation="consistent_type",
    )
    labels = consistent.row_axis.labels
    return tuple(
        labels[row]
        for row in range(len(labels))
        if consistent.row_offsets[row] < consistent.row_offsets[row + 1]
    )


def _csr_suite_query(subject: CSRSubject) -> tuple[str, ...]:
    imported_types, documented_types = _csr_type_paths(subject)
    if (
        imported_types.row_axis != documented_types.row_axis
        or imported_types.column_axis != documented_types.column_axis
    ):
        raise AssertionError("held-out CSR paths must share exact code/type axes")

    result: list[str] = []
    type_labels = documented_types.column_axis.labels
    for row, source in enumerate(imported_types.row_axis.labels):
        imported_start = imported_types.row_offsets[row]
        imported_stop = imported_types.row_offsets[row + 1]
        documented_start = documented_types.row_offsets[row]
        documented_stop = documented_types.row_offsets[row + 1]
        if imported_start == imported_stop or documented_start == documented_stop:
            continue
        if imported_stop - imported_start != 1 or documented_stop - documented_start != 1:
            raise AssertionError("held-out generator must retain one type path per importing source")
        imported_type = imported_types.column_indices[imported_start]
        documented_type = documented_types.column_indices[documented_start]
        tag = "consistent" if imported_type == documented_type else "mismatched"
        result.append(f"{tag}:{source}")
        result.append(f"mentioned_type:{type_labels[documented_type]}")
    return tuple(sorted(result))


def heldout_csr_probe(
    *,
    size: int = 256,
    repeats: int = 2,
    query_iterations: int = 5,
) -> dict[str, Any]:
    if type(size) is not int or not 1 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_HELDOUT_SUBJECTS}]")

    reference_forest = _heldout_forest(size)
    reference_fourfold = _complete_fourfold(reference_forest)

    def build_forest_arm() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _heldout_forest(size)
        return forest, _complete_fourfold(forest)

    forest_metrics, forest_result = _measure(
        build_forest_arm,
        lambda subject: _heldout_forest_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_preindexed_arm():
        forest = _heldout_forest(size)
        fourfold = _complete_fourfold(forest)
        return forest, fourfold, _heldout_forest_index(forest)

    preindexed_metrics, preindexed_result = _measure(
        build_preindexed_arm,
        _heldout_preindexed_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_tensor_arm() -> tuple[KnowledgeForest, FourfoldSnapshot, TensorView]:
        forest = _heldout_forest(size)
        fourfold = _complete_fourfold(forest)
        return forest, fourfold, _heldout_tensor(forest, fourfold)

    tensor_metrics, tensor_result = _measure(
        build_tensor_arm,
        lambda subject: _heldout_tensor_query(subject[2]),
        repeats=repeats,
        query_iterations=query_iterations,
    )
    csr_metrics, csr_result = _measure(
        lambda: _build_csr_subject(size),
        _csr_consistent_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    if not (forest_result == preindexed_result == tensor_result == csr_result):
        raise AssertionError("held-out CSR arm changed the direct Forest query subject")

    forest_suite_metrics, forest_suite_result = _measure(
        build_forest_arm,
        lambda subject: _heldout_forest_suite_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )
    preindexed_suite_metrics, preindexed_suite_result = _measure(
        build_preindexed_arm,
        _heldout_preindexed_suite_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    tensor_suite_metrics, tensor_suite_result = _measure(
        build_tensor_arm,
        lambda subject: _heldout_tensor_suite_query(subject[2]),
        repeats=repeats,
        query_iterations=query_iterations,
    )
    csr_suite_metrics, csr_suite_result = _measure(
        lambda: _build_csr_subject(size),
        _csr_suite_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    if not (
        forest_suite_result
        == preindexed_suite_result
        == tensor_suite_result
        == csr_suite_result
    ):
        raise AssertionError("held-out CSR suite changed the direct Forest query subject")

    return {
        "schema": "daedalus-tensor-heldout-csr-cost-probe/1",
        "authority": "diagnostic-only",
        "claim": "none",
        "held_out": True,
        "construction_basis": "forest+complete-fourfold",
        "csr_query_basis": "boolean-matmul+csr-row-occupancy",
        "workload_spec_sha256": HELDOUT_WORKLOAD_SHA256,
        "query_suite_spec_sha256": HELDOUT_QUERY_SUITE_SHA256,
        "source_forest_sha256": reference_forest.content_sha256,
        "source_fourfold_sha256": reference_fourfold.digest,
        "subject_count": size,
        "node_count": size * 4,
        "edge_count": size * 4,
        "repeats": repeats,
        "query_iterations_per_repeat": query_iterations,
        "result_count": len(forest_result),
        "result_sha256": hashlib.sha256(
            json.dumps(forest_result, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "arms": {
            "forest_direct": forest_metrics,
            "forest_preindexed": preindexed_metrics,
            "forest_plus_tensor": tensor_metrics,
            "fourfold_boolean_csr": csr_metrics,
        },
        "query_suite": {
            "result_count": len(forest_suite_result),
            "result_sha256": hashlib.sha256(
                json.dumps(forest_suite_result, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "arms": {
                "forest_direct": forest_suite_metrics,
                "forest_preindexed": preindexed_suite_metrics,
                "forest_plus_tensor": tensor_suite_metrics,
                "fourfold_boolean_csr": csr_suite_metrics,
            },
        },
        "csr_break_even_queries": {
            "single_vs_forest_direct": _break_even_query_count(csr_metrics, forest_metrics),
            "single_vs_forest_preindexed": _break_even_query_count(
                csr_metrics, preindexed_metrics
            ),
            "suite_vs_forest_direct": _break_even_query_count(
                csr_suite_metrics, forest_suite_metrics
            ),
            "suite_vs_forest_preindexed": _break_even_query_count(
                csr_suite_metrics, preindexed_suite_metrics
            ),
        },
    }


def test_heldout_csr_probe_preserves_exact_subject_without_speed_claim() -> None:
    result = heldout_csr_probe(size=16, repeats=1, query_iterations=1)

    assert result["schema"] == "daedalus-tensor-heldout-csr-cost-probe/1"
    assert result["authority"] == "diagnostic-only"
    assert result["claim"] == "none"
    assert result["construction_basis"] == "forest+complete-fourfold"
    assert result["csr_query_basis"] == "boolean-matmul+csr-row-occupancy"
    assert result["node_count"] == 64
    assert result["edge_count"] == 64
    assert result["result_count"] == 8
    assert result["query_suite"]["result_count"] == 32
    expected_arms = {
        "forest_direct",
        "forest_preindexed",
        "forest_plus_tensor",
        "fourfold_boolean_csr",
    }
    assert set(result["arms"]) == expected_arms
    assert set(result["query_suite"]["arms"]) == expected_arms
    assert len(result["result_sha256"]) == 64
    assert len(result["query_suite"]["result_sha256"]) == 64
    for value in result["csr_break_even_queries"].values():
        assert value is None or (type(value) is int and value >= 0)


def test_heldout_csr_fixture_preserves_forest_identity_and_complete_endpoint_planes() -> None:
    forest = _heldout_forest(8)
    fourfold = _complete_fourfold(forest)

    assert fourfold.source_forest_sha256 == forest.content_sha256
    assert {
        plane.plane: plane.status for plane in fourfold.planes
    } == {
        "code": "complete",
        "type": "complete",
        "data": "absent",
        "knowledge": "complete",
    }
    assert all(binding.assurance == "verified" for binding in fourfold.bindings)


def test_heldout_csr_query_does_not_fall_back_to_entry_iteration(monkeypatch) -> None:
    monkeypatch.setattr(
        TypedRelationBlock,
        "iter_entries",
        lambda self: (_ for _ in ()).throw(AssertionError("iter_entries fallback")),
    )
    subject = _build_csr_subject(8)

    assert len(_csr_consistent_query(subject)) == 4
    assert len(_csr_suite_query(subject)) == 16


def test_heldout_csr_probe_bounds_subject_size() -> None:
    with pytest.raises(ValueError):
        heldout_csr_probe(size=0)
    with pytest.raises(ValueError):
        heldout_csr_probe(size=MAX_HELDOUT_SUBJECTS + 1)
