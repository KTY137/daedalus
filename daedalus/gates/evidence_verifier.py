"""Strict verification of a :class:`GateEvidenceIndex` against live state.

Canonical data is not authenticated merely because it parses. The strict
verifier therefore requires independently obtained trust sets for the adopted
requirements, protected plan/registry digests, and every hard evidence class.
Empty trust sets fail closed.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_sha

from .evidence import GateEvidenceIndex


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must include a timezone")
    return value.astimezone(timezone.utc)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _trusted(values: Iterable[str], label: str) -> frozenset[str]:
    return frozenset(_sha256(value, label) for value in values)


def evidence_requirements_sha256(index: GateEvidenceIndex) -> str:
    """Digest the adopted Gate-0 requirement set independently of observations."""

    return canonical_sha(
        {
            "schema": "daedalus-gate-evidence-requirements/1",
            "gate": index.gate,
            "required_workflow_ids": list(index.required_workflow_ids),
            "required_artifact_kinds": list(index.required_artifact_kinds),
            "required_runtime_ids": list(index.required_runtime_ids),
            "required_fault_matrix_ids": list(index.required_fault_matrix_ids),
            "required_review_perspectives": list(
                index.required_review_perspectives
            ),
        }
    )


def strict_mechanical_blockers(
    index: GateEvidenceIndex,
    *,
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
    trusted_requirements_sha256s: Iterable[str] = (),
    trusted_iron_plan_sha256s: Iterable[str] = (),
    trusted_registry_sha256s: Iterable[str] = (),
    trusted_workflow_evidence_sha256s: Iterable[str] = (),
    trusted_artifact_evidence_sha256s: Iterable[str] = (),
    trusted_runtime_envelope_sha256s: Iterable[str] = (),
    trusted_fault_matrix_sha256s: Iterable[str] = (),
    trusted_review_evidence_sha256s: Iterable[str] = (),
    trusted_owner_verifier_sha256s: Iterable[str] = (),
) -> tuple[str, ...]:
    """Return exact-head blockers including authenticity and optional evidence."""

    current = _revision(current_revision, "current_revision")
    current_tree = _revision(current_tree_revision, "current_tree_revision")
    instant = _utc(now)
    trusted_requirements = _trusted(
        trusted_requirements_sha256s, "trusted_requirements_sha256"
    )
    trusted_plans = _trusted(
        trusted_iron_plan_sha256s, "trusted_iron_plan_sha256"
    )
    trusted_registries = _trusted(
        trusted_registry_sha256s, "trusted_registry_sha256"
    )
    trusted_workflows = _trusted(
        trusted_workflow_evidence_sha256s, "trusted_workflow_evidence_sha256"
    )
    trusted_artifacts = _trusted(
        trusted_artifact_evidence_sha256s, "trusted_artifact_evidence_sha256"
    )
    trusted_runtimes = _trusted(
        trusted_runtime_envelope_sha256s, "trusted_runtime_envelope_sha256"
    )
    trusted_faults = _trusted(
        trusted_fault_matrix_sha256s, "trusted_fault_matrix_sha256"
    )
    trusted_reviews = _trusted(
        trusted_review_evidence_sha256s, "trusted_review_evidence_sha256"
    )
    trusted_owner = _trusted(
        trusted_owner_verifier_sha256s, "trusted_owner_verifier_sha256"
    )
    blockers = set(
        index.mechanical_blockers(
            current_revision=current,
            current_tree_revision=current_tree,
            now=instant,
        )
    )

    if evidence_requirements_sha256(index) not in trusted_requirements:
        blockers.add("index:untrusted-requirements")
    if index.iron_plan_sha256 not in trusted_plans:
        blockers.add("index:untrusted-iron-plan")
    if index.registry_sha256 not in trusted_registries:
        blockers.add("index:untrusted-registry")

    for item in index.workflows:
        prefix = f"workflow:{item.workflow_id}"
        if item.digest not in trusted_workflows:
            blockers.add(f"{prefix}:untrusted-evidence")
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
        if item.digest not in trusted_artifacts:
            blockers.add(f"{prefix}:untrusted-evidence")
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
        if item.envelope_sha256 not in trusted_runtimes:
            blockers.add(f"{prefix}:untrusted-envelope")
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
        if item.matrix_sha256 not in trusted_faults:
            blockers.add(f"{prefix}:untrusted-matrix")
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.status != "passed":
            blockers.add(f"{prefix}:status-{item.status}")
        if _parse(item.executed_at) > instant:
            blockers.add(f"{prefix}:executed-in-future")

    for item in index.reviews:
        prefix = f"review:{item.perspective}"
        if item.digest not in trusted_reviews:
            blockers.add(f"{prefix}:untrusted-evidence")
        if item.source_revision != current:
            blockers.add(f"{prefix}:foreign-source-revision")
        if item.unresolved_finding_ids:
            blockers.add(f"{prefix}:unresolved-findings")
        if item.verdict == "changes-requested":
            blockers.add(f"{prefix}:changes-requested")
        if _parse(item.reviewed_at) > instant:
            blockers.add(f"{prefix}:reviewed-in-future")

    if index.owner_decision is not None:
        if index.owner_decision.verifier_receipt_sha256 not in trusted_owner:
            blockers.add("owner-decision:untrusted-verifier-receipt")
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
    trusted_requirements_sha256s: Iterable[str] = (),
    trusted_iron_plan_sha256s: Iterable[str] = (),
    trusted_registry_sha256s: Iterable[str] = (),
    trusted_workflow_evidence_sha256s: Iterable[str] = (),
    trusted_artifact_evidence_sha256s: Iterable[str] = (),
    trusted_runtime_envelope_sha256s: Iterable[str] = (),
    trusted_fault_matrix_sha256s: Iterable[str] = (),
    trusted_review_evidence_sha256s: Iterable[str] = (),
    trusted_owner_verifier_sha256s: Iterable[str] = (),
) -> None:
    """Raise with the deterministic blocker list when the index is not trusted."""

    blockers = strict_mechanical_blockers(
        index,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=now,
        trusted_requirements_sha256s=trusted_requirements_sha256s,
        trusted_iron_plan_sha256s=trusted_iron_plan_sha256s,
        trusted_registry_sha256s=trusted_registry_sha256s,
        trusted_workflow_evidence_sha256s=trusted_workflow_evidence_sha256s,
        trusted_artifact_evidence_sha256s=trusted_artifact_evidence_sha256s,
        trusted_runtime_envelope_sha256s=trusted_runtime_envelope_sha256s,
        trusted_fault_matrix_sha256s=trusted_fault_matrix_sha256s,
        trusted_review_evidence_sha256s=trusted_review_evidence_sha256s,
        trusted_owner_verifier_sha256s=trusted_owner_verifier_sha256s,
    )
    if blockers:
        raise ValueError("Gate evidence index has blocker(s): " + ", ".join(blockers))


__all__ = [
    "assert_strict_exact_head",
    "evidence_requirements_sha256",
    "strict_mechanical_blockers",
]
