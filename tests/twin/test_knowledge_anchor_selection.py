"""Automatic work-item-path to Fourfold-anchor selection tests."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_anchor_selection import (
    select_knowledge_anchors_for_paths,
)
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    correlate_knowledge,
)
from daedalus.twin.knowledge_sources import ingest_confluence_dump


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _result():
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
    return correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )


def test_work_item_path_selects_all_exact_file_nodes_without_name_leakage() -> None:
    result = _result()
    selection = select_knowledge_anchors_for_paths(
        result,
        ("./src/events.py",),
    )

    assert selection.complete is True
    assert selection.target_paths == ("src/events.py",)
    assert {
        "code:file:src/events.py",
        "type:src/events.py#Event",
        "type:field:src/events.py#Event.voltage",
    }.issubset(set(selection.anchor_node_ids))
    assert "type:field:src/device.py#Device.output_voltage" not in selection.anchor_node_ids
    assert selection.unmatched_target_paths == ()
    assert selection.to_dict()["authority_granted"] is False
    assert selection.digest == select_knowledge_anchors_for_paths(
        result,
        ("src\\events.py",),
    ).digest


def test_target_path_selection_refuses_traversal_and_absolute_paths() -> None:
    result = _result()
    for invalid in ("../src/events.py", "src/../events.py", "/src/events.py"):
        with pytest.raises(KnowledgeCorrelationError):
            select_knowledge_anchors_for_paths(result, (invalid,))


def test_unknown_target_is_visible_or_fail_closed() -> None:
    result = _result()
    with pytest.raises(KnowledgeCorrelationError, match="no Fourfold node cards"):
        select_knowledge_anchors_for_paths(
            result,
            ("src/missing.py",),
        )

    selection = select_knowledge_anchors_for_paths(
        result,
        ("src/missing.py",),
        fail_on_unmatched=False,
    )
    assert selection.complete is False
    assert selection.anchor_node_ids == ()
    assert selection.unmatched_target_paths == ("src/missing.py",)
