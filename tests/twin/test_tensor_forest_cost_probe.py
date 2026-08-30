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
from daedalus.structcore.forest import ForestNode, KnowledgeForest
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView

REVISION = "a" * 40
FOURFOLD = hashlib.sha256(b"tensor-forest-cost-probe-fourfold").hexdigest()
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


def _tensor(rows: tuple[tuple[str, str], ...], forest: KnowledgeForest) -> TensorView:
    provenance = ContractProvenance(
        origin="test.tensor-forest-cost-probe",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(forest.content_sha256, FOURFOLD),
        trace_id="tensor-forest-cost-probe",
    )
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        source_fourfold_sha256=FOURFOLD,
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
    return tuple(entry.coordinate_map["node"] for entry in subject.select(plane=plane))


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

    forest_metrics, forest_result = _measure(
        lambda: _forest(rows),
        lambda subject: _forest_query(subject, plane),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    def build_tensor_arm() -> tuple[KnowledgeForest, TensorView]:
        forest = _forest(rows)
        return forest, _tensor(rows, forest)

    tensor_metrics, tensor_result = _measure(
        build_tensor_arm,
        lambda subject: _tensor_query(subject[1], plane),
        repeats=repeats,
        query_iterations=query_iterations,
    )

    if forest_result != tensor_result:
        raise AssertionError("tensor projection changed the direct Forest query subject")

    return {
        "schema": "daedalus-tensor-forest-cost-probe/1",
        "authority": "diagnostic-only",
        "claim": "none",
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


def test_tensor_query_matches_direct_forest_subject() -> None:
    result = probe(size=64, repeats=1, query_iterations=2, plane="knowledge")

    assert result["result_count"] == 32
    assert len(result["result_sha256"]) == 64
    assert result["claim"] == "none"


def test_cost_probe_reports_equal_budget_arms_without_speed_claim() -> None:
    result = probe(size=32, repeats=2, query_iterations=3)

    assert result["schema"] == "daedalus-tensor-forest-cost-probe/1"
    assert result["authority"] == "diagnostic-only"
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
