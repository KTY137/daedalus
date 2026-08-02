"""Constructor-level anti-repackaging tests for merged provider slices."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_access import build_access_scoped_context
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    correlate_knowledge,
)
from daedalus.twin.knowledge_prompt import build_knowledge_prompt_envelope
from daedalus.twin.knowledge_slice_bridge import (
    KnowledgeAugmentedSlices,
    merge_knowledge_slice_texts,
)
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _augmented():
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
    policy = CorrelationPolicy(min_proposal_score=0.58)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=policy,
    )
    context = build_access_scoped_context(
        result,
        snapshot=snapshot,
        corpus=corpus,
        objective="Rename Event.voltage.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        correlation_policy=policy,
    )
    prompt = build_knowledge_prompt_envelope(
        context,
        result=result,
        corpus=corpus,
    )
    return merge_knowledge_slice_texts(
        {"src/events.py": "class Event:\n    voltage: float\n"},
        prompt,
    )


def test_augmented_slices_refuse_text_and_path_repackaging() -> None:
    augmented = _augmented()
    rows = dict(augmented.slice_texts)
    rows["src/events.py"] += "\nMALICIOUS REPACKAGING"
    with pytest.raises(KnowledgeCorrelationError, match="digest"):
        KnowledgeAugmentedSlices(
            slice_texts=tuple(rows.items()),
            receipt=augmented.receipt,
        )

    with pytest.raises(KnowledgeCorrelationError, match="digest|paths"):
        KnowledgeAugmentedSlices(
            slice_texts=tuple(
                row for row in augmented.slice_texts if row[0] != "src/events.py"
            ),
            receipt=augmented.receipt,
        )
