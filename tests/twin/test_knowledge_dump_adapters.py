"""Real export-shape crucible for external knowledge ingestion."""
from __future__ import annotations

import bz2
from pathlib import Path
import runpy

import pytest

from daedalus.twin.knowledge_correlation import CorrelationPolicy, correlate_knowledge
from daedalus.twin.knowledge_dump_adapters import (
    KnowledgeDumpAdapterError,
    MediaWikiXMLLimits,
    ingest_confluence_html_export,
    ingest_confluence_rest_dump,
    ingest_mediawiki_xml_dump,
)
from daedalus.twin.knowledge_sources import combine_knowledge_corpora


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


_MEDIAWIKI_XML = b"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<mediawiki xmlns=\"http://www.mediawiki.org/xml/export-0.11/\">
  <page>
    <title>Bias voltage</title><ns>0</ns><id>42</id>
    <revision><id>9001</id><timestamp>2026-01-01T00:00:00Z</timestamp>
      <text xml:space=\"preserve\">== Detector bias ==
Bias voltage is applied to a detector. `Event.voltage` is a project-specific example.</text>
    </revision>
  </page>
  <page>
    <title>Talk:Bias voltage</title><ns>1</ns><id>43</id>
    <revision><id>9002</id><timestamp>2026-01-01T00:00:00Z</timestamp>
      <text xml:space=\"preserve\">This talk page must not enter the default namespace selection.</text>
    </revision>
  </page>
  <page>
    <title>Unrelated physics</title><ns>0</ns><id>44</id>
    <revision><id>9003</id><timestamp>2026-01-01T00:00:00Z</timestamp>
      <text xml:space=\"preserve\">Not selected by the title prefix.</text>
    </revision>
  </page>
</mediawiki>
"""


def test_real_export_adapters_are_bounded_deterministic_and_correlatable(tmp_path: Path) -> None:
    forest, snapshot = _twin()

    confluence_rest = ingest_confluence_rest_dump(
        {
            "results": [
                {
                    "id": "123",
                    "title": "Bias ADR",
                    "space": {"key": "E4"},
                    "version": {"number": 7},
                    "body": {
                        "storage": {
                            "value": (
                                "<h1>Decision</h1>"
                                "<p><code>Event.voltage</code> is required and stored "
                                "with every measurement.</p>"
                            )
                        }
                    },
                    "metadata": {"labels": {"results": [{"name": "adr"}]}},
                }
            ]
        },
        instance_id="confluence.example",
        imported_at=CREATED_AT,
    )
    assert confluence_rest.documents[0].source.authority == "accepted_architecture"
    assert confluence_rest.documents[0].source.source_revision == "7"

    confluence_html = ingest_confluence_html_export(
        {
            "Bias Runbook.html": (
                "<html><head><title>Bias Runbook</title></head><body>"
                "<h1>Operation</h1><p><code>Event.voltage</code> is required.</p>"
                "</body></html>"
            )
        },
        instance_id="confluence-html-export",
        export_revision="space-export-2026-08-02",
        imported_at=CREATED_AT,
        authority="operational_runbook",
    )
    assert confluence_html.documents[0].title == "Bias Runbook"
    assert confluence_html.documents[0].source.authority == "operational_runbook"

    xml_path = tmp_path / "enwiki.xml"
    bz2_path = tmp_path / "enwiki.xml.bz2"
    xml_path.write_bytes(_MEDIAWIKI_XML)
    bz2_path.write_bytes(bz2.compress(_MEDIAWIKI_XML))
    limits = MediaWikiXMLLimits(
        max_selected_pages=2,
        max_page_text_bytes=20_000,
        max_total_text_bytes=40_000,
    )
    wiki_xml = ingest_mediawiki_xml_dump(
        xml_path,
        instance_id="wikipedia-en",
        imported_at=CREATED_AT,
        limits=limits,
        title_prefixes=("Bias",),
    )
    wiki_bz2 = ingest_mediawiki_xml_dump(
        bz2_path,
        instance_id="wikipedia-en",
        imported_at=CREATED_AT,
        limits=limits,
        title_prefixes=("Bias",),
    )
    assert wiki_xml.digest == wiki_bz2.digest
    assert [document.title for document in wiki_xml.documents] == ["Bias voltage"]
    assert wiki_xml.documents[0].source.authority == "external_reference"

    corpus = combine_knowledge_corpora(
        "real-export-crucible",
        confluence_rest,
        confluence_html,
        wiki_xml,
    )
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )
    event_proposals = [
        proposal
        for proposal in result.proposals
        if proposal.target_node_id == "type:field:src/events.py#Event.voltage"
    ]
    assert len(event_proposals) >= 3
    assert any(proposal.eligible_for_verification for proposal in event_proposals)
    assert any(
        not proposal.eligible_for_verification
        and proposal.source_authority == "external_reference"
        for proposal in event_proposals
    )

    doctype_path = tmp_path / "unsafe.xml"
    doctype_path.write_bytes(
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY leak "boom">]>'
        b'<mediawiki><page><title>X</title><ns>0</ns><id>1</id>'
        b'<revision><id>2</id><text>&leak;</text></revision></page></mediawiki>'
    )
    with pytest.raises(KnowledgeDumpAdapterError, match="DTD/entities"):
        ingest_mediawiki_xml_dump(
            doctype_path,
            instance_id="unsafe",
            imported_at=CREATED_AT,
        )

    with pytest.raises(KnowledgeDumpAdapterError, match="max_selected_pages"):
        ingest_mediawiki_xml_dump(
            xml_path,
            instance_id="bounded",
            imported_at=CREATED_AT,
            namespace_ids=(0, 1),
            limits=MediaWikiXMLLimits(
                max_selected_pages=1,
                max_page_text_bytes=20_000,
                max_total_text_bytes=40_000,
            ),
        )
