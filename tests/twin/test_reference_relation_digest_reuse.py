from __future__ import annotations

from pathlib import Path

import daedalus.twin.reference_compiler as reference_compiler
import daedalus.twin.relation_compiler as relation_compiler
from daedalus.spine.envelope import canonical_sha as canonical_sha_impl
from daedalus.twin.semiring import BooleanSemiring


REVISION = "d" * 40
NOW = "2026-09-09T02:00:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
_EDGE_PAYLOAD_KEYS = frozenset(
    {"source", "target", "relation", "directed", "weight", "evidence", "attributes"}
)


def _is_edge_payload(value: object) -> bool:
    return isinstance(value, dict) and frozenset(value) == _EDGE_PAYLOAD_KEYS


def test_reference_compile_reuses_edge_digest_for_fourfold_membership(monkeypatch) -> None:
    edge_payload_hashes = 0

    def counting_canonical_sha(value):
        nonlocal edge_payload_hashes
        if _is_edge_payload(value):
            edge_payload_hashes += 1
        return canonical_sha_impl(value)

    monkeypatch.setattr(reference_compiler, "canonical_sha", counting_canonical_sha)

    result = reference_compiler.compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-reference-relation-digest-reuse",
    )

    retained_same_plane_relations = sum(
        len(plane.relation_sha256s) for plane in result.snapshot.planes
    )
    assert retained_same_plane_relations > 0
    assert edge_payload_hashes == len(result.forest.edges)
    assert result.snapshot.source_forest_sha256 == result.forest.content_sha256


def test_reference_to_relation_projection_rehashes_same_plane_edges_at_authority_boundary(
    monkeypatch,
) -> None:
    producer_edge_digests: list[str] = []
    consumer_edge_digests: list[str] = []

    def counting_reference_sha(value):
        digest = canonical_sha_impl(value)
        if _is_edge_payload(value):
            producer_edge_digests.append(digest)
        return digest

    def counting_relation_sha(value):
        digest = canonical_sha_impl(value)
        if _is_edge_payload(value):
            consumer_edge_digests.append(digest)
        return digest

    monkeypatch.setattr(reference_compiler, "canonical_sha", counting_reference_sha)
    monkeypatch.setattr(relation_compiler, "canonical_sha", counting_relation_sha)

    result = reference_compiler.compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-reference-relation-authority-boundary",
    )
    compiled = relation_compiler.compile_relation_blocks(
        result.forest,
        result.snapshot,
        BooleanSemiring(),
    )

    node_plane = {
        node_id: plane.plane
        for plane in result.snapshot.planes
        for node_id in plane.node_ids
    }
    same_plane_edges = tuple(
        edge
        for edge in result.forest.edges
        if node_plane[edge.source] == node_plane[edge.target]
    )
    retained_relation_digests = {
        digest
        for plane in result.snapshot.planes
        for digest in plane.relation_sha256s
    }

    assert same_plane_edges
    assert retained_relation_digests
    assert len(producer_edge_digests) == len(result.forest.edges)
    assert len(consumer_edge_digests) == len(same_plane_edges)
    assert set(consumer_edge_digests) == retained_relation_digests
    assert all(digest in producer_edge_digests for digest in consumer_edge_digests)
    assert compiled.source_forest_sha256 == result.snapshot.source_forest_sha256
