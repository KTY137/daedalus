from __future__ import annotations

import gc
import hashlib
import json
import statistics
import time
import tracemalloc
from collections.abc import Callable
from typing import Any

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import FourfoldSnapshot, fourfold_from_knowledge_forest
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

REVISION = "a" * 40
NOW = "2026-08-30T16:58:27Z"
MAX_PROBE_SUBJECTS = 10_000
MAX_PROBE_REPEATS = 20
MAX_QUERY_ITERATIONS = 100


def _rows(size: int) -> tuple[tuple[str, str], ...]:
    if type(size) is not int or not 1 <= size <= MAX_PROBE_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_PROBE_SUBJECTS}]")
    return tuple(
        (f"src/module_{index:05d}.py", "code" if index % 2 == 0 else "knowledge")
        for index in range(size)
    )


def _forest(rows: tuple[tuple[str, str], ...]) -> KnowledgeForest:
    return KnowledgeForest(
        root=".",
        nodes=tuple(
            ForestNode(node_id, "source_file" if plane == "code" else "document")
            for node_id, plane in rows
        ),
        edges=(),
        hyperedges=(),
        provenance={"origin": "test.tensor-forest-cost-probe", "source_revision": REVISION},
    )


def _fourfold(forest: KnowledgeForest, *, trace_id: str) -> FourfoldSnapshot:
    return fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=NOW,
        trace_id=trace_id,
    )


def _tensor(
    rows: tuple[tuple[str, str], ...],
    forest: KnowledgeForest,
    fourfold: FourfoldSnapshot,
) -> TensorView:
    provenance = ContractProvenance(
        origin="test.tensor-forest-cost-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(forest.content_sha256, fourfold.digest),
        trace_id="tensor-forest-cost-probe",
    )
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        source_fourfold_sha256=fourfold.digest,
        status="complete",
        axes=(
            TensorAxis("node", tuple(node_id for node_id, _ in rows)),
            TensorAxis("plane", ("code", "knowledge")),
        ),
        entries=tuple(
            SparseTensorEntry(
                coordinates=(("node", node_id), ("plane", plane)),
                relation="membership",
                evidence_sha256s=(
                    hashlib.sha256(f"{node_id}:{plane}".encode("utf-8")).hexdigest(),
                ),
            )
            for node_id, plane in rows
        ),
        provenance=provenance,
    )


def _forest_query(subject: KnowledgeForest, plane: str) -> tuple[str, ...]:
    kind = {"code": "source_file", "knowledge": "document"}[plane]
    return tuple(node.id for node in subject.nodes if node.kind == kind)


def _tensor_query(subject: TensorView, plane: str) -> tuple[str, ...]:
    return tuple(entry.coordinates[0][1] for entry in subject.select(plane=plane))


def _relation_forest(size: int) -> KnowledgeForest:
    if type(size) is not int or not 1 <= size <= MAX_PROBE_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_PROBE_SUBJECTS}]")
    code_ids = tuple(f"src/module_{index:05d}.py" for index in range(size))
    document_ids = tuple(f"docs/module_{index:05d}.md" for index in range(size))
    nodes = tuple(
        [ForestNode(node_id, "source_file") for node_id in code_ids]
        + [ForestNode(node_id, "document") for node_id in document_ids]
    )
    document_edges = tuple(
        ForestEdge(
            source=code_id,
            target=document_id,
            relation="documents",
            directed=True,
            evidence=(hashlib.sha256(f"documents:{code_id}:{document_id}".encode()).hexdigest(),),
        )
        for code_id, document_id in zip(code_ids, document_ids)
    )
    import_edges = tuple(
        ForestEdge(
            source=code_ids[index],
            target=code_ids[(index + 1) % size],
            relation="imports",
            directed=True,
            evidence=(
                hashlib.sha256(
                    f"imports:{code_ids[index]}:{code_ids[(index + 1) % size]}".encode()
                ).hexdigest(),
            ),
        )
        for index in range(0, size, 2)
    )
    return KnowledgeForest(
        root=".",
        nodes=nodes,
        edges=document_edges + import_edges,
        hyperedges=(),
        provenance={"origin": "test.tensor-forest-relation-cost-probe", "source_revision": REVISION},
    )


