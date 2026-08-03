"""Independent verification for an exact-head Gate-0 release report.

A serialized release report is not trusted merely because its derived
``closed`` field is true. Verification reconstructs the original projection
from the retained mechanical report and evidence index, then rechecks all
external trust anchors and expiry conditions at the current instant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from daedalus.schemas import _revision

from .evidence import GateEvidenceIndex
from .release import Gate0ReleaseReport, assemble_gate0_release_report
from .report import GateReport


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def gate0_release_verification_blockers(
    release: Gate0ReleaseReport,
    mechanical_report: GateReport,
    evidence_index: GateEvidenceIndex,
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
    """Reconstruct and recheck a retained release report against live state."""

    current = _revision(current_revision, "current_revision")
    current_tree = _revision(current_tree_revision, "current_tree_revision")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must include a timezone")
    instant = now.astimezone(timezone.utc)
    generated = _parse_utc(release.generated_at)
    blockers: set[str] = set()

    mechanical_sha = str(mechanical_report.to_dict()["report_sha256"])
    if release.source_revision != current:
        blockers.add("release:foreign-source-revision")
    if release.source_tree_revision != current_tree:
        blockers.add("release:foreign-source-tree")
    if release.mechanical_report_sha256 != mechanical_sha:
        blockers.add("release:mechanical-report-mismatch")
    if release.evidence_index_sha256 != evidence_index.digest:
        blockers.add("release:evidence-index-mismatch")
    if generated > instant:
        blockers.add("release:generated-in-future")

    trust = {
        "trusted_requirements_sha256s": trusted_requirements_sha256s,
        "trusted_iron_plan_sha256s": trusted_iron_plan_sha256s,
        "trusted_registry_sha256s": trusted_registry_sha256s,
        "trusted_workflow_evidence_sha256s": trusted_workflow_evidence_sha256s,
        "trusted_artifact_evidence_sha256s": trusted_artifact_evidence_sha256s,
        "trusted_runtime_envelope_sha256s": trusted_runtime_envelope_sha256s,
        "trusted_fault_matrix_sha256s": trusted_fault_matrix_sha256s,
        "trusted_review_evidence_sha256s": trusted_review_evidence_sha256s,
        "trusted_owner_verifier_sha256s": trusted_owner_verifier_sha256s,
    }

    reconstructed = assemble_gate0_release_report(
        mechanical_report,
        evidence_index,
        release_id=release.release_id,
        current_revision=release.source_revision,
        current_tree_revision=release.source_tree_revision,
        now=generated,
        provenance_origin=release.provenance.origin,
        trace_id=release.provenance.trace_id,
        **trust,
    )
    if reconstructed.to_dict() != release.to_dict():
        blockers.add("release:projection-mismatch")

    current_projection = assemble_gate0_release_report(
        mechanical_report,
        evidence_index,
        release_id=release.release_id,
        current_revision=current,
        current_tree_revision=current_tree,
        now=instant,
        provenance_origin=release.provenance.origin,
        trace_id=release.provenance.trace_id,
        **trust,
    )
    blockers.update(current_projection.blockers)
    if release.closed and not current_projection.closed:
        blockers.add("release:no-longer-current")

    return tuple(sorted(blockers))


def assert_gate0_release_report(
    release: Gate0ReleaseReport,
    mechanical_report: GateReport,
    evidence_index: GateEvidenceIndex,
    **verification: object,
) -> None:
    """Raise with a deterministic blocker list when a release is not trusted."""

    blockers = gate0_release_verification_blockers(
        release,
        mechanical_report,
        evidence_index,
        **verification,
    )
    if blockers:
        raise ValueError("Gate-0 release report has blocker(s): " + ", ".join(blockers))


__all__ = [
    "assert_gate0_release_report",
    "gate0_release_verification_blockers",
]
