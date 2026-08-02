"""Deep immutability regression for external knowledge graph projections."""
from __future__ import annotations

from daedalus.twin.knowledge_graph_projection import KnowledgeOverlayNode


def test_overlay_node_deep_freezes_nested_attributes() -> None:
    headings = ["Architecture", "Sensor bias"]
    metadata = {"tags": ["adr", "bias"], "nested": {"required": True}}
    node = KnowledgeOverlayNode(
        node_id="external-section:" + "a" * 64,
        kind="external_knowledge_section",
        attributes=(
            ("heading_path", headings),
            ("metadata", metadata),
        ),
    )
    before_digest = node.digest
    before = node.to_dict()

    headings.append("MUTATED")
    metadata["tags"].append("MUTATED")
    metadata["nested"]["required"] = False

    assert node.digest == before_digest
    assert node.to_dict() == before
    rendered = str(node.to_dict())
    assert "MUTATED" not in rendered
    assert "required': True" in rendered