def _relation_tensor(
    forest: KnowledgeForest,
    fourfold: FourfoldSnapshot,
) -> TensorView:
    plane_by_node = {
        node.id: "code" if node.kind == "source_file" else "knowledge"
        for node in forest.nodes
    }
    provenance = ContractProvenance(
        origin="test.tensor-forest-relation-cost-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(forest.content_sha256, fourfold.digest),
        trace_id="tensor-forest-relation-cost-probe",
    )
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        source_fourfold_sha256=fourfold.digest,
        status="complete",
        axes=(
            TensorAxis("source", tuple(sorted({edge.source for edge in forest.edges}))),
            TensorAxis("source_plane", tuple(sorted({plane_by_node[edge.source] for edge in forest.edges}))),
            TensorAxis("target", tuple(sorted({edge.target for edge in forest.edges}))),
            TensorAxis("target_plane", tuple(sorted({plane_by_node[edge.target] for edge in forest.edges}))),
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
                evidence_sha256s=(
                    hashlib.sha256(
                        f"{edge.relation}:{edge.source}:{edge.target}".encode("utf-8")
                    ).hexdigest(),
                ),
            )
            for edge in forest.edges
        ),
        provenance=provenance,
    )


def _relation_forest_query(subject: KnowledgeForest) -> tuple[str, ...]:
    kind_by_node = {node.id: node.kind for node in subject.nodes}
    documented: set[str] = set()
    importing: set[str] = set()
    for edge in subject.edges:
        if (
            edge.relation == "documents"
            and kind_by_node.get(edge.source) == "source_file"
            and kind_by_node.get(edge.target) == "document"
        ):
            documented.add(edge.source)
        elif (
            edge.relation == "imports"
            and kind_by_node.get(edge.source) == "source_file"
            and kind_by_node.get(edge.target) == "source_file"
        ):
            importing.add(edge.source)
    return tuple(sorted(documented & importing))


def _relation_forest_index(
    subject: KnowledgeForest,
) -> dict[tuple[str, str, str], frozenset[str]]:
    kind_by_node = {node.id: node.kind for node in subject.nodes}
    buckets: dict[tuple[str, str, str], set[str]] = {}
    for edge in subject.edges:
        source_kind = kind_by_node.get(edge.source)
        target_kind = kind_by_node.get(edge.target)
        if source_kind is None or target_kind is None:
            continue
        key = (edge.relation, source_kind, target_kind)
        buckets.setdefault(key, set()).add(edge.source)
    return {key: frozenset(values) for key, values in buckets.items()}


def _relation_forest_preindexed_query(
    subject: tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        dict[tuple[str, str, str], frozenset[str]],
    ],
) -> tuple[str, ...]:
    _, _, index = subject
    documented = index[("documents", "source_file", "document")]
    importing = index[("imports", "source_file", "source_file")]
    return tuple(sorted(documented & importing))


def _relation_tensor_query(subject: TensorView) -> tuple[str, ...]:
    positions = {axis.name: index for index, axis in enumerate(subject.axes)}
    source_position = positions["source"]
    target_plane_position = positions["target_plane"]
    documented: set[str] = set()
    importing: set[str] = set()
    for entry in subject.select(source_plane="code"):
        source = entry.coordinates[source_position][1]
        target_plane = entry.coordinates[target_plane_position][1]
        if entry.relation == "documents" and target_plane == "knowledge":
            documented.add(source)
        elif entry.relation == "imports" and target_plane == "code":
            importing.add(source)
    return tuple(sorted(documented & importing))


