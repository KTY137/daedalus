from __future__ import annotations

from pathlib import Path

import daedalus.twin.reference_compiler as reference_compiler
from daedalus.spine.envelope import canonical_sha as canonical_sha_impl


REVISION = "d" * 40
NOW = "2026-09-09T02:00:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
_EDGE_PAYLOAD_KEYS = frozenset(
    {"source", "target", "relation", "directed", "weight", "evidence", "attributes"}
)


def test_reference_compile_reuses_edge_digest_for_fourfold_membership(monkeypatch) -> None:
    edge_payload_hashes = 0

    def counting_canonical_sha(value):
        nonlocal edge_payload_hashes
        if isinstance(value, dict) and frozenset(value) == _EDGE_PAYLOAD_KEYS:
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
