"""Policy- and soft-provider-binding regressions for correlation runs."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_access import build_access_scoped_context
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
)
from daedalus.twin.knowledge_prompt import build_knowledge_prompt_envelope
from daedalus.twin.knowledge_run import (
    build_attempt_receipt_from_correlation_run,
    run_knowledge_correlation,
)
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


class _SoftProvider:
    def score(self, *, claim, document, card):  # noqa: ANN001
        if card.node_id.endswith("Event.voltage"):
            return 0.9, "e" * 64
        return None


def _inputs():
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
                    "body_storage": "<p><code>Event.voltage</code> is required.</p>",
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    return forest, snapshot, corpus


def test_correlation_run_binds_policy_and_is_replay_identical() -> None:
    forest, snapshot, corpus = _inputs()
    policy = CorrelationPolicy(min_proposal_score=0.58)
    first = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=policy,
    )
    replay = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=policy,
    )
    stricter = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.9),
    )

    assert first.digest == replay.digest
    assert first.receipt.digest == replay.receipt.digest
    assert first.receipt.result_sha256 == first.result.digest
    assert first.receipt.correlation_policy_sha256 != (
        stricter.receipt.correlation_policy_sha256
    )
    assert first.digest != stricter.digest
    body = first.receipt.to_dict()
    assert body["authority_granted"] is False
    assert body["verification_claimed"] is False
    assert body["gate_closure_claimed"] is False


def test_soft_provider_requires_and_binds_manifest_digest() -> None:
    forest, snapshot, corpus = _inputs()
    provider = _SoftProvider()
    with pytest.raises(KnowledgeCorrelationError, match="supplied together"):
        run_knowledge_correlation(
            snapshot=snapshot,
            forest=forest,
            corpus=corpus,
            soft_signal_provider=provider,
        )
    with pytest.raises(KnowledgeCorrelationError, match="supplied together"):
        run_knowledge_correlation(
            snapshot=snapshot,
            forest=forest,
            corpus=corpus,
            soft_signal_manifest_sha256="f" * 64,
        )

    run = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        soft_signal_provider=provider,
        soft_signal_manifest_sha256="f" * 64,
    )
    assert run.receipt.soft_signal_manifest_sha256 == "f" * 64


def test_attempt_receipt_can_be_built_from_policy_bound_run() -> None:
    forest, snapshot, corpus = _inputs()
    run = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )
    context = build_access_scoped_context(
        run.result,
        snapshot=snapshot,
        corpus=corpus,
        objective="Rename Event.voltage.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        correlation_policy=run.policy,
    )
    prompt = build_knowledge_prompt_envelope(
        context,
        result=run.result,
        corpus=corpus,
    )
    receipt = build_attempt_receipt_from_correlation_run(
        receipt_id="policy-bound-attempt",
        created_at=CREATED_AT,
        snapshot=snapshot,
        corpus=corpus,
        run=run,
        access_policy=context.policy,
        context=context,
        prompt=prompt,
    )
    assert receipt.correlation_result_sha256 == run.result.digest
    assert receipt.correlation_policy_sha256 == (
        run.receipt.correlation_policy_sha256
    )
