from __future__ import annotations

import hashlib
import json
import runpy
from dataclasses import replace
from pathlib import Path
from typing import Any

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, KnowledgeForest
from daedalus.twin import FourfoldSnapshot, fourfold_from_knowledge_forest
from daedalus.twin.tensor import SparseTensorEntry, TensorView

_HELDOUT = runpy.run_path(str(Path(__file__).with_name("test_tensor_heldout_multihop_probe.py")))
_measure = _HELDOUT["_measure"]
_heldout_forest = _HELDOUT["_heldout_forest"]
_heldout_tensor = _HELDOUT["_heldout_tensor"]
_heldout_forest_index = _HELDOUT["_heldout_forest_index"]
_heldout_tensor_maps = _HELDOUT["_heldout_tensor_maps"]
_query_relation_suite = _HELDOUT["_query_relation_suite"]
REVISION = _HELDOUT["REVISION"]
NOW = _HELDOUT["NOW"]
MAX_HELDOUT_SUBJECTS = _HELDOUT["MAX_HELDOUT_SUBJECTS"]

DELTA_REVISION = "b" * 40
DELTA_SPEC = {
    "version": 1,
    "relation": "mentions_type",
    "selection": "first N document subjects in generator order",
    "mutation": "toggle matching vs next-type mention",
    "scope": "derived refresh only; revised Forest/Fourfold are prepaid authority",
}
DELTA_SPEC_SHA256 = hashlib.sha256(
    json.dumps(DELTA_SPEC, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
RelationMaps = tuple[dict[str, str], dict[str, str], dict[str, str], dict[str, str]]


def _fourfold(forest: KnowledgeForest, revision: str) -> FourfoldSnapshot:
    return fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=revision,
        created_at=NOW,
        trace_id="tensor-delta-refresh-probe",
    )


def _revised_forest(base: KnowledgeForest, *, size: int, changed_subjects: int) -> KnowledgeForest:
    changed = 0
    edges: list[ForestEdge] = []
    for edge in base.edges:
        if edge.relation == "mentions_type" and changed < changed_subjects:
            matching = f"type:Contract{changed:05d}"
            alternate = f"type:Contract{(changed + 1) % size:05d}"
            target = alternate if edge.target == matching else matching
            edge = replace(
                edge,
                target=target,
                evidence=(hashlib.sha256(f"heldout-delta:{edge.source}:{target}".encode()).hexdigest(),),
            )
            changed += 1
        edges.append(edge)
    if changed != changed_subjects:
        raise AssertionError("delta generator did not change the requested subjects")
    return replace(
        base,
        edges=tuple(edges),
        provenance={"origin": "test.tensor-delta-refresh-probe", "source_revision": DELTA_REVISION},
    )


def _changed_mentions(forest: KnowledgeForest, count: int) -> dict[str, ForestEdge]:
    changed = {
        edge.source: edge
        for edge in forest.edges
        if edge.relation == "mentions_type"
        and int(edge.source.removeprefix("docs/module_").removesuffix(".md")) < count
    }
    if len(changed) != count:
        raise AssertionError("revised Forest does not retain the requested delta")
    return changed


def _refresh_index(base: RelationMaps, changed: dict[str, ForestEdge]) -> RelationMaps:
    refreshed = tuple(dict(bucket) for bucket in base)
    refreshed[3].update({source: edge.target for source, edge in changed.items()})
    return refreshed  # type: ignore[return-value]


def _refresh_tensor(
    base: TensorView,
    revised_forest: KnowledgeForest,
    revised_fourfold: FourfoldSnapshot,
    changed: dict[str, ForestEdge],
) -> TensorView:
    def refreshed_entry(entry: SparseTensorEntry) -> SparseTensorEntry:
        if entry.relation != "mentions_type":
            return entry
        source = entry.coordinate_map["source"]
        edge = changed.get(source)
        if edge is None:
            return entry
        return replace(
            entry,
            coordinates=tuple(
                (axis, edge.target if axis == "target" else label)
                for axis, label in entry.coordinates
            ),
            evidence_sha256s=edge.evidence,
        )

    return TensorView(
        repository_id=base.repository_id,
        source_revision=DELTA_REVISION,
        source_forest_sha256=revised_forest.content_sha256,
        source_fourfold_sha256=revised_fourfold.digest,
        status="complete",
        axes=base.axes,
        entries=tuple(refreshed_entry(entry) for entry in base.entries),
        provenance=ContractProvenance(
            origin="test.tensor-delta-refresh-probe",
            source_revision=DELTA_REVISION,
            created_at=NOW,
            input_digests=(revised_forest.content_sha256, revised_fourfold.digest),
            trace_id="tensor-delta-refresh-probe",
        ),
    )


def _as_refresh_metrics(metrics: dict[str, int]) -> dict[str, int]:
    return {
        "refresh_ns_median": metrics["construction_ns_median"],
        "refresh_peak_bytes_median": metrics["construction_peak_bytes_median"],
        "query_ns_median": metrics["query_ns_median"],
        "query_peak_bytes_median": metrics["query_peak_bytes_median"],
    }


def delta_refresh_probe(
    *, size: int = 256, changed_subjects: int = 8, repeats: int = 3, query_iterations: int = 5
) -> dict[str, Any]:
    if type(size) is not int or not 2 <= size <= MAX_HELDOUT_SUBJECTS:
        raise ValueError(f"size must be an integer in [2, {MAX_HELDOUT_SUBJECTS}]")
    if type(changed_subjects) is not int or not 1 <= changed_subjects <= size:
        raise ValueError("changed_subjects must be an integer in [1, size]")

    base_forest = _heldout_forest(size)
    base_fourfold = _fourfold(base_forest, REVISION)
    revised_forest = _revised_forest(base_forest, size=size, changed_subjects=changed_subjects)
    revised_fourfold = _fourfold(revised_forest, DELTA_REVISION)
    base_index = _heldout_forest_index(base_forest)
    base_tensor = _heldout_tensor(base_forest, base_fourfold)
    changed = _changed_mentions(revised_forest, changed_subjects)
    base_result = _query_relation_suite(base_index)
    revised_result = _query_relation_suite(_heldout_forest_index(revised_forest))
    if base_result == revised_result:
        raise AssertionError("frozen delta did not change the query subject")

    index_metrics, index_result = _measure(
        lambda: _refresh_index(base_index, changed),
        _query_relation_suite,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    tensor_metrics, tensor_result = _measure(
        lambda: _refresh_tensor(base_tensor, revised_forest, revised_fourfold, changed),
        lambda tensor: _query_relation_suite(_heldout_tensor_maps(tensor)),
        repeats=repeats,
        query_iterations=query_iterations,
    )
    if index_result != revised_result or tensor_result != revised_result:
        raise AssertionError("delta refresh changed the revised Forest query subject")

    refreshed_tensor = _refresh_tensor(base_tensor, revised_forest, revised_fourfold, changed)
    if refreshed_tensor != _refresh_tensor(base_tensor, revised_forest, revised_fourfold, changed):
        raise AssertionError("Tensor delta refresh is not deterministic")
    if (
        refreshed_tensor.source_revision != DELTA_REVISION
        or refreshed_tensor.source_forest_sha256 != revised_forest.content_sha256
        or refreshed_tensor.source_fourfold_sha256 != revised_fourfold.digest
    ):
        raise AssertionError("Tensor delta refresh retained stale revision provenance")
    if _query_relation_suite(base_index) != base_result:
        raise AssertionError("index refresh mutated the base snapshot")
    if _query_relation_suite(_heldout_tensor_maps(base_tensor)) != base_result:
        raise AssertionError("Tensor refresh mutated the base snapshot")

    digest = lambda rows: hashlib.sha256(json.dumps(rows, separators=(",", ":")).encode()).hexdigest()
    return {
        "schema": "daedalus-tensor-delta-refresh-cost-probe/1",
        "authority": "diagnostic-only",
        "claim": "none",
        "scope": DELTA_SPEC["scope"],
        "delta_spec_sha256": DELTA_SPEC_SHA256,
        "base_revision": REVISION,
        "revised_revision": DELTA_REVISION,
        "subject_count": size,
        "node_count": size * 4,
        "edge_count": size * 4,
        "changed_subjects": changed_subjects,
        "changed_edges": changed_subjects,
        "changed_subject_fraction": changed_subjects / size,
        "changed_edge_fraction": changed_subjects / (size * 4),
        "base_forest_sha256": base_forest.content_sha256,
        "revised_forest_sha256": revised_forest.content_sha256,
        "base_fourfold_sha256": base_fourfold.digest,
        "revised_fourfold_sha256": revised_fourfold.digest,
        "base_result_sha256": digest(base_result),
        "revised_result_count": len(revised_result),
        "revised_result_sha256": digest(revised_result),
        "repeats": repeats,
        "query_iterations_per_repeat": query_iterations,
        "arms": {
            "forest_independent_indices_delta_refresh": _as_refresh_metrics(index_metrics),
            "tensor_delta_refresh": _as_refresh_metrics(tensor_metrics),
        },
        "tensor_revision_atomic": True,
        "tensor_delta_deterministic": True,
        "base_snapshots_unchanged": True,
    }


def test_delta_refresh_probe_preserves_revision_atomicity() -> None:
    result = delta_refresh_probe(size=64, changed_subjects=4, repeats=1, query_iterations=2)
    assert result["schema"] == "daedalus-tensor-delta-refresh-cost-probe/1"
    assert result["authority"] == "diagnostic-only"
    assert result["claim"] == "none"
    assert result["base_result_sha256"] != result["revised_result_sha256"]
    assert result["tensor_revision_atomic"] is True
    assert result["tensor_delta_deterministic"] is True
    assert result["base_snapshots_unchanged"] is True
    assert set(result["arms"]) == {
        "forest_independent_indices_delta_refresh",
        "tensor_delta_refresh",
    }
