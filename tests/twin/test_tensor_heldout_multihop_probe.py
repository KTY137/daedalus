from __future__ import annotations

import hashlib
import json
import runpy
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


def _heldout_forest(size: int) -> KnowledgeForest:
    if type(size) is not int or not 1 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_HELDOUT_SUBJECTS}]")

    source_ids = tuple(f"src/module_{index:05d}.py" for index in range(size))
    dependency_ids = tuple(f"src/dependency_{index:05d}.py" for index in range(size))
    type_ids = tuple(f"type:Contract{index:05d}" for index in range(size))
    document_ids = tuple(f"docs/module_{index:05d}.md" for index in range(size))

    nodes = tuple(
        [ForestNode(node_id, "source_file") for node_id in source_ids]
        + [ForestNode(node_id, "source_file") for node_id in dependency_ids]
        + [ForestNode(node_id, "type") for node_id in type_ids]
        + [ForestNode(node_id, "document") for node_id in document_ids]
    )

    edges: list[ForestEdge] = []
    for index, (source, dependency, type_id, document) in enumerate(
        zip(source_ids, dependency_ids, type_ids, document_ids)
    ):
        mentioned_type = type_id if index % 2 == 0 else type_ids[(index + 1) % size]
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
    return {
        "source_file": "code",
        "type": "type",
        "document": "knowledge",
    }[kind]


def _heldout_tensor(
    forest: KnowledgeForest,
    fourfold: FourfoldSnapshot,
) -> TensorView:
    plane_by_node = {node.id: _plane_for_kind(node.kind) for node in forest.nodes}
    provenance = ContractProvenance(
        origin="test.tensor-heldout-multihop-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(forest.content_sha256, fourfold.digest),
        trace_id="tensor-heldout-multihop-probe",
    )
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
        provenance=provenance,
    )


def _query_from_relation_maps(
    imports: dict[str, str],
    declarations: dict[str, str],
    documents: dict[str, str],
    mentions: dict[str, str],
) -> tuple[str, ...]:
    result: list[str] = []
    for source, dependency in imports.items():
        document = documents.get(source)
        declared_type = declarations.get(dependency)
        mentioned_type = mentions.get(document) if document is not None else None
        if declared_type is not None and declared_type == mentioned_type:
            result.append(source)
    return tuple(sorted(result))


def _heldout_forest_query(subject: KnowledgeForest) -> tuple[str, ...]:
    imports: dict[str, str] = {}
    declarations: dict[str, str] = {}
    documents: dict[str, str] = {}
    mentions: dict[str, str] = {}
    for edge in subject.edges:
        if edge.relation == "imports":
            imports[edge.source] = edge.target
        elif edge.relation == "declares":
            declarations[edge.source] = edge.target
        elif edge.relation == "documents":
            documents[edge.source] = edge.target
        elif edge.relation == "mentions_type":
            mentions[edge.source] = edge.target
    return _query_from_relation_maps(imports, declarations, documents, mentions)


def _heldout_forest_index(
    subject: KnowledgeForest,
) -> tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]:
    imports: dict[str, str] = {}
    declarations: dict[str, str] = {}
    documents: dict[str, str] = {}
    mentions: dict[str, str] = {}
    for edge in subject.edges:
        target = edge.target
        if edge.relation == "imports":
            imports[edge.source] = target
        elif edge.relation == "declares":
            declarations[edge.source] = target
        elif edge.relation == "documents":
            documents[edge.source] = target
        elif edge.relation == "mentions_type":
            mentions[edge.source] = target
    return imports, declarations, documents, mentions


def _heldout_preindexed_query(
    subject: tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]],
    ],
) -> tuple[str, ...]:
    _, _, relation_maps = subject
    return _query_from_relation_maps(*relation_maps)


def _heldout_tensor_query(subject: TensorView) -> tuple[str, ...]:
    positions = {axis.name: index for index, axis in enumerate(subject.axes)}
    source_position = positions["source"]
    source_plane_position = positions["source_plane"]
    target_position = positions["target"]
    target_plane_position = positions["target_plane"]

    imports: dict[str, str] = {}
    declarations: dict[str, str] = {}
    documents: dict[str, str] = {}
    mentions: dict[str, str] = {}
    for entry in subject.entries:
        source = entry.coordinates[source_position][1]
        source_plane = entry.coordinates[source_plane_position][1]
        target = entry.coordinates[target_position][1]
        target_plane = entry.coordinates[target_plane_position][1]
        relation_shape = (entry.relation, source_plane, target_plane)
        if relation_shape == ("imports", "code", "code"):
            imports[source] = target
        elif relation_shape == ("declares", "code", "type"):
            declarations[source] = target
        elif relation_shape == ("documents", "code", "knowledge"):
            documents[source] = target
        elif relation_shape == ("mentions_type", "knowledge", "type"):
            mentions[source] = target
    return _query_from_relation_maps(imports, declarations, documents, mentions)


def heldout_probe(
    *,
    size: int = 256,
    repeats: int = 3,
    query_iterations: int = 5,
) -> dict[str, Any]:
    if type(size) is not int or not 1 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_HELDOUT_SUBJECTS}]")

    reference_forest = _heldout_forest(size)
    reference_fourfold = _fourfold(
        reference_forest,
        trace_id="tensor-heldout-multihop-probe",
    )

    def build_forest_arm() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _heldout_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-heldout-multihop-probe")
        return forest, fourfold

    forest_metrics, forest_result = _measure(
        build_forest_arm,
        lambda subject: _heldout_forest_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_preindexed_arm() -> tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]],
    ]:
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

    return {
        "schema": "daedalus-tensor-heldout-multihop-cost-probe/1",
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
    }


def test_heldout_multihop_probe_preserves_exact_subject() -> None:
    result = heldout_probe(size=64, repeats=1, query_iterations=2)

    assert result["schema"] == "daedalus-tensor-heldout-multihop-cost-probe/1"
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


def test_heldout_probe_bounds_subject_size() -> None:
    with pytest.raises(ValueError):
        heldout_probe(size=0)
    with pytest.raises(ValueError):
        heldout_probe(size=MAX_HELDOUT_SUBJECTS + 1)
