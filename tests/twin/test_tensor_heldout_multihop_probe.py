from __future__ import annotations

import hashlib
import json
import runpy
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import FourfoldSnapshot
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

_SHARED = runpy.run_path(str(Path(__file__).with_name("test_tensor_forest_cost_probe.py")))
_measure = _SHARED["_measure"]
_fourfold = _SHARED["_fourfold"]
REVISION = _SHARED["REVISION"]
NOW = _SHARED["NOW"]

MAX_HELDOUT_SUBJECTS = 2_048
HELDOUT_WORKLOAD_SPEC = {
    "name": "imported-type-document-consistency",
    "version": 1,
    "query": (
        "return each code source A where A imports code B, B declares type T, "
        "A documents knowledge D, and D mentions the same T"
    ),
    "generator": "deterministic parity split; odd documents mention the next type",
    "comparison": "direct Forest vs relation-preindexed Forest vs derived Tensor",
}
HELDOUT_WORKLOAD_SHA256 = hashlib.sha256(
    json.dumps(HELDOUT_WORKLOAD_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

HELDOUT_QUERY_SUITE_SPEC = {
    "version": 1,
    "queries": (
        "consistent_sources",
        "mismatched_sources",
        "mentioned_types_for_importing_sources",
    ),
    "semantics": (
        "sources whose imported dependency declares the type mentioned by their document",
        "sources whose imported dependency declares a different type than their document mentions",
        "types mentioned by documents attached to importing sources",
    ),
}
HELDOUT_QUERY_SUITE_SHA256 = hashlib.sha256(
    json.dumps(HELDOUT_QUERY_SUITE_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

RelationMaps = tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]
_RELATION_BUCKET = {
    ("imports", "code", "code"): 0,
    ("declares", "code", "type"): 1,
    ("documents", "code", "knowledge"): 2,
    ("mentions_type", "knowledge", "type"): 3,
}


def _heldout_forest(size: int) -> KnowledgeForest:
    if type(size) is not int or not 1 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_HELDOUT_SUBJECTS}]")

    sources = tuple(f"src/module_{index:05d}.py" for index in range(size))
    dependencies = tuple(f"src/dependency_{index:05d}.py" for index in range(size))
    types = tuple(f"type:Contract{index:05d}" for index in range(size))
    documents = tuple(f"docs/module_{index:05d}.md" for index in range(size))
    nodes = tuple(
        [ForestNode(node_id, "source_file") for node_id in sources + dependencies]
        + [ForestNode(node_id, "type") for node_id in types]
        + [ForestNode(node_id, "document") for node_id in documents]
    )

    edges: list[ForestEdge] = []
    for index, (source, dependency, type_id, document) in enumerate(
        zip(sources, dependencies, types, documents)
    ):
        mentioned_type = type_id if index % 2 == 0 else types[(index + 1) % size]
        for relation, edge_source, edge_target in (
            ("imports", source, dependency),
            ("declares", dependency, type_id),
            ("documents", source, document),
            ("mentions_type", document, mentioned_type),
        ):
            edges.append(
                ForestEdge(
                    source=edge_source,
                    target=edge_target,
                    relation=relation,
                    directed=True,
                    evidence=(
                        hashlib.sha256(
                            f"heldout:{relation}:{edge_source}:{edge_target}".encode("utf-8")
                        ).hexdigest(),
                    ),
                )
            )

    return KnowledgeForest(
        root=".",
        nodes=nodes,
        edges=tuple(edges),
        hyperedges=(),
        provenance={
            "origin": "test.tensor-heldout-multihop-probe",
            "source_revision": REVISION,
        },
    )


def _plane_for_kind(kind: str) -> str:
    return {"source_file": "code", "type": "type", "document": "knowledge"}[kind]


def _heldout_tensor(forest: KnowledgeForest, fourfold: FourfoldSnapshot) -> TensorView:
    plane_by_node = {node.id: _plane_for_kind(node.kind) for node in forest.nodes}
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        source_fourfold_sha256=fourfold.digest,
        status="complete",
        axes=(
            TensorAxis("source", tuple(sorted({edge.source for edge in forest.edges}))),
            TensorAxis(
                "source_plane",
                tuple(sorted({plane_by_node[edge.source] for edge in forest.edges})),
            ),
            TensorAxis("target", tuple(sorted({edge.target for edge in forest.edges}))),
            TensorAxis(
                "target_plane",
                tuple(sorted({plane_by_node[edge.target] for edge in forest.edges})),
            ),
        ),
        entries=tuple(
            SparseTensorEntry(
                coordinates=(
                    ("source", edge.source),
                    ("source_plane", plane_by_node[edge.source]),
                    ("target", edge.target),
                    ("target_plane", plane_by_node[edge.target]),
                ),
                relation=edge.relation,
                value=edge.weight,
                evidence_sha256s=edge.evidence,
            )
            for edge in forest.edges
        ),
        provenance=ContractProvenance(
            origin="test.tensor-heldout-multihop-probe",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(forest.content_sha256, fourfold.digest),
            trace_id="tensor-heldout-multihop-probe",
        ),
    )


