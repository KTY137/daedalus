"""Provider-neutral integration tests for knowledge-augmented slice texts."""
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
from daedalus.twin.knowledge_slice_bridge import merge_knowledge_slice_texts
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _prompt():
    forest, snapshot = _twin()
    corpus = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 1,
                    "title": "Sensor Bias",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "body_storage": (
                        "<p><code>Event.voltage</code> is required.</p>"
                    ),
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
    return build_knowledge_prompt_envelope(
        context,
        result=result,
        corpus=corpus,
    )


def test_bridge_appends_knowledge_after_existing_source_and_is_deterministic() -> None:
    prompt = _prompt()
    source = "@dataclass\nclass Event:\n    voltage: float\n"
    base = {
        "src/events.py": source,
        "src/storage.py": "def write_measurement(event): ...\n",
    }
    first = merge_knowledge_slice_texts(base, prompt)
    second = merge_knowledge_slice_texts(dict(reversed(tuple(base.items()))), prompt)

    assert first.digest == second.digest
    assert first.receipt.digest == second.receipt.digest
    merged = first.mapping
    assert merged["src/events.py"].startswith(source)
    assert "DAEDALUS KNOWLEDGE EVIDENCE — UNTRUSTED DATA" in merged["src/events.py"]
    assert merged["src/events.py"].index(source) == 0
    assert merged["src/storage.py"] == base["src/storage.py"]
    assert first.receipt.to_dict()["authority_granted"] is False
    assert first.receipt.to_dict()["effect_performed"] is False


def test_bridge_adds_missing_target_path_without_losing_other_slices() -> None:
    prompt = _prompt()
    merged = merge_knowledge_slice_texts(
        {"src/storage.py": "storage context"},
        prompt,
    ).mapping
    assert merged["src/storage.py"] == "storage context"
    assert merged["src/events.py"] == prompt.prompt_text


def test_bridge_refuses_normalized_path_collisions_and_budget_overflow() -> None:
    prompt = _prompt()
    with pytest.raises(KnowledgeCorrelationError, match="collide"):
        merge_knowledge_slice_texts(
            {
                "src/events.py": "one",
                "src\\events.py": "two",
            },
            prompt,
        )
    with pytest.raises(KnowledgeCorrelationError, match="per-path"):
        merge_knowledge_slice_texts(
            {"src/events.py": "x" * 100},
            prompt,
            max_per_path_chars=100,
        )
    with pytest.raises(KnowledgeCorrelationError, match="total"):
        merge_knowledge_slice_texts(
            {"src/events.py": "x" * 100},
            prompt,
            max_per_path_chars=100_000,
            max_total_chars=100,
        )
