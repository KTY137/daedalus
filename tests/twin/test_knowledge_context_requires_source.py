"""Knowledge may enrich, never replace, source context."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_context_pipeline import (
    build_knowledge_assisted_context,
)
from daedalus.twin.knowledge_correlation import KnowledgeCorrelationError
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def test_existing_target_without_dss_source_context_is_refused() -> None:
    forest, snapshot = _twin()
    corpus = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 1,
                    "title": "Bias",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "body_storage": "<p><code>Event.voltage</code> is required.</p>",
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )

    with pytest.raises(KnowledgeCorrelationError, match="missing source context"):
        build_knowledge_assisted_context(
            receipt_id="no-source-context",
            created_at=CREATED_AT,
            objective="Rename Event.voltage.",
            target_paths=("src/events.py",),
            base_slice_texts={"src/storage.py": "storage only"},
            snapshot=snapshot,
            forest=forest,
            corpus=corpus,
        )

    with pytest.raises(KnowledgeCorrelationError, match="empty or invalid"):
        build_knowledge_assisted_context(
            receipt_id="empty-source-context",
            created_at=CREATED_AT,
            objective="Rename Event.voltage.",
            target_paths=("src/events.py",),
            base_slice_texts={"src/events.py": ""},
            snapshot=snapshot,
            forest=forest,
            corpus=corpus,
        )
