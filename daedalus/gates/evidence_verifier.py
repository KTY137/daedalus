"""Strict verification of a :class:`GateEvidenceIndex` against live state.

The index's own ``mechanical_blockers`` checks required membership. This module
adds the adversarial rule that *every retained item* must also be coherent.
Extra failed, stale, foreign, or content-address-mismatched evidence cannot be
smuggled into the index and silently ignored.
"""
from __future__ import annotations

from datetime import datetime, timezone

from daedalus.schemas import _revision

from .evidence import GateEvidenceIndex


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value.astimezone(timezone.utc)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def strict_mechanical_blockers(
    index: GateEvidenceIndex,
    *,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> tuple[str, ...]:
    """Return all exact-head blockers, including inconsistent extra evidence."""

    current = _revision(current_revision, "current_revision")
    current_tree = _revision(current_tree_revision, "current_tree_revision")
    instant = _utc(now)
    blockers = set(
        index.mechanical_blockers(
            current_revision=current,
            current_tree_revision=current_tree,
            now=instant,
        )
    )

    for item in index.workflows:
        prefix = f"workflow:{item.workflow_id}"
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.conclusion != "success":
            blockers.add(f"{prefix}:conclusion-{item.conclusion}")
        if _parse(item.completed_at) > instant:
            blockers.add(f"{prefix}:completed-in-future")
        if instant >= _parse(item.expires_at):
            blockers.add(f"{prefix}:expired")

    for item in index.artifacts:
        prefix = f"artifact:{item.artifact_kind}"
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.source_tree_revision != current_tree:
            blockers.add(f"{prefix}:foreign-source-tree")
        if item.locator.rsplit(":", 1)[-1] != item.content_sha256:
            blockers.add(f"{prefix}:locator-content-mismatch")
        if _parse(item.built_at) > instant:
            blockers.add(f"{prefix}:built-in-future")

    for item in index.runtimes:
        prefix = f"runtime:{item.runtime_id}"
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.authority != "live-runtime":
            blockers.add(f"{prefix}:non-live-authority")
        if item.status != "passed":
            blockers.add(f"{prefix}:status-{item.status}")
        if _parse(item.observed_at) > instant:
            blockers.add(f"{prefix}:observed-in-future")
        if instant >= _parse(item.expires_at):
            blockers.add(f"{prefix}:expired")

    for item in index.fault_matrices:
        prefix = f"fault-matrix:{item.matrix_id}"
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.status != "passed":
            blockers.add(f"{prefix}:status-{item.status}")
        if _parse(item.executed_at) > instant:
            blockers.add(f"{prefix}:executed-in-future")

    for item in index.reviews:
        prefix = f"review:{item.perspective}"
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.unresolved_finding_ids:
            blockers.add(f"{prefix}:unresolved-findings")
        if item.verdict == "changes-requested":
            blockers.add(f"{prefix}:changes-requested")
        if _parse(item.reviewed_at) > instant:
            blockers.add(f"{prefix}:reviewed-in-future")

    if index.owner_decision is not None:
        if index.owner_decision.source_revision != current:
            blockers.add("owner-decision:foreign-source-revision")
        if _parse(index.owner_decision.verified_at) > instant:
            blockers.add("owner-decision:verified-in-future")

    return tuple(sorted(blockers))


def assert_strict_exact_head(
    index: GateEvidenceIndex,
    *,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> None:
    """Raise with the deterministic blocker list when the index is not ready."""

    blockers = strict_mechanical_blockers(
        index,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=now,
    )
    if blockers:
        raise ValueError("Gate evidence index has blocker(s): " + ", ".join(blockers))


__all__ = ["assert_strict_exact_head", "strict_mechanical_blockers"]
