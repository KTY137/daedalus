"""End-of-context-chain receipt regressions."""
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
from daedalus.twin.knowledge_provider_receipt import (
    build_knowledge_provider_context_receipt,
)
from daedalus.twin.knowledge_receipt import build_knowledge_attempt_context_receipt
from daedalus.twin.knowledge_slice_bridge import merge_knowledge_slice_texts
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _chain(page_id: str):
    forest, snapshot = _twin()
    corpus = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": page_id,
                    "version": 1,
                    "title": "Sensor Bias",
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
    knowledge_receipt = build_knowledge_attempt_context_receipt(
        receipt_id=f"attempt-{page_id}",
        created_at=CREATED_AT,
        snapshot=snapshot,
        corpus=corpus,
        correlation_policy=policy,
        result=result,
        access_policy=context.policy,
        context=context,
        prompt=prompt,
    )
    augmented = merge_knowledge_slice_texts(
        {
            "src/events.py": (
                "@dataclass\nclass Event:\n    voltage: float\n"
            )
        },
        prompt,
    )
    return knowledge_receipt, augmented


def test_provider_receipt_binds_exact_merged_context_and_grants_nothing() -> None:
    knowledge_receipt, augmented = _chain("1")
    receipt = build_knowledge_provider_context_receipt(
        knowledge_receipt,
        augmented,
    )
    replay = build_knowledge_provider_context_receipt(
        knowledge_receipt,
        augmented,
    )

    assert receipt.digest == replay.digest
    assert receipt.provider_context_sha256 == augmented.digest
    assert receipt.slice_bridge_receipt_sha256 == augmented.receipt.digest
    assert receipt.target_paths == ("src/events.py",)
    assert receipt.merged_chars == augmented.receipt.merged_chars
    body = receipt.to_dict()
    assert body["model_invocation_claimed"] is False
    assert body["effect_performed"] is False
    assert body["authority_granted"] is False


def test_provider_receipt_refuses_prompt_substitution() -> None:
    knowledge_receipt, _ = _chain("1")
    _, foreign_augmented = _chain("2")

    with pytest.raises(KnowledgeCorrelationError, match="does not bind"):
        build_knowledge_provider_context_receipt(
            knowledge_receipt,
            foreign_augmented,
        )
