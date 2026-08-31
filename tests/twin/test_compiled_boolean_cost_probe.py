from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, KnowledgeForest
from daedalus.twin import FourfoldSnapshot
from daedalus.twin.contractions import (
    BlockRef,
    CompiledBooleanContractionPlan,
    Compose,
    ContractionPlan,
    Hadamard,
    ReferenceContractionInterpreter,
)
from daedalus.twin.relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

_HELDOUT = runpy.run_path(str(Path(__file__).with_name("test_tensor_heldout_multihop_probe.py")))
_SHARED = runpy.run_path(str(Path(__file__).with_name("test_tensor_forest_cost_probe.py")))

_heldout_forest = _HELDOUT["_heldout_forest"]
_heldout_forest_query = _HELDOUT["_heldout_forest_query"]
_heldout_forest_index = _HELDOUT["_heldout_forest_index"]
_heldout_preindexed_query = _HELDOUT["_heldout_preindexed_query"]
_fourfold = _SHARED["_fourfold"]
_measure = _SHARED["_measure"]
REVISION = _SHARED["REVISION"]

RELATIONS = ("imports", "declares", "documents", "mentions_type")
PROBE_SPEC = {
    "name": "fused-compiled-boolean-contraction",
    "version": 1,
    "relations": RELATIONS,
    "query": "(imports @ declares) AND (documents @ mentions_type)",
    "comparison": (
        "direct Forest vs four independent dict indices vs materializing Boolean CSR "
        "reference vs fused compiled Boolean CSR"
    ),
    "construction_basis": "forest+fourfold",
    "compiled_plan_cost": "included in compiled-arm construction",
}
PROBE_SPEC_SHA256 = hashlib.sha256(
    json.dumps(PROBE_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()

_PLAN = ContractionPlan(
    output_name="consistent-source-type",
    expression=Hadamard(
        Compose(BlockRef("imports"), BlockRef("declares"), "imports-declares"),
        Compose(BlockRef("documents"), BlockRef("mentions_type"), "docs-mentions-type"),
        "consistent-source-type",
    ),
)
_BOOLEAN = BooleanSemiring()
_REFERENCE = ReferenceContractionInterpreter(_BOOLEAN)


def _node_planes(fourfold: FourfoldSnapshot) -> dict[str, str]:
    return {
        node_id: plane.plane
        for plane in fourfold.planes
        for node_id in plane.node_ids
    }


def _verified_edge_value(edge: ForestEdge, fourfold: FourfoldSnapshot) -> bool:
    planes = _node_planes(fourfold)
    try:
        source_plane = planes[edge.source]
        target_plane = planes[edge.target]
    except KeyError as exc:
        raise ValueError("requested Forest edge endpoint is absent from Fourfold") from exc

    edge_digest = canonical_sha(edge.to_dict())
    if source_plane == target_plane:
        plane = next(item for item in fourfold.planes if item.plane == source_plane)
        if edge_digest not in plane.relation_sha256s:
            raise ValueError("requested intra-plane Forest edge is absent from Fourfold evidence")
        return True

    binding = next(
        (
            item
            for item in fourfold.bindings
            if item.source_plane == source_plane
            and item.source_node_id == edge.source
            and item.target_plane == target_plane
            and item.target_node_id == edge.target
            and item.relation == edge.relation
        ),
        None,
    )
    if binding is None or edge_digest not in binding.evidence_sha256s:
        raise ValueError("requested cross-plane Forest edge lacks the exact Fourfold binding")
    return True


def _compile_blocks(
    forest: KnowledgeForest,
    fourfold: FourfoldSnapshot,
) -> dict[str, TypedRelationBlock[bool]]:
    if forest.content_sha256 != fourfold.source_forest_sha256:
        raise ValueError("Forest and Fourfold must describe the same exact subject")
    if fourfold.source_revision != REVISION:
        raise ValueError("Fourfold revision does not match the frozen probe revision")

    planes = _node_planes(fourfold)
    axes = {
        plane.plane: TypedAxis(f"{plane.plane}-node", plane.plane, plane.node_ids)
        for plane in fourfold.planes
        if plane.node_ids
    }
    subject = ProjectionSubject(
        repository_id=fourfold.repository_id,
        source_revision=fourfold.source_revision,
        source_fourfold_sha256=fourfold.digest,
    )
    grouped: dict[str, tuple[RelationSignature, list[tuple[str, str, bool]]]] = {}
    for edge in forest.edges:
        if edge.relation not in RELATIONS:
            continue
        if not edge.directed:
            raise ValueError("probe relation blocks require directed Forest edges")
        try:
            signature = RelationSignature(
                planes[edge.source], edge.relation, planes[edge.target]
            )
        except KeyError as exc:
            raise ValueError("requested Forest edge endpoint is absent from Fourfold") from exc
        previous = grouped.get(edge.relation)
        if previous is None:
            grouped[edge.relation] = (signature, [])
        elif previous[0] != signature:
            raise ValueError("one relation name spans multiple plane signatures")
        grouped[edge.relation][1].append(
            (edge.source, edge.target, _verified_edge_value(edge, fourfold))
        )

    missing = tuple(relation for relation in RELATIONS if relation not in grouped)
    if missing:
        raise ValueError(f"probe subject lacks requested relations: {missing}")

    return {
        relation: TypedRelationBlock.from_coordinates(
            subject=subject,
            signature=signature,
            row_axis=axes[signature.source_plane],
            column_axis=axes[signature.target_plane],
            coordinates=tuple(coordinates),
            semiring=_BOOLEAN,
        )
        for relation, (signature, coordinates) in grouped.items()
    }


def _block_result(block: TypedRelationBlock[bool]) -> tuple[str, ...]:
    return tuple(row for row, _column, value in block.iter_entries() if value is True)


def _query_reference(
    subject: tuple[KnowledgeForest, FourfoldSnapshot, dict[str, TypedRelationBlock[bool]]],
) -> tuple[str, ...]:
    return _block_result(_REFERENCE.evaluate(_PLAN, subject[2]))


def _query_compiled(
    subject: tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        dict[str, TypedRelationBlock[bool]],
        CompiledBooleanContractionPlan,
    ],
) -> tuple[str, ...]:
    return _block_result(subject[3].evaluate())


def compiled_boolean_probe(
    *,
    size: int = 256,
    repeats: int = 2,
    query_iterations: int = 10,
) -> dict[str, Any]:
    reference_forest = _heldout_forest(size)
    reference_fourfold = _fourfold(reference_forest, trace_id="compiled-boolean-cost-probe")

    def build_forest() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _heldout_forest(size)
        return forest, _fourfold(forest, trace_id="compiled-boolean-cost-probe")

    def build_preindexed() -> tuple[KnowledgeForest, FourfoldSnapshot, Any]:
        forest, fourfold = build_forest()
        return forest, fourfold, _heldout_forest_index(forest)

    def build_blocks() -> tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        dict[str, TypedRelationBlock[bool]],
    ]:
        forest, fourfold = build_forest()
        return forest, fourfold, _compile_blocks(forest, fourfold)

    def build_compiled() -> tuple[
        KnowledgeForest,
        FourfoldSnapshot,
        dict[str, TypedRelationBlock[bool]],
        CompiledBooleanContractionPlan,
    ]:
        forest, fourfold, blocks = build_blocks()
        return forest, fourfold, blocks, CompiledBooleanContractionPlan.compile(_PLAN, blocks)

    forest_metrics, forest_result = _measure(
        build_forest,
        lambda subject: _heldout_forest_query(subject[0]),
        repeats=repeats,
        query_iterations=query_iterations,
    )
    preindexed_metrics, preindexed_result = _measure(
        build_preindexed,
        _heldout_preindexed_query,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    reference_metrics, reference_result = _measure(
        build_blocks,
        _query_reference,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    compiled_metrics, compiled_result = _measure(
        build_compiled,
        _query_compiled,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    if not (forest_result == preindexed_result == reference_result == compiled_result):
        raise AssertionError("compiled comparison arm changed the held-out Forest subject")

    return {
        "schema": "daedalus-fused-compiled-boolean-cost-probe/1",
        "authority": "diagnostic-only",
        "claim": "none",
        "probe_spec_sha256": PROBE_SPEC_SHA256,
        "construction_basis": PROBE_SPEC["construction_basis"],
        "compiled_plan_cost": PROBE_SPEC["compiled_plan_cost"],
        "source_forest_sha256": reference_forest.content_sha256,
        "source_fourfold_sha256": reference_fourfold.digest,
        "subject_count": size,
        "node_count": size * 4,
        "edge_count": size * 4,
        "result_count": len(forest_result),
        "result_sha256": hashlib.sha256(
            json.dumps(forest_result, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "arms": {
            "forest_direct": forest_metrics,
            "forest_preindexed": preindexed_metrics,
            "fourfold_boolean_csr_reference": reference_metrics,
            "fourfold_boolean_csr_compiled": compiled_metrics,
        },
    }


def test_compiled_cost_probe_preserves_exact_heldout_subject() -> None:
    result = compiled_boolean_probe(size=32, repeats=1, query_iterations=2)
    assert result["schema"] == "daedalus-fused-compiled-boolean-cost-probe/1"
    assert result["authority"] == "diagnostic-only"
    assert result["claim"] == "none"
    assert result["construction_basis"] == "forest+fourfold"
    assert result["compiled_plan_cost"] == "included in compiled-arm construction"
    assert result["node_count"] == 128
    assert result["edge_count"] == 128
    assert result["result_count"] == 16
    assert set(result["arms"]) == {
        "forest_direct",
        "forest_preindexed",
        "fourfold_boolean_csr_reference",
        "fourfold_boolean_csr_compiled",
    }
