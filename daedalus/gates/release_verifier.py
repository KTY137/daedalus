"""Independent current-state verification for Gate-0 release reports."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from daedalus.schemas import _revision

from .evidence import GateEvidenceIndex
from .release import Gate0ReleaseReport, assemble_gate0_release_report
from .report import GateReport
from .trust_bundle import (
    EvidenceTrustBundle,
    EvidenceTrustBundleBindingError,
    EvidenceTrustBundleSignatureError,
)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _bundle_blocker(exc: Exception) -> str:
    if isinstance(exc, EvidenceTrustBundleSignatureError):
        return "release:trust-bundle-signature"
    if isinstance(exc, EvidenceTrustBundleBindingError):
        return "release:trust-bundle-binding"
    return "release:trust-bundle-verification"


def gate0_release_verification_blockers(
    release: Gate0ReleaseReport,
    mechanical_report: GateReport,
    evidence_index: GateEvidenceIndex,
    trust_bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    collector_keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> tuple[str, ...]:
    """Reconstruct a retained report and recheck exact-head trust at ``now``."""

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
    if release.evidence_trust_bundle_sha256 != trust_bundle.digest:
        blockers.add("release:trust-bundle-mismatch")
    if generated > instant:
        blockers.add("release:generated-in-future")

    common = {
        "repo_root": repo_root,
        "collector_keyring": collector_keyring,
        "expected_collector_id": expected_collector_id,
        "expected_workflow_paths": expected_workflow_paths,
        "release_id": release.release_id,
    }

    try:
        reconstructed = assemble_gate0_release_report(
            mechanical_report,
            evidence_index,
            trust_bundle,
            current_revision=release.source_revision,
            current_tree_revision=release.source_tree_revision,
            now=generated,
            **common,
        )
    except (EvidenceTrustBundleSignatureError, EvidenceTrustBundleBindingError) as exc:
        blockers.add(_bundle_blocker(exc))
        blockers.add("release:projection-unverifiable")
    else:
        if reconstructed.to_dict() != release.to_dict():
            blockers.add("release:projection-mismatch")

    try:
        current_projection = assemble_gate0_release_report(
            mechanical_report,
            evidence_index,
            trust_bundle,
            current_revision=current,
            current_tree_revision=current_tree,
            now=instant,
            **common,
        )
    except (EvidenceTrustBundleSignatureError, EvidenceTrustBundleBindingError) as exc:
        blockers.add(_bundle_blocker(exc))
        blockers.add("release:no-longer-current")
    else:
        blockers.update(current_projection.blockers)
        if release.closed and not current_projection.closed:
            blockers.add("release:no-longer-current")

    return tuple(sorted(blockers))


def assert_gate0_release_report(
    release: Gate0ReleaseReport,
    mechanical_report: GateReport,
    evidence_index: GateEvidenceIndex,
    trust_bundle: EvidenceTrustBundle,
    **verification: object,
) -> None:
    """Raise with a deterministic blocker list when a release is not trusted."""

    blockers = gate0_release_verification_blockers(
        release,
        mechanical_report,
        evidence_index,
        trust_bundle,
        **verification,
    )
    if blockers:
        raise ValueError("Gate-0 release report has blocker(s): " + ", ".join(blockers))


__all__ = [
    "assert_gate0_release_report",
    "gate0_release_verification_blockers",
]
