from __future__ import annotations

from collections.abc import Iterator, Sequence
import hashlib

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.structcore.forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
)
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import BooleanSemiring

REVISION = "4" * 40
CREATED_AT = "2026-09-06T11:00:00+02:00"


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


def _with_plane_statuses(
    forest: KnowledgeForest,
    snapshot: FourfoldSnapshot,
    statuses: dict[str, str],
) -> FourfoldSnapshot:
    planes = tuple(
        (
            PlaneSnapshot(
                plane=plane.plane,
                source_revision=plane.source_revision,
                status=statuses[plane.plane],
                node_ids=plane.node_ids,
                relation_sha256s=plane.relation_sha256s,
                evidence_sha256s=plane.evidence_sha256s,
                reason=(
                    "test fixture intentionally incomplete"
                    if statuses[plane.plane] == "partial"
                    else ""
                ),
            )
            if plane.plane in statuses
            else plane
        )
        for plane in snapshot.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-selected-pruning.status-fixture",
        source_revision=snapshot.source_revision,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in snapshot.bindings),
        ),
        trace_id="relation-compiler-selected-pruning-status",
    )
    return FourfoldSnapshot(
        repository_id=snapshot.repository_id,
        source_revision=snapshot.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=snapshot.bindings,
        provenance=provenance,
    )


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/api.py", "source_file"),
            ForestNode("src/worker.py", "source_file"),
            ForestNode("type:Event", "type"),
        ),
        edges=(
            _edge("src/api.py", "src/worker.py", "imports"),
            _edge("src/worker.py", "type:Event", "declares"),
        ),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-selected-pruning",
            "source_revision": REVISION,
        },
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-selected-pruning",
    )
    return forest, _with_plane_statuses(
        forest,
        snapshot,
        {"code": "complete", "type": "complete"},
    )


def _fixture_with_hyperedge() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest, _ = _fixture()
    forest = KnowledgeForest(
        root=forest.root,
        nodes=forest.nodes,
        edges=forest.edges,
        hyperedges=(
            ForestHyperedge(
                id="clone_exact:fixture",
                relation="clone_exact",
                members=("src/api.py", "src/worker.py"),
                evidence=(_digest("clone_exact:fixture"),),
            ),
        ),
        provenance=forest.provenance,
    )
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-selected-pruning-hyperedge",
    )
    return forest, _with_plane_statuses(
        forest,
        snapshot,
        {"code": "complete", "type": "complete"},
    )


class _DeclaredSignatureCatalog(Sequence[RelationSignature]):
    def __init__(self, signature: RelationSignature) -> None:
        self._signature = signature

    def __len__(self) -> int:
        return 1

    def __getitem__(self, index: int) -> RelationSignature:
        if index == 0:
            return self._signature
        raise IndexError(index)

    def __iter__(self) -> Iterator[RelationSignature]:
        raise AssertionError("declared signature catalog iterator was consumed")


class _UnboundedSignatures:
    def __iter__(self) -> Iterator[RelationSignature]:
        raise AssertionError("unbounded signature iterable was consumed")


def test_explicit_signature_prunes_unselected_evidence_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "declares", "type")
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def guarded_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        if edge.relation != "declares":
            raise AssertionError("unselected Forest evidence was materialized")
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", guarded_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert observed_relations == ["declares"]
    assert tuple(compiled.block_map) == (relation_block_name(selected),)
    assert tuple(compiled.block_map[relation_block_name(selected)].iter_entries()) == (
        ("src/worker.py", "type:Event", True),
    )
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.forest_hyperedge_count == 0
    assert compiled.verified_binding_count == len(snapshot.bindings)


def test_explicit_signature_prunes_unselected_verified_binding_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "imports", "code")
    observed_signatures: list[RelationSignature] = []
    original = relation_compiler._record_fact

    def guarded_record_fact(*args: object, **kwargs: object) -> None:
        signature = kwargs.get("signature")
        if not isinstance(signature, RelationSignature):
            raise AssertionError("relation fact did not carry a typed signature")
        observed_signatures.append(signature)
        if signature != selected:
            raise AssertionError("unselected verified-binding fact was materialized")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "_record_fact", guarded_record_fact)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert observed_signatures == [selected]
    assert tuple(compiled.block_map) == (relation_block_name(selected),)
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.forest_hyperedge_count == 0
    assert compiled.verified_binding_count == len(snapshot.bindings)


def test_explicit_signature_contract_is_validated_before_edge_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="RelationSignature records"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(object(),),  # type: ignore[arg-type]
        )


