"""Derive Fourfold context anchors from existing work-item target paths.

Daedalus work items already carry bounded repository paths. This module maps
those paths to exact node cards so knowledge correlation can be used without a
human knowing internal Fourfold node IDs. Selection is lexical only on paths;
semantic objective matching remains a separate, later research feature.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Sequence

from ..spine.envelope import canonical_sha
from .knowledge_correlation import (
    KnowledgeCorrelationError,
    KnowledgeCorrelationResult,
)


def _path(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeCorrelationError("target path must not be empty")
    normalized = value.strip().replace("\\", "/").lstrip("./")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise KnowledgeCorrelationError("target path must be bounded and relative")
    return normalized


@dataclass(frozen=True)
class KnowledgeAnchorSelection:
    snapshot_sha256: str
    correlation_result_sha256: str
    target_paths: tuple[str, ...]
    anchor_node_ids: tuple[str, ...]
    unmatched_target_paths: tuple[str, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-anchor-selection/1"

    def __post_init__(self) -> None:
        targets = tuple(sorted({_path(value) for value in self.target_paths}))
        if not targets:
            raise KnowledgeCorrelationError("anchor selection requires targets")
        anchors = tuple(sorted(set(self.anchor_node_ids)))
        unmatched = tuple(sorted({_path(value) for value in self.unmatched_target_paths}))
        if not set(unmatched).issubset(targets):
            raise KnowledgeCorrelationError("unmatched paths must be target paths")
        if not anchors and not unmatched:
            raise KnowledgeCorrelationError(
                "anchor selection must contain anchors or unmatched paths"
            )
        object.__setattr__(self, "target_paths", targets)
        object.__setattr__(self, "anchor_node_ids", anchors)
        object.__setattr__(self, "unmatched_target_paths", unmatched)

    @property
    def complete(self) -> bool:
        return not self.unmatched_target_paths and bool(self.anchor_node_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_sha256": self.snapshot_sha256,
            "correlation_result_sha256": self.correlation_result_sha256,
            "target_paths": list(self.target_paths),
            "anchor_node_ids": list(self.anchor_node_ids),
            "unmatched_target_paths": list(self.unmatched_target_paths),
            "complete": self.complete,
            "authority_granted": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def select_knowledge_anchors_for_paths(
    result: KnowledgeCorrelationResult,
    target_paths: Sequence[str],
    *,
    fail_on_unmatched: bool = True,
) -> KnowledgeAnchorSelection:
    """Select every exact snapshot node whose source path is a target path."""

    targets = tuple(sorted({_path(value) for value in target_paths}))
    if not targets:
        raise KnowledgeCorrelationError("target_paths must not be empty")
    card_paths = {
        card.node_id: card.path.replace("\\", "/").lstrip("./")
        for card in result.cards
        if card.path
    }
    anchors = tuple(
        sorted(
            node_id
            for node_id, path in card_paths.items()
            if path in set(targets)
        )
    )
    matched_paths = {card_paths[node_id] for node_id in anchors}
    unmatched = tuple(sorted(set(targets) - matched_paths))
    if fail_on_unmatched and unmatched:
        raise KnowledgeCorrelationError(
            f"target paths have no Fourfold node cards: {list(unmatched)}"
        )
    return KnowledgeAnchorSelection(
        snapshot_sha256=result.snapshot_sha256,
        correlation_result_sha256=result.digest,
        target_paths=targets,
        anchor_node_ids=anchors,
        unmatched_target_paths=unmatched,
    )


__all__ = [
    "KnowledgeAnchorSelection",
    "select_knowledge_anchors_for_paths",
]
