from __future__ import annotations

import hashlib
import weakref

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import relation_compiler
from daedalus.twin.contracts import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.legacy_forest import fourfold_from_knowledge_forest
from daedalus.twin.relation_blocks import RelationSignature
from daedalus.twin.relation_compiler import compile_relation_blocks, relation_block_name
from daedalus.twin.semiring import (
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
)

REVISION = "5" * 40
CREATED_AT = "2026-09-06T19:01:01+02:00"
SIGNATURE = RelationSignature("code", "imports", "code")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _edge(evidence_label: str) -> ForestEdge:
    return ForestEdge(
        source="src/a.py",
        target="src/b.py",
        relation="imports",
        directed=True,
        evidence=(_digest(evidence_label),),
    )


def _fixture() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    forest = KnowledgeForest(
        root=".",
        nodes=(
            ForestNode("src/a.py", "source_file"),
            ForestNode("src/b.py", "source_file"),
        ),
        edges=(_edge("witness-a"), _edge("witness-b")),
        hyperedges=(),
        provenance={
            "origin": "test.relation-compiler-observer-semantics",
            "source_revision": REVISION,
        },
    )
    projected = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=CREATED_AT,
        trace_id="relation-compiler-observer-semantics",
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
                reason="",
            )
            if plane.plane == "code"
            else plane
        )
        for plane in projected.planes
    )
    provenance = ContractProvenance(
        origin="test.relation-compiler-observer-semantics.complete-code",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            *(binding.digest for binding in projected.bindings),
        ),
        trace_id="relation-compiler-observer-semantics-complete-code",
    )
    return forest, FourfoldSnapshot(
        repository_id=projected.repository_id,
        source_revision=projected.source_revision,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=projected.bindings,
        provenance=provenance,
    )


def _single_value(compiled: object) -> object:
    block = compiled.block_map[relation_block_name(SIGNATURE)]  # type: ignore[attr-defined]
    entries = tuple(block.iter_entries())
    assert len(entries) == 1
    assert entries[0][:2] == ("src/a.py", "src/b.py")
    return entries[0][2]


def _require_scalar_fact_boundary_without_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_record_fact = relation_compiler._record_fact

    def guarded_record_fact(
        facts: dict[object, dict[tuple[int, int], object]],
        **kwargs: object,
    ) -> None:
        assert kwargs["evidence_atoms"] is None
        original_record_fact(facts, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "_record_fact", guarded_record_fact)


def test_boolean_observer_collapses_duplicate_witnesses_to_existence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    _require_scalar_fact_boundary_without_evidence(monkeypatch)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        BooleanSemiring(),
        signatures=(SIGNATURE,),
    )

    assert _single_value(compiled) is True
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


def test_natural_observer_counts_semantic_paths_not_ingest_witnesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    _require_scalar_fact_boundary_without_evidence(monkeypatch)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        NaturalSemiring(),
        signatures=(SIGNATURE,),
    )

    assert _single_value(compiled) == 1
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


def test_evidence_observer_retains_alternative_witness_bundles() -> None:
    forest, snapshot = _fixture()

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(SIGNATURE,),
    )

    value = _single_value(compiled)
    assert isinstance(value, EvidenceValue)
    expected = {
        tuple(sorted({canonical_sha(edge.to_dict()), *edge.evidence}))
        for edge in forest.edges
    }
    assert set(value.alternatives) == expected
    assert compiled.semantic_fact_count == 1
    assert compiled.forest_edge_count == 2


def test_evidence_observer_reuses_retained_edge_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    edge_payloads = tuple(edge.to_dict() for edge in forest.edges)
    expected = {
        tuple(sorted({canonical_sha(edge.to_dict()), *edge.evidence}))
        for edge in forest.edges
    }
    original_canonical_sha = relation_compiler.canonical_sha
    edge_hash_calls = 0

    def counting_canonical_sha(value: object) -> str:
        nonlocal edge_hash_calls
        if any(value == payload for payload in edge_payloads):
            edge_hash_calls += 1
        return original_canonical_sha(value)

    monkeypatch.setattr(
        relation_compiler,
        "canonical_sha",
        counting_canonical_sha,
    )

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        EvidenceDagSemiring(),
        signatures=(SIGNATURE,),
    )

    assert edge_hash_calls == len(forest.edges)
    value = _single_value(compiled)
    assert isinstance(value, EvidenceValue)
    assert set(value.alternatives) == expected


def test_forest_edge_evidence_normalizes_at_fact_boundary() -> None:
    witness_a = _digest("boundary-a")
    witness_b = _digest("boundary-b")
    edge = ForestEdge(
        source="src/a.py",
        target="src/b.py",
        relation="imports",
        directed=True,
        evidence=(witness_b, witness_a, witness_b),
    )
    edge_digest = canonical_sha(edge.to_dict())

    facts: dict[RelationSignature, dict[tuple[int, int], object]] = {}
    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=1,
        scalar_value=None,
        evidence_atoms=(edge_digest, *edge.evidence),
    )

    assert facts[SIGNATURE][(0, 1)] == {
        tuple(sorted({edge_digest, witness_a, witness_b}))
    }