def test_explicit_signature_catalog_materializes_declared_cardinality_only() -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "imports", "code")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=_DeclaredSignatureCatalog(selected),
    )

    assert tuple(compiled.block_map) == (relation_block_name(selected),)


def test_explicit_signature_catalog_rejects_unbounded_iterable_before_consumption() -> None:
    forest, snapshot = _fixture()

    with pytest.raises(ValueError, match="signatures must be a bounded sequence"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=_UnboundedSignatures(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("flag", (0, 1, None, "false"))
def test_verified_binding_inclusion_policy_requires_exact_boolean(
    flag: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="include_verified_bindings must be boolean"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            include_verified_bindings=flag,  # type: ignore[arg-type]
        )


def test_verified_binding_false_skips_binding_fact_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "declares", "type")
    observed_signatures: list[RelationSignature] = []
    original = relation_compiler._record_fact

    def recording_record_fact(*args: object, **kwargs: object) -> None:
        signature = kwargs.get("signature")
        if not isinstance(signature, RelationSignature):
            raise AssertionError("relation fact did not carry a typed signature")
        observed_signatures.append(signature)
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "_record_fact", recording_record_fact)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
        include_verified_bindings=False,
    )

    assert observed_signatures == [selected]
    assert compiled.semantic_fact_count == 1
    assert compiled.verified_binding_count == 0


@pytest.mark.parametrize(
    "signatures",
    ((RelationSignature("code", "declares", "type"),), None),
)
def test_selected_relation_requires_complete_endpoint_planes_before_materialization(
    signatures: tuple[RelationSignature, ...] | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    snapshot = _with_plane_statuses(forest, snapshot, {"type": "partial"})

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="type=partial"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=signatures,
        )


def test_explicit_complete_relation_ignores_unselected_partial_plane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    snapshot = _with_plane_statuses(forest, snapshot, {"type": "partial"})
    selected = RelationSignature("code", "imports", "code")
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def guarded_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        if edge.relation != "imports":
            raise AssertionError("unselected partial-plane evidence was materialized")
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", guarded_atoms)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert observed_relations == ["imports"]
    assert tuple(compiled.block_map) == (relation_block_name(selected),)


def test_predeclared_empty_relation_refuses_absent_endpoint_before_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    selected = RelationSignature("code", "feeds", "data")

    def forbidden_atoms(edge: ForestEdge) -> tuple[str, ...]:
        raise AssertionError(f"unexpected materialization of {edge.relation}")

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", forbidden_atoms)

    with pytest.raises(ValueError, match="data=absent"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(selected,),
        )


def test_discover_all_keeps_existing_forest_materialization_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    observed_relations: list[str] = []
    original = relation_compiler._forest_edge_atoms

    def recording_atoms(edge: ForestEdge) -> tuple[str, ...]:
        observed_relations.append(edge.relation)
        return original(edge)

    monkeypatch.setattr(relation_compiler, "_forest_edge_atoms", recording_atoms)

    compiled = compile_relation_blocks(forest, snapshot, BooleanSemiring())

    assert observed_relations == ["imports", "declares"]
    assert set(compiled.block_map) == {
        "code:imports:code",
        "code:declares:type",
    }
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.forest_hyperedge_count == 0
    assert compiled.verified_binding_count == len(snapshot.bindings)


def test_discover_all_refuses_retained_hyperedge_instead_of_lossy_omission() -> None:
    forest, snapshot = _fixture_with_hyperedge()

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        compile_relation_blocks(forest, snapshot, BooleanSemiring())


def test_explicit_matching_relation_refuses_retained_hyperedge() -> None:
    forest, snapshot = _fixture_with_hyperedge()
    selected = RelationSignature("code", "clone_exact", "code")

    with pytest.raises(ValueError, match="cannot flatten a retained ForestHyperedge"):
        compile_relation_blocks(
            forest,
            snapshot,
            BooleanSemiring(),
            signatures=(selected,),
        )


def test_explicit_unrelated_relation_can_skip_retained_hyperedge() -> None:
    forest, snapshot = _fixture_with_hyperedge()
    selected = RelationSignature("code", "imports", "code")

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(selected,),
    )

    assert tuple(compiled.block_map) == (relation_block_name(selected),)
    assert tuple(compiled.block_map[relation_block_name(selected)].iter_entries()) == (
        ("src/api.py", "src/worker.py", True),
    )
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == len(forest.edges)
    assert compiled.forest_hyperedge_count == len(forest.hyperedges) == 1
    assert compiled.to_dict()["forest_hyperedge_count"] == 1