def _relation_maps(rows: Iterable[tuple[str, str, str, str, str]]) -> RelationMaps:
    maps: RelationMaps = ({}, {}, {}, {})
    for relation, source, source_plane, target, target_plane in rows:
        bucket = _RELATION_BUCKET.get((relation, source_plane, target_plane))
        if bucket is not None:
            maps[bucket][source] = target
    return maps


def _query_relation_maps(maps: RelationMaps) -> tuple[str, ...]:
    imports, declarations, documents, mentions = maps
    result: list[str] = []
    for source, dependency in imports.items():
        document = documents.get(source)
        declared_type = declarations.get(dependency)
        mentioned_type = mentions.get(document) if document is not None else None
        if declared_type is not None and declared_type == mentioned_type:
            result.append(source)
    return tuple(sorted(result))


def _query_relation_suite(maps: RelationMaps) -> tuple[str, ...]:
    """Return three tagged multi-hop results from one shared relation subject."""

    imports, declarations, documents, mentions = maps
    result: list[str] = []
    for source, dependency in imports.items():
        document = documents.get(source)
        declared_type = declarations.get(dependency)
        mentioned_type = mentions.get(document) if document is not None else None
        if declared_type is None or mentioned_type is None:
            continue
        if declared_type == mentioned_type:
            result.append(f"consistent:{source}")
        else:
            result.append(f"mismatched:{source}")
        result.append(f"mentioned_type:{mentioned_type}")
    return tuple(sorted(result))


def _heldout_forest_index(subject: KnowledgeForest) -> RelationMaps:
    plane_by_node = {node.id: _plane_for_kind(node.kind) for node in subject.nodes}
    return _relation_maps(
        (
            edge.relation,
            edge.source,
            plane_by_node[edge.source],
            edge.target,
            plane_by_node[edge.target],
        )
        for edge in subject.edges
    )


def _heldout_forest_query(subject: KnowledgeForest) -> tuple[str, ...]:
    return _query_relation_maps(_heldout_forest_index(subject))


def _heldout_forest_suite_query(subject: KnowledgeForest) -> tuple[str, ...]:
    return _query_relation_suite(_heldout_forest_index(subject))


def _heldout_preindexed_query(
    subject: tuple[KnowledgeForest, FourfoldSnapshot, RelationMaps],
) -> tuple[str, ...]:
    return _query_relation_maps(subject[2])


def _heldout_preindexed_suite_query(
    subject: tuple[KnowledgeForest, FourfoldSnapshot, RelationMaps],
) -> tuple[str, ...]:
    return _query_relation_suite(subject[2])


def _heldout_tensor_maps(subject: TensorView) -> RelationMaps:
    positions = {axis.name: index for index, axis in enumerate(subject.axes)}
    source = positions["source"]
    source_plane = positions["source_plane"]
    target = positions["target"]
    target_plane = positions["target_plane"]
    return _relation_maps(
        (
            entry.relation,
            entry.coordinates[source][1],
            entry.coordinates[source_plane][1],
            entry.coordinates[target][1],
            entry.coordinates[target_plane][1],
        )
        for entry in subject.entries
    )


def _heldout_tensor_query(subject: TensorView) -> tuple[str, ...]:
    return _query_relation_maps(_heldout_tensor_maps(subject))


def _heldout_tensor_suite_query(subject: TensorView) -> tuple[str, ...]:
    return _query_relation_suite(_heldout_tensor_maps(subject))


def _break_even_query_count(
    challenger: dict[str, int],
    baseline: dict[str, int],
) -> int | None:
    construction_delta = (
        challenger["construction_ns_median"] - baseline["construction_ns_median"]
    )
    query_savings = baseline["query_ns_median"] - challenger["query_ns_median"]
    if construction_delta <= 0:
        return 0
    if query_savings <= 0:
        return None
    return (construction_delta + query_savings - 1) // query_savings


def heldout_probe(
    *,
    size: int = 256,
    repeats: int = 3,
    query_iterations: int = 5,
) -> dict[str, Any]:
    if type(size) is not int or not 1 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_HELDOUT_SUBJECTS}]")

    reference_forest = _heldout_forest(size)
    reference_fourfold = _fourfold(reference_forest, trace_id="tensor-heldout-multihop-probe")

    def build_forest_arm() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _heldout_forest(size)
        return forest, _fourfold(forest, trace_id="tensor-heldout-multihop-probe")

    forest_metrics, forest_result = _measure(
        build_forest_arm,
        lambda subject: _heldout_forest_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_preindexed_arm() -> tuple[KnowledgeForest, FourfoldSnapshot, RelationMaps]:
        forest = _heldout_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-heldout-multihop-probe")
        return forest, fourfold, _heldout_forest_index(forest)

    preindexed_metrics, preindexed_result = _measure(
        build_preindexed_arm,
        _heldout_preindexed_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_tensor_arm() -> tuple[KnowledgeForest, FourfoldSnapshot, TensorView]:
        forest = _heldout_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-heldout-multihop-probe")
        return forest, fourfold, _heldout_tensor(forest, fourfold)

    tensor_metrics, tensor_result = _measure(
        build_tensor_arm,
        lambda subject: _heldout_tensor_query(subject[2]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    if forest_result != preindexed_result or forest_result != tensor_result:
        raise AssertionError("held-out comparison arm changed the direct Forest query subject")

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
    if (
        forest_suite_result != preindexed_suite_result
        or forest_suite_result != tensor_suite_result
    ):
        raise AssertionError("query-suite arm changed the direct Forest subject")

    return {
        "schema": "daedalus-tensor-heldout-multihop-cost-probe/2",
        "authority": "diagnostic-only",
        "claim": "none",
        "held_out": True,
        "workload": HELDOUT_WORKLOAD_SPEC["name"],
        "workload_spec_sha256": HELDOUT_WORKLOAD_SHA256,
        "construction_basis": "forest+fourfold",
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
        },
        "query_suite": {
            "queries": HELDOUT_QUERY_SUITE_SPEC["queries"],
            "query_suite_spec_sha256": HELDOUT_QUERY_SUITE_SHA256,
            "result_count": len(forest_suite_result),
            "result_sha256": hashlib.sha256(
                json.dumps(forest_suite_result, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "arms": {
                "forest_direct": forest_suite_metrics,
                "forest_preindexed": preindexed_suite_metrics,
                "forest_plus_tensor": tensor_suite_metrics,
            },
            "tensor_break_even_query_suites": {
                "vs_forest_direct": _break_even_query_count(
                    tensor_suite_metrics, forest_suite_metrics
                ),
                "vs_forest_preindexed": _break_even_query_count(
                    tensor_suite_metrics, preindexed_suite_metrics
                ),
            },
        },
    }


def test_heldout_multihop_probe_preserves_exact_subject() -> None:
    result = heldout_probe(size=64, repeats=1, query_iterations=2)

    assert result["schema"] == "daedalus-tensor-heldout-multihop-cost-probe/2"
    assert result["authority"] == "diagnostic-only"
    assert result["claim"] == "none"
    assert result["held_out"] is True
    assert result["construction_basis"] == "forest+fourfold"
    assert len(result["workload_spec_sha256"]) == 64
    assert len(result["source_forest_sha256"]) == 64
    assert len(result["source_fourfold_sha256"]) == 64
    assert result["node_count"] == 256
    assert result["edge_count"] == 256
    assert result["result_count"] == 32
    assert len(result["result_sha256"]) == 64
    assert set(result["arms"]) == {
        "forest_direct",
        "forest_preindexed",
        "forest_plus_tensor",
    }

    suite = result["query_suite"]
    assert suite["queries"] == HELDOUT_QUERY_SUITE_SPEC["queries"]
    assert len(suite["query_suite_spec_sha256"]) == 64
    assert suite["result_count"] == 128
    assert len(suite["result_sha256"]) == 64
    assert set(suite["arms"]) == {
        "forest_direct",
        "forest_preindexed",
        "forest_plus_tensor",
    }
    assert set(suite["tensor_break_even_query_suites"]) == {
        "vs_forest_direct",
        "vs_forest_preindexed",
    }
    for value in suite["tensor_break_even_query_suites"].values():
        assert value is None or (type(value) is int and value >= 0)


def test_heldout_probe_bounds_subject_size() -> None:
    with pytest.raises(ValueError):
        heldout_probe(size=0)
    with pytest.raises(ValueError):
        heldout_probe(size=MAX_HELDOUT_SUBJECTS + 1)
