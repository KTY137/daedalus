# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin import fourfold_from_knowledge_forest

REVISION = "a" * 40
NOW = "2026-08-01T10:00:00Z"


def _forest(*, evidence: tuple[str, ...]) -> KnowledgeForest:
    return KnowledgeForest(
        root="/repo",
        nodes=(
            ForestNode("src/app.py", "source_file", {}),
            ForestNode("type:src/app.py#Config", "type", {}),
        ),
        edges=(
            ForestEdge(
                "src/app.py",
                "type:src/app.py#Config",
                "produces",
                True,
                evidence=evidence,
            ),
        ),
        hyperedges=(),
        provenance={"source_schema": "test"},
    )


def test_legacy_adapter_refuses_unevidenced_cross_plane_edge() -> None:
    with pytest.raises(ValueError, match="no retained evidence"):
        fourfold_from_knowledge_forest(
            _forest(evidence=()),
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            created_at=NOW,
        )


def test_verified_legacy_binding_retains_forest_and_edge_identity() -> None:
    forest = _forest(evidence=("structcore.type_edges",))
    snapshot = fourfold_from_knowledge_forest(
        forest,
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        created_at=NOW,
    )

    assert len(snapshot.bindings) == 1
    binding = snapshot.bindings[0]
    assert binding.assurance == "verified"
    assert forest.content_sha256 in binding.evidence_sha256s
    assert len(binding.evidence_sha256s) == 2