class _TrackedDigest(str):
    __slots__ = ("__weakref__",)


@pytest.mark.parametrize("semiring", (BooleanSemiring(), NaturalSemiring()))
def test_scalar_staging_releases_prior_admission_digests_before_fact_materialization(
    monkeypatch: pytest.MonkeyPatch,
    semiring: object,
) -> None:
    forest, snapshot = _fixture()
    edge_payloads = tuple(edge.to_dict() for edge in forest.edges)
    original_canonical_sha = relation_compiler.canonical_sha
    original_record_fact = relation_compiler._record_fact
    digest_refs: list[weakref.ReferenceType[_TrackedDigest]] = []
    live_digest_counts: list[int] = []

    def tracking_canonical_sha(value: object) -> str:
        digest = original_canonical_sha(value)
        if any(value == payload for payload in edge_payloads):
            tracked = _TrackedDigest(digest)
            digest_refs.append(weakref.ref(tracked))
            return tracked
        return digest

    def observing_record_fact(
        facts: dict[object, dict[tuple[int, int], object]],
        **kwargs: object,
    ) -> None:
        if not live_digest_counts:
            live_digest_counts.append(sum(ref() is not None for ref in digest_refs))
        original_record_fact(facts, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(relation_compiler, "canonical_sha", tracking_canonical_sha)
    monkeypatch.setattr(relation_compiler, "_record_fact", observing_record_fact)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        semiring,  # type: ignore[arg-type]
        signatures=(SIGNATURE,),
    )

    assert len(digest_refs) == len(forest.edges)
    assert live_digest_counts
    assert live_digest_counts[0] < len(forest.edges)
    assert _single_value(compiled) in (True, 1)


@pytest.mark.parametrize(
    ("semiring", "expected_value"),
    ((BooleanSemiring(), True), (NaturalSemiring(), 1)),
)
def test_scalar_observer_reuses_final_fact_bucket_for_indexed_block(
    monkeypatch: pytest.MonkeyPatch,
    semiring: object,
    expected_value: object,
) -> None:
    forest, snapshot = _fixture()
    recorded_buckets: list[dict[tuple[int, int], object]] = []
    indexed_entries: list[dict[tuple[int, int], object]] = []
    original_record_fact = relation_compiler._record_fact
    original_from_indexed = relation_compiler.TypedRelationBlock._from_indexed

    def recording_fact(facts: dict[object, dict[tuple[int, int], object]], **kwargs: object) -> None:
        original_record_fact(facts, **kwargs)  # type: ignore[arg-type]
        recorded_buckets.append(facts[kwargs["signature"]])

    def recording_from_indexed(
        cls: type[object],
        subject: object,
        signature: object,
        row_axis: object,
        column_axis: object,
        entries: dict[tuple[int, int], object],
        backend: object,
    ) -> object:
        indexed_entries.append(entries)
        return original_from_indexed(
            subject,
            signature,
            row_axis,
            column_axis,
            entries,
            backend,
        )

    monkeypatch.setattr(relation_compiler, "_record_fact", recording_fact)
    monkeypatch.setattr(
        relation_compiler.TypedRelationBlock,
        "_from_indexed",
        classmethod(recording_from_indexed),
    )

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        semiring,  # type: ignore[arg-type]
        signatures=(SIGNATURE,),
    )

    assert recorded_buckets
    bucket = recorded_buckets[0]
    assert all(recorded is bucket for recorded in recorded_buckets)
    assert indexed_entries == [bucket]
    assert indexed_entries[0] is bucket
    assert tuple(bucket.values()) == (expected_value,)
    assert _single_value(compiled) == expected_value


def test_fact_recording_refuses_before_per_relation_bucket_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(relation_compiler, "MAX_BLOCK_ENTRIES", 1)
    facts: dict[RelationSignature, dict[tuple[int, int], object]] = {}

    relation_compiler._record_fact(
        facts,
        signature=SIGNATURE,
        source_index=0,
        target_index=0,
        scalar_value=True,
        evidence_atoms=None,
    )
    with pytest.raises(ValueError, match="exceeds bounded entry limit 1"):
        relation_compiler._record_fact(
            facts,
            signature=SIGNATURE,
            source_index=0,
            target_index=1,
            scalar_value=True,
            evidence_atoms=None,
        )

    assert facts[SIGNATURE] == {(0, 0): True}


class AlternateNaturalBackend:
    name = "natural"
    zero = 0
    one = 1

    @staticmethod
    def add(left: int, right: int) -> int:
        return left + right

    @staticmethod
    def multiply(left: int, right: int) -> int:
        return left * right


def test_compiler_preserves_protocol_backend_substitution_by_semantic_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forest, snapshot = _fixture()
    _require_scalar_fact_boundary_without_evidence(monkeypatch)

    compiled = compile_relation_blocks(
        forest,
        snapshot,
        AlternateNaturalBackend(),
        signatures=(SIGNATURE,),
    )

    assert compiled.semiring_name == "natural"
    assert _single_value(compiled) == 1