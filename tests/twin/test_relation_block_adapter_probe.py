from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path
from typing import Any

import pytest

from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, KnowledgeForest
from daedalus.twin import FourfoldSnapshot
from daedalus.twin.contractions import (
    BlockRef,
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
from daedalus.twin.semiring import BooleanSemiring, EvidenceDagSemiring, EvidenceValue

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
    "name": "fourfold-relation-block-adapter",
    "version": 1,
    "relations": RELATIONS,
    "comparison": "direct Forest vs four independent dict indices vs verified typed CSR blocks",
    "construction_basis": "forest+fourfold",
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
_BOOLEAN_INTERPRETER = ReferenceContractionInterpreter(_BOOLEAN)
_EVIDENCE = EvidenceDagSemiring()
_EVIDENCE_INTERPRETER = ReferenceContractionInterpreter(_EVIDENCE)


def _node_planes(fourfold: FourfoldSnapshot) -> dict[str, str]:
    return {
        node_id: plane.plane
        for plane in fourfold.planes
        for node_id in plane.node_ids
    }


def _verified_edge_value(
    edge: ForestEdge,
    fourfold: FourfoldSnapshot,
    *,
    evidence: bool,
) -> bool | EvidenceValue:
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
        return EvidenceValue.atom(edge_digest) if evidence else True

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
    if evidence:
        return EvidenceValue((tuple(binding.evidence_sha256s),))
    return True


def _compile_blocks(
    forest: KnowledgeForest,
    fourfold: FourfoldSnapshot,
    *,
    evidence: bool = False,
) -> dict[str, TypedRelationBlock[Any]]:
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
    grouped: dict[str, tuple[RelationSignature, list[tuple[str, str, Any]]]] = {}
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
            (
                edge.source,
                edge.target,
                _verified_edge_value(edge, fourfold, evidence=evidence),
            )
        )

    missing = tuple(relation for relation in RELATIONS if relation not in grouped)
    if missing:
        raise ValueError(f"probe subject lacks requested relations: {missing}")

    semiring = _EVIDENCE if evidence else _BOOLEAN
    return {
        relation: TypedRelationBlock.from_coordinates(
            subject=subject,
            signature=signature,
            row_axis=axes[signature.source_plane],
            column_axis=axes[signature.target_plane],
            coordinates=tuple(coordinates),
            semiring=semiring,
        )
        for relation, (signature, coordinates) in grouped.items()
    }


def _query_boolean_blocks(
    subject: tuple[KnowledgeForest, FourfoldSnapshot, dict[str, TypedRelationBlock[Any]]],
) -> tuple[str, ...]:
    result = _BOOLEAN_INTERPRETER.evaluate(_PLAN, subject[2])
    return tuple(row for row, _column, value in result.iter_entries() if value is True)


def relation_block_probe(
    *,
    size: int = 256,
    repeats: int = 2,
    query_iterations: int = 10,
) -> dict[str, Any]:
    reference_forest = _heldout_forest(size)
    reference_fourfold = _fourfold(reference_forest, trace_id="relation-block-adapter-probe")

    def build_forest() -> tuple[KnowledgeForest, FourfoldSnapshot]:
        forest = _heldout_forest(size)
        return forest, _fourfold(forest, trace_id="relation-block-adapter-probe")

    def build_preindexed() -> tuple[KnowledgeForest, FourfoldSnapshot, Any]:
        forest, fourfold = build_forest()
        return forest, fourfold, _heldout_forest_index(forest)

    def build_blocks() -> tuple[KnowledgeForest, FourfoldSnapshot, dict[str, TypedRelationBlock[Any]]]:
        forest, fourfold = build_forest()
        return forest, fourfold, _compile_blocks(forest, fourfold)

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
    algebra_metrics, algebra_result = _measure(
        build_blocks,
        _query_boolean_blocks,
        repeats=repeats,
        query_iterations=query_iterations,
    )
    if forest_result != preindexed_result or forest_result != algebra_result:
        raise AssertionError("relation-block adapter changed the held-out Forest subject")

    return {
        "schema": "daedalus-fourfold-relation-block-adapter-probe/1",
        "authority": "diagnostic-only",
        "claim": "none",
        "probe_spec_sha256": PROBE_SPEC_SHA256,
        "construction_basis": PROBE_SPEC["construction_basis"],
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
            "fourfold_boolean_csr": algebra_metrics,
        },
    }


def test_adapter_preserves_exact_heldout_subject_and_fourfold_binding() -> None:
    result = relation_block_probe(size=64, repeats=1, query_iterations=2)
    assert result["schema"] == "daedalus-fourfold-relation-block-adapter-probe/1"
    assert result["authority"] == "diagnostic-only"
    assert result["claim"] == "none"
    assert result["construction_basis"] == "forest+fourfold"
    assert result["node_count"] == 256
    assert result["edge_count"] == 256
    assert result["result_count"] == 32
    assert set(result["arms"]) == {
        "forest_direct",
        "forest_preindexed",
        "fourfold_boolean_csr",
    }


def test_evidence_semiring_composes_exact_fourfold_receipts() -> None:
    forest = _heldout_forest(8)
    fourfold = _fourfold(forest, trace_id="relation-block-evidence-probe")
    blocks = _compile_blocks(forest, fourfold, evidence=True)
    result = _EVIDENCE_INTERPRETER.evaluate(_PLAN, blocks)

    entries = tuple(result.iter_entries())
    assert len(entries) == 4
    for _source, _type_id, value in entries:
        assert isinstance(value, EvidenceValue)
        assert value.alternatives
        assert all(fourfold.source_forest_sha256 in term for term in value.alternatives)


def test_adapter_refuses_cross_revision_subject() -> None:
    forest = _heldout_forest(4)
    fourfold = _fourfold(forest, trace_id="relation-block-revision-probe")
    object.__setattr__(fourfold, "source_revision", "c" * 40)
    with pytest.raises(ValueError, match="frozen probe revision"):
        _compile_blocks(forest, fourfold)
