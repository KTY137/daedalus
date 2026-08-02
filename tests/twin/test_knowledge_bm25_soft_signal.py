"""Autonomous but non-authoritative BM25/alias correlation proof."""
from __future__ import annotations

import runpy

from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    build_node_cards,
)
from daedalus.twin.knowledge_run import run_knowledge_correlation
from daedalus.twin.knowledge_soft_signals import (
    AliasGroup,
    BM25SoftSignalProvider,
    KnowledgeAliasLexicon,
)
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def test_bm25_aliases_correlate_free_prose_without_authority_escalation() -> None:
    forest, snapshot = _twin()
    corpus = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 1,
                    "title": "Acquisition contract",
                    "space_key": "E4",
                    "authority": "project_documentation",
                    "body_storage": (
                        "<p>The event sensor bias is persisted with every measurement.</p>"
                    ),
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    lexicon = KnowledgeAliasLexicon(
        groups=(
            AliasGroup(
                concept_id="detector bias",
                terms=("sensor bias", "bias voltage", "voltage"),
            ),
        )
    )
    reordered_lexicon = KnowledgeAliasLexicon(
        groups=(
            AliasGroup(
                concept_id="detector bias",
                terms=("voltage", "bias voltage", "sensor bias"),
            ),
        )
    )
    assert lexicon.digest == reordered_lexicon.digest

    cards = build_node_cards(snapshot, forest)
    provider = BM25SoftSignalProvider(cards=cards, lexicon=lexicon)
    replay_provider = BM25SoftSignalProvider(
        cards=tuple(reversed(cards)),
        lexicon=reordered_lexicon,
    )
    assert provider.manifest_sha256 == replay_provider.manifest_sha256

    claim = corpus.claims[0]
    document = corpus.documents[0]
    by_id = {card.node_id: card for card in cards}
    event_score = provider.score(
        claim=claim,
        document=document,
        card=by_id["type:field:src/events.py#Event.voltage"],
    )
    output_score = provider.score(
        claim=claim,
        document=document,
        card=by_id["type:field:src/device.py#Device.output_voltage"],
    )
    assert event_score is not None
    assert output_score is not None
    assert event_score[0] > output_score[0]
    assert event_score[1] == provider.manifest_sha256

    run = run_knowledge_correlation(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.10),
        soft_signal_provider=provider,
        soft_signal_manifest_sha256=provider.manifest_sha256,
    )
    proposals = {
        proposal.target_node_id: proposal
        for proposal in run.result.proposals
    }
    event = proposals["type:field:src/events.py#Event.voltage"]
    assert event.state == "proposed"
    assert event.eligible_for_verification is False
    assert any(signal.kind == "soft-provider" for signal in event.signals)
    assert run.receipt.soft_signal_manifest_sha256 == provider.manifest_sha256
    assert not any(
        proposal.state == "source_supported"
        for proposal in run.result.proposals
    )
