from __future__ import annotations

import hashlib
import inspect

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature, TypedAxis, TypedRelationBlock
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "8" * 40
CREATED_AT = "2026-09-09T20:57:28+02:00"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _edge(source: str, target: str, relation: str) -> ForestEdge:
    return ForestEdge(
        source=source,
        target=target,
        relation=relation,
        directed=True,
        evidence=(_digest(f"{relation}:{source}:{target}"),),
    )


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("src/worker.py", "source_file"),
            ForestNode("type:Event", "type"),
            ForestNode("docs/architecture.md", "document"),
        ),
        edges=(
            _edge("src/api.py", "src/worker.py", "imports"),
            _edge("src/worker.py", "type:Event", "declares"),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-axis-scope",
            "source_revision": REVISION,
        },
    )
    legacy = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-axis-scope",
    )
    planes = tuple(
        (
            PlaneSnapshot(
                plane=plane.plane,
                source_revision=plane.source_revision,
                status="complete",
                node_ids=plane.node_ids,
                relation_sha256s=plane.relation_sha256s,
                evidence_sha256s=plane.evidence_sha256s,
                reason=None,
            )
            if plane.plane in {"code", "type"}
            else plane
        )
        for plane in legacy.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-axis-scope.complete-endpoints",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in legacy.bindings),
        ),
        trace_id="relation-compiler-axis-scope-complete",
    )
    snapshot = FourfoldSnapshot(
        repository_id=legacy.repository_id,
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=legacy.bindings,
        provenance=provenance,
    )
    return forest, snapshot


def _track_axes(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    observed: list[str] = []

    def tracking_axis(*args: object, **kwargs: object) -> TypedAxis:
        plane = kwargs.get("plane")
        if not isinstance(plane, str):
            raise AssertionError("compiler stopped constructing TypedAxis with named plane")
        observed.append(plane)
        return TypedAxis(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "TypedAxis", tracking_axis)
    return observed


def _track_retained_digest_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, ...]]:
    observed: list[tuple[str, ...]] = []
    builtin_frozenset = frozenset

    def tracking_frozenset(values: object = ()) -> frozenset[object]:
        materialized = tuple(values)  # type: ignore[arg-type]
        observed.append(materialized)  # type: ignore[arg-type]
        return builtin_frozenset(materialized)

    monkeypatch.setattr(relation_compiler, "frozenset", tracking_frozenset, raising=False)
    return observed


def test_explicit_same_plane_compile_constructs_only_its_endpoint_axis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    observed_axes = _track_axes(monkeypatch)
    observed_digest_sets = _track_retained_digest_sets(monkeypatch)
    signature = RelationSignature("code", "imports", "code")
    code_plane = next(plane for plane in snapshot.planes if plane.plane == "code")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(signature,),
    )

    assert observed_axes == ["code"]
    assert observed_digest_sets == [tuple(code_plane.relation_sha256s)]
    assert tuple(compiled.block_map) == (relation_block_name(signature),)
    assert tuple(compiled.block_map[relation_block_name(signature)].iter_entries()) == (
        ("src/api.py", "src/worker.py", True),
    )


def test_explicit_cross_plane_compile_constructs_only_selected_endpoint_axes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    observed_axes = _track_axes(monkeypatch)
    observed_digest_sets = _track_retained_digest_sets(monkeypatch)
    signature = RelationSignature("code", "declares", "type")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(signature,),
    )

    assert observed_axes == ["code", "type"]
    assert observed_digest_sets == []
    assert tuple(compiled.block_map) == (relation_block_name(signature),)
    assert tuple(compiled.block_map[relation_block_name(signature)].iter_entries()) == (
        ("src/worker.py", "type:Event", True),
    )


def test_compiler_reuses_validated_partition_map_for_canonical_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    real_partition = relation_compiler._forest_node_partition
    observed: TrackingPartition | None = None

    class TrackingPartition(dict[str, object]):
        def __init__(self, initial: dict[str, str]) -> None:
            super().__init__(initial)
            self.writes: list[tuple[str, object]] = []

        def __setitem__(self, key: str, value: object) -> None:
            self.writes.append((key, value))
            super().__setitem__(key, value)

    def tracking_partition(
        candidate_forest: KnowledgeForest,
        candidate_snapshot: FourfoldSnapshot,
    ) -> dict[str, object]:
        nonlocal observed
        observed = TrackingPartition(real_partition(candidate_forest, candidate_snapshot))
        return observed

    monkeypatch.setattr(relation_compiler, "_forest_node_partition", tracking_partition)
    signature = RelationSignature("code", "imports", "code")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(signature,),
    )

    assert observed is not None
    assert observed.writes == [
        (node_id, (plane.plane, position))
        for plane in snapshot.planes
        for position, node_id in enumerate(plane.node_ids)
    ]
    assert tuple(compiled.block_map[relation_block_name(signature)].iter_entries()) == (
        ("src/api.py", "src/worker.py", True),
    )


def test_compiler_releases_consumed_staging_before_csr_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    imports = RelationSignature("code", "imports", "code")
    declares = RelationSignature("code", "declares", "type")
    original_from_indexed = TypedRelationBlock._from_indexed.__func__
    observed_signatures: list[RelationSignature] = []
    remaining_fact_counts: list[int] = []

    def inspecting_from_indexed(
        cls: type[TypedRelationBlock[object]],
        *args: object,
        **kwargs: object,
    ) -> TypedRelationBlock[object]:
        signature = args[1]
        assert isinstance(signature, RelationSignature)
        frame = inspect.currentframe()
        assert frame is not None and frame.f_back is not None
        compiler_locals = frame.f_back.f_locals
        assert compiler_locals["edge_records"] == []
        assert compiler_locals["binding_records_by_key"] == {}
        facts = compiler_locals["facts"]
        assert isinstance(facts, dict)
        assert signature not in facts
        observed_signatures.append(signature)
        remaining_fact_counts.append(len(facts))
        return original_from_indexed(cls, *args, **kwargs)  # type: ignore[arg-type, return-value]

    monkeypatch.setattr(
        TypedRelationBlock,
        "_from_indexed",
        classmethod(inspecting_from_indexed),
    )

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(imports, declares),
    )

    assert observed_signatures == [declares, imports]
    assert remaining_fact_counts == [1, 0]
    assert compiled.semantic_fact_count == 2
    assert tuple(compiled.block_map[relation_block_name(imports)].iter_entries()) == (
        ("src/api.py", "src/worker.py", True),
    )
    assert tuple(compiled.block_map[relation_block_name(declares)].iter_entries()) == (
        ("src/worker.py", "type:Event", True),
    )
