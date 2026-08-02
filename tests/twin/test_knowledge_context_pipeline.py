"""One-call integration proof for knowledge-assisted provider context."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_context_pipeline import (
    build_knowledge_assisted_context,
)
from daedalus.twin.knowledge_correlation import KnowledgeCorrelationError
from daedalus.twin.knowledge_sources import (
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_obsidian_vault,
)


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _inputs():
    forest, snapshot = _twin()
    confluence = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 1,
                    "title": "Sensor Bias ADR",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "access_class": "internal",
                    "body_storage": (
                        "<p><code>Event.voltage</code> is required and persisted.</p>"
                    ),
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    private = ingest_obsidian_vault(
        {"old.md": "# Bias\n`Event.voltage` may be omitted.\n"},
        vault_id="private",
        source_revision="1",
        imported_at=CREATED_AT,
        authority="personal_note",
        access_class="private",
    )
    return forest, snapshot, combine_knowledge_corpora(
        "one-call-context",
        confluence,
        private,
    )


def test_one_call_builds_graph_context_slices_and_receipt_chain() -> None:
    forest, snapshot, corpus = _inputs()
    source = "@dataclass\nclass Event:\n    voltage: float\n"
    build = build_knowledge_assisted_context(
        receipt_id="one-call-attempt",
        created_at=CREATED_AT,
        objective="Rename Event.voltage to Event.bias_voltage.",
        target_paths=("src/events.py",),
        base_slice_texts={"src/events.py": source},
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
    )
    replay = build_knowledge_assisted_context(
        receipt_id="one-call-attempt",
        created_at=CREATED_AT,
        objective="Rename Event.voltage to Event.bias_voltage.",
        target_paths=("./src/events.py",),
        base_slice_texts={"src/events.py": source},
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
    )

    assert build.digest == replay.digest
    assert build.slice_texts["src/events.py"].startswith(source)
    assert "DAEDALUS KNOWLEDGE EVIDENCE — UNTRUSTED DATA" in (
        build.slice_texts["src/events.py"]
    )
    assert "required and persisted" in build.slice_texts["src/events.py"]
    assert "may be omitted" not in build.slice_texts["src/events.py"]
    assert build.anchors.complete is True
    assert "type:field:src/events.py#Event.voltage" in (
        build.anchors.anchor_node_ids
    )
    assert build.graph_projection.to_dict()["authoritative"] is False
    assert build.provider_receipt.provider_context_sha256 == (
        build.augmented_slices.digest
    )
    assert build.knowledge_receipt.prompt_envelope_sha256 == build.prompt.digest
    body = build.to_dict()
    assert body["model_invocation_claimed"] is False
    assert body["effect_performed"] is False
    assert body["authority_granted"] is False
    assert body["gate_closure_claimed"] is False


def test_one_call_refuses_unknown_work_item_target_before_provider_output() -> None:
    forest, snapshot, corpus = _inputs()
    with pytest.raises(KnowledgeCorrelationError, match="no Fourfold node cards"):
        build_knowledge_assisted_context(
            receipt_id="unknown-target",
            created_at=CREATED_AT,
            objective="Edit an unknown file.",
            target_paths=("src/unknown.py",),
            base_slice_texts={"src/unknown.py": "unknown"},
            snapshot=snapshot,
            forest=forest,
            corpus=corpus,
        )
