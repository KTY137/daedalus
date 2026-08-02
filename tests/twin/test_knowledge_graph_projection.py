"""Graph projection proof for external knowledge and Fourfold correlations."""
from __future__ import annotations

import runpy

from daedalus.twin.knowledge_correlation import CorrelationPolicy, correlate_knowledge
from daedalus.twin.knowledge_graph_projection import project_external_knowledge_graph
from daedalus.twin.knowledge_sources import (
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_obsidian_vault,
)


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def test_external_knowledge_becomes_a_regenerable_non_authoritative_graph() -> None:
    forest, snapshot = _twin()
    confluence = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 2,
                    "title": "Sensor Bias Architecture",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "body_storage": (
                        "<h1>Bias</h1>"
                        "<p><code>Event.voltage</code> is required.</p>"
                        "<p><code>CalibrationService</code> publishes corrections.</p>"
                    ),
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    obsidian = ingest_obsidian_vault(
        {"old.md": "# Bias\n`Event.voltage` may be omitted.\n"},
        vault_id="notes",
        source_revision="4",
        imported_at=CREATED_AT,
    )
    corpus = combine_knowledge_corpora("projection", confluence, obsidian)
    reordered = combine_knowledge_corpora("projection", obsidian, confluence)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )
    replay_result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=reordered,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )

    graph = project_external_knowledge_graph(corpus, result)
    replay = project_external_knowledge_graph(reordered, replay_result)
    assert graph.digest == replay.digest
    assert graph.snapshot_sha256 == snapshot.digest
    assert graph.corpus_sha256 == corpus.digest
    assert graph.correlation_result_sha256 == result.digest
    body = graph.to_dict()
    assert body["authoritative"] is False
    assert body["verified_binding_output"] is False
    assert body["regenerable"] is True

    kinds = {node.kind for node in graph.nodes}
    assert {
        "external_knowledge_source",
        "external_knowledge_document",
        "external_knowledge_section",
        "external_knowledge_claim",
        "fourfold_node_reference",
        "knowledge_contradiction",
        "unresolved_knowledge_anchor",
    }.issubset(kinds)
    relations = {edge.relation for edge in graph.edges}
    assert {
        "provides_revision",
        "contains_section",
        "asserts_claim",
        "documents",
        "describes_schema",
        "has_contradiction",
        "has_unresolved_anchor",
    }.issubset(relations)
    assert not any(edge.state in {"verified", "trusted"} for edge in graph.edges)
    assert any(edge.state == "source_supported" for edge in graph.edges)
    assert any(edge.state == "diagnostic" for edge in graph.edges)

    node_ids = {node.node_id for node in graph.nodes}
    assert len(node_ids) == len(graph.nodes)
    assert all(edge.source_node_id in node_ids for edge in graph.edges)
    assert all(edge.target_node_id in node_ids for edge in graph.edges)
