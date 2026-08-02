"""Evidence-chain regressions for knowledge-assisted coding attempts."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_access import (
    KnowledgeAccessPolicy,
    build_access_scoped_context,
)
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    correlate_knowledge,
)
from daedalus.twin.knowledge_prompt import build_knowledge_prompt_envelope
from daedalus.twin.knowledge_receipt import build_knowledge_attempt_context_receipt
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _chain(*, page_id: str = "1", access: tuple[str, ...] = ("internal",)):
    forest, snapshot = _twin()
    corpus = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": page_id,
                    "version": 2,
                    "title": "Sensor Bias",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "access_class": "internal",
                    "body_storage": (
                        "<p><code>Event.voltage</code> is required.</p>"
                    ),
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    correlation_policy = CorrelationPolicy(min_proposal_score=0.58)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=correlation_policy,
    )
    access_policy = KnowledgeAccessPolicy(allowed_access_classes=access)
    context = build_access_scoped_context(
        result,
        snapshot=snapshot,
        corpus=corpus,
        objective="Rename Event.voltage to Event.bias_voltage.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        access_policy=access_policy,
        correlation_policy=correlation_policy,
    )
    prompt = build_knowledge_prompt_envelope(
        context,
        result=result,
        corpus=corpus,
    )
    return (
        snapshot,
        corpus,
        correlation_policy,
        result,
        access_policy,
        context,
        prompt,
    )


def test_knowledge_attempt_receipt_is_replay_identical_and_grants_nothing() -> None:
    chain = _chain()
    kwargs = dict(
        receipt_id="knowledge-attempt-1",
        created_at=CREATED_AT,
        snapshot=chain[0],
        corpus=chain[1],
        correlation_policy=chain[2],
        result=chain[3],
        access_policy=chain[4],
        context=chain[5],
        prompt=chain[6],
    )
    first = build_knowledge_attempt_context_receipt(**kwargs)
    second = build_knowledge_attempt_context_receipt(**kwargs)

    assert first.digest == second.digest
    assert first.prompt_payload_sha256 == chain[6].payload_sha256
    assert first.target_paths == ("src/events.py",)
    body = first.to_dict()
    assert body["authority_granted"] is False
    assert body["verification_claimed"] is False
    assert body["gate_closure_claimed"] is False


def test_receipt_refuses_corpus_policy_and_context_substitution() -> None:
    chain = _chain()
    foreign = _chain(page_id="2")

    with pytest.raises(KnowledgeCorrelationError, match="result/corpus"):
        build_knowledge_attempt_context_receipt(
            receipt_id="substitute-corpus",
            created_at=CREATED_AT,
            snapshot=chain[0],
            corpus=foreign[1],
            correlation_policy=chain[2],
            result=chain[3],
            access_policy=chain[4],
            context=chain[5],
            prompt=chain[6],
        )

    broader_policy = KnowledgeAccessPolicy(
        allowed_access_classes=("public", "internal")
    )
    with pytest.raises(KnowledgeCorrelationError, match="access policy"):
        build_knowledge_attempt_context_receipt(
            receipt_id="substitute-policy",
            created_at=CREATED_AT,
            snapshot=chain[0],
            corpus=chain[1],
            correlation_policy=chain[2],
            result=chain[3],
            access_policy=broader_policy,
            context=chain[5],
            prompt=chain[6],
        )

    with pytest.raises(KnowledgeCorrelationError, match="prompt/context"):
        build_knowledge_attempt_context_receipt(
            receipt_id="substitute-prompt",
            created_at=CREATED_AT,
            snapshot=chain[0],
            corpus=chain[1],
            correlation_policy=chain[2],
            result=chain[3],
            access_policy=chain[4],
            context=chain[5],
            prompt=foreign[6],
        )