def _measure(
    build: Callable[[], Any],
    query: Callable[[Any], tuple[str, ...]],
    *,
    repeats: int,
    query_iterations: int,
) -> tuple[dict[str, int], tuple[str, ...]]:
    if type(repeats) is not int or not 1 <= repeats <= MAX_PROBE_REPEATS:
        raise ValueError(f"repeats must be an integer in [1, {MAX_PROBE_REPEATS}]")
    if type(query_iterations) is not int or not 1 <= query_iterations <= MAX_QUERY_ITERATIONS:
        raise ValueError(
            f"query_iterations must be an integer in [1, {MAX_QUERY_ITERATIONS}]"
        )

    construction_ns: list[int] = []
    construction_peak_bytes: list[int] = []
    query_ns: list[int] = []
    query_peak_bytes: list[int] = []
    expected: tuple[str, ...] | None = None

    for _ in range(repeats):
        gc.collect()
        tracemalloc.start()
        started = time.perf_counter_ns()
        subject = build()
        construction_ns.append(time.perf_counter_ns() - started)
        _, peak = tracemalloc.get_traced_memory()
        construction_peak_bytes.append(peak)
        tracemalloc.stop()

        gc.collect()
        tracemalloc.start()
        started = time.perf_counter_ns()
        result: tuple[str, ...] = ()
        for _ in range(query_iterations):
            result = query(subject)
        elapsed = time.perf_counter_ns() - started
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        query_ns.append(elapsed // query_iterations)
        query_peak_bytes.append(peak)

        if expected is None:
            expected = result
        else:
            assert result == expected

    assert expected is not None
    return (
        {
            "construction_ns_median": int(statistics.median(construction_ns)),
            "construction_peak_bytes_median": int(statistics.median(construction_peak_bytes)),
            "query_ns_median": int(statistics.median(query_ns)),
            "query_peak_bytes_median": int(statistics.median(query_peak_bytes)),
        },
        expected,
    )


def probe(
    *,
    size: int = 256,
    repeats: int = 3,
    query_iterations: int = 5,
    plane: str = "code",
) -> dict[str, Any]:
    rows = _rows(size)
    if plane not in {"code", "knowledge"}:
        raise ValueError("plane must be code or knowledge")

    reference_forest = _forest(rows)
    reference_fourfold = _fourfold(
        reference_forest,
        trace_id="tensor-forest-cost-probe",
    )

    def build_forest_arm() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _forest(rows)
        fourfold = _fourfold(forest, trace_id="tensor-forest-cost-probe")
        return forest, fourfold

    forest_metrics, forest_result = _measure(
        build_forest_arm,
        lambda subject: _forest_query(subject[0], plane),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_tensor_arm() -> tuple[KnowledgeForest, FourfoldSnapshot, TensorView]:
        forest = _forest(rows)
        fourfold = _fourfold(forest, trace_id="tensor-forest-cost-probe")
        return forest, fourfold, _tensor(rows, forest, fourfold)

    tensor_metrics, tensor_result = _measure(
        build_tensor_arm,
        lambda subject: _tensor_query(subject[2], plane),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    if forest_result != tensor_result:
        raise AssertionError("tensor projection changed the direct Forest query subject")

    return {
        "schema": "daedalus-tensor-forest-cost-probe/2",
        "authority": "diagnostic-only",
        "claim": "none",
        "construction_basis": "forest+fourfold",
        "source_forest_sha256": reference_forest.content_sha256,
        "source_fourfold_sha256": reference_fourfold.digest,
        "subject_count": size,
        "plane": plane,
        "repeats": repeats,
        "query_iterations_per_repeat": query_iterations,
        "result_count": len(forest_result),
        "result_sha256": hashlib.sha256(
            json.dumps(forest_result, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "arms": {
            "forest_direct": forest_metrics,
            "forest_plus_tensor": tensor_metrics,
        },
    }


def relation_probe(
    *,
    size: int = 256,
    repeats: int = 3,
    query_iterations: int = 5,
) -> dict[str, Any]:
    if type(size) is not int or not 1 <= size <= MAX_PROBE_SUBJECTS:
        raise ValueError(f"size must be an integer in [1, {MAX_PROBE_SUBJECTS}]")

    reference_forest = _relation_forest(size)
    reference_fourfold = _fourfold(
        reference_forest,
        trace_id="tensor-forest-relation-cost-probe",
    )

    def build_forest_arm() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _relation_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-forest-relation-cost-probe")
        return forest, fourfold

    forest_metrics, forest_result = _measure(
        build_forest_arm,
        lambda subject: _relation_forest_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_preindexed_forest_arm() -> tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        dict[tuple[str, str, str], frozenset[str]],
    ]:
        forest = _relation_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-forest-relation-cost-probe")
        return forest, fourfold, _relation_forest_index(forest)

    preindexed_metrics, preindexed_result = _measure(
        build_preindexed_forest_arm,
        _relation_forest_preindexed_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_tensor_arm() -> tuple[KnowledgeForest, FourfoldSnapshot, TensorView]:
        forest = _relation_forest(size)
        fourfold = _fourfold(forest, trace_id="tensor-forest-relation-cost-probe")
        return forest, fourfold, _relation_tensor(forest, fourfold)

    tensor_metrics, tensor_result = _measure(
        build_tensor_arm,
        lambda subject: _relation_tensor_query(subject[2]),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    if forest_result != preindexed_result or forest_result != tensor_result:
        raise AssertionError("comparison arm changed the direct cross-plane Forest query subject")

    return {
        "schema": "daedalus-tensor-forest-relation-cost-probe/3",
        "authority": "diagnostic-only",
        "claim": "none",
        "construction_basis": "forest+fourfold",
        "source_forest_sha256": reference_forest.content_sha256,
        "source_fourfold_sha256": reference_fourfold.digest,
        "workload": "documented-import-sources",
        "subject_count": size,
        "node_count": size * 2,
        "edge_count": size + ((size + 1) // 2),
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


def test_tensor_query_matches_direct_forest_subject() -> None:
    result = probe(size=64, repeats=1, query_iterations=2, plane="knowledge")

    assert result["result_count"] == 32
    assert len(result["result_sha256"]) == 64
    assert result["claim"] == "none"


def test_cost_probe_reports_equal_budget_arms_without_speed_claim() -> None:
    result = probe(size=32, repeats=2, query_iterations=3)

    assert result["schema"] == "daedalus-tensor-forest-cost-probe/2"
    assert result["authority"] == "diagnostic-only"
    assert result["construction_basis"] == "forest+fourfold"
    assert len(result["source_forest_sha256"]) == 64
    assert len(result["source_fourfold_sha256"]) == 64
    assert result["repeats"] == 2
    assert result["query_iterations_per_repeat"] == 3
    assert set(result["arms"]) == {"forest_direct", "forest_plus_tensor"}
    for metrics in result["arms"].values():
        assert set(metrics) == {
            "construction_ns_median",
            "construction_peak_bytes_median",
            "query_ns_median",
            "query_peak_bytes_median",
        }
        assert all(type(value) is int and value >= 0 for value in metrics.values())


def test_probe_binds_tensor_to_real_fourfold_snapshot_identity() -> None:
    rows = _rows(8)
    forest = _forest(rows)
    fourfold = _fourfold(forest, trace_id="tensor-forest-cost-probe")
    tensor = _tensor(rows, forest, fourfold)

    assert tensor.source_forest_sha256 == forest.content_sha256
    assert tensor.source_fourfold_sha256 == fourfold.digest
    assert fourfold.source_forest_sha256 == forest.content_sha256


def test_relation_probe_matches_cross_plane_multi_relation_forest_subject() -> None:
    result = relation_probe(size=64, repeats=1, query_iterations=2)

    assert result["schema"] == "daedalus-tensor-forest-relation-cost-probe/3"
    assert result["construction_basis"] == "forest+fourfold"
    assert len(result["source_forest_sha256"]) == 64
    assert len(result["source_fourfold_sha256"]) == 64
    assert result["workload"] == "documented-import-sources"
    assert result["node_count"] == 128
    assert result["edge_count"] == 96
    assert result["result_count"] == 32
    assert len(result["result_sha256"]) == 64
    assert result["claim"] == "none"


def test_relation_cost_probe_reports_equal_budget_arms_without_speed_claim() -> None:
    result = relation_probe(size=32, repeats=2, query_iterations=3)

    assert result["authority"] == "diagnostic-only"
    assert result["repeats"] == 2
    assert result["query_iterations_per_repeat"] == 3
    assert set(result["arms"]) == {
        "forest_direct",
        "forest_preindexed",
        "forest_plus_tensor",
    }
    for metrics in result["arms"].values():
        assert all(type(value) is int and value >= 0 for value in metrics.values())


def test_cost_probe_bounds_its_own_work() -> None:
    for kwargs in (
        {"size": 0},
        {"size": MAX_PROBE_SUBJECTS + 1},
        {"repeats": 0},
        {"repeats": MAX_PROBE_REPEATS + 1},
        {"query_iterations": 0},
        {"query_iterations": MAX_QUERY_ITERATIONS + 1},
    ):
        with pytest.raises(ValueError):
            probe(**kwargs)
        with pytest.raises(ValueError):
            relation_probe(**kwargs)
