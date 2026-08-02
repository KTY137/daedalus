"""File-level acceptance test for the offline knowledge pipeline."""
from __future__ import annotations

import json
from pathlib import Path
import runpy

import pytest

from daedalus.spine.envelope import canonical_json
from daedalus.twin.knowledge_pipeline import main
from daedalus.twin.knowledge_wire import (
    KnowledgeWireError,
    knowledge_corpus_json,
    parse_knowledge_corpus_json,
    parse_knowledge_forest,
    strict_json,
)


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def test_offline_dump_to_access_scoped_context_roundtrip(tmp_path: Path, capsys) -> None:
    forest, snapshot = _twin()
    snapshot_path = tmp_path / "snapshot.json"
    forest_path = tmp_path / "forest.json"
    _write(snapshot_path, snapshot.to_json())
    _write(forest_path, canonical_json(forest.to_dict()))

    confluence_dump = tmp_path / "confluence.json"
    _write(
        confluence_dump,
        json.dumps(
            {
                "schema": "daedalus-confluence-dump/1",
                "pages": [
                    {
                        "page_id": "18439177",
                        "version": 23,
                        "title": "Sensor Bias Storage",
                        "space_key": "E4",
                        "labels": ["sensor bias"],
                        "authority": "accepted_architecture",
                        "access_class": "internal",
                        "body_storage": (
                            "<h1>Sensor bias</h1>"
                            "<p>Each measurement stores <code>Event.voltage</code>. "
                            "The field is required.</p>"
                        ),
                    }
                ],
            }
        ),
    )
    obsidian_root = tmp_path / "vault"
    _write(
        obsidian_root / "private-note.md",
        "# Sensor bias\n`Event.voltage` may be omitted in an old experiment.\n",
    )

    confluence_corpus = tmp_path / "confluence-corpus.json"
    obsidian_corpus = tmp_path / "obsidian-corpus.json"
    combined_corpus = tmp_path / "combined-corpus.json"
    correlation = tmp_path / "correlation.json"
    context = tmp_path / "context.json"

    assert main(
        [
            "ingest-confluence",
            "--input",
            str(confluence_dump),
            "--instance-id",
            "institute-confluence",
            "--imported-at",
            CREATED_AT,
            "--output",
            str(confluence_corpus),
        ]
    ) == 0
    assert main(
        [
            "ingest-obsidian",
            "--root",
            str(obsidian_root),
            "--vault-id",
            "private-research",
            "--source-revision",
            "vault-rev-9",
            "--imported-at",
            CREATED_AT,
            "--output",
            str(obsidian_corpus),
        ]
    ) == 0
    assert main(
        [
            "combine",
            "--input",
            str(obsidian_corpus),
            "--input",
            str(confluence_corpus),
            "--corpus-id",
            "pipeline-crucible",
            "--output",
            str(combined_corpus),
        ]
    ) == 0

    corpus = parse_knowledge_corpus_json(combined_corpus.read_bytes())
    assert corpus == parse_knowledge_corpus_json(
        knowledge_corpus_json(corpus), "roundtrip corpus"
    )
    assert len(corpus.documents) == 2

    assert main(
        [
            "correlate",
            "--snapshot",
            str(snapshot_path),
            "--forest",
            str(forest_path),
            "--corpus",
            str(combined_corpus),
            "--output",
            str(correlation),
        ]
    ) == 0
    correlation_payload = json.loads(correlation.read_text(encoding="utf-8"))
    assert correlation_payload["schema"] == "daedalus-knowledge-correlation-result/1"
    assert any(
        proposal["target_node_id"] == "type:field:src/events.py#Event.voltage"
        for bundle in correlation_payload["bundles"]
        for proposal in bundle["proposals"]
    )

    assert main(
        [
            "context",
            "--snapshot",
            str(snapshot_path),
            "--forest",
            str(forest_path),
            "--corpus",
            str(combined_corpus),
            "--objective",
            "Rename Event.voltage without exposing private notes.",
            "--anchor",
            "type:field:src/events.py#Event.voltage",
            "--output",
            str(context),
        ]
    ) == 0
    context_payload = json.loads(context.read_text(encoding="utf-8"))
    rendered = json.dumps(context_payload, sort_keys=True)
    assert context_payload["schema"] == "daedalus-access-scoped-knowledge-context/1"
    assert "Each measurement stores `Event.voltage`" in rendered
    assert "may be omitted in an old experiment" not in rendered
    assert context_payload["withheld_source_ids"]
    assert context_payload["withheld_claim_sha256s"]
    assert context_payload["policy"]["allowed_access_classes"] == [
        "internal",
        "public",
    ]

    # Outputs are immutable by default and require an explicit replacement flag.
    assert main(
        [
            "context",
            "--snapshot",
            str(snapshot_path),
            "--forest",
            str(forest_path),
            "--corpus",
            str(combined_corpus),
            "--objective",
            "Do not overwrite evidence silently.",
            "--anchor",
            "type:field:src/events.py#Event.voltage",
            "--output",
            str(context),
        ]
    ) == 2
    assert "output already exists" in capsys.readouterr().err


def test_wire_boundary_rejects_duplicate_keys_unknown_fields_and_dangling_edges() -> None:
    with pytest.raises(KnowledgeWireError, match="duplicate JSON key"):
        strict_json('{"schema":"x","schema":"y"}', "duplicate fixture")

    forest, _ = _twin()
    payload = forest.to_dict()
    payload["unknown"] = True
    with pytest.raises(KnowledgeWireError, match="unknown"):
        parse_knowledge_forest(payload)

    payload = forest.to_dict()
    payload["edges"][0]["target"] = "type:missing#Field"
    with pytest.raises(KnowledgeWireError, match="dangling"):
        parse_knowledge_forest(payload)
