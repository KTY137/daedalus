"""Sealed promotion authorization for Gate 0.

The existing Kairos integration-worktree machinery is retained, but it may not
start until this module proves that one persisted and re-authenticated
OwnerApproval consumption, one passed EvidencePacket, the exact ordered
candidate batch, and the live target HEAD all name the same immutable promotion
subject.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from daedalus.kernel.approvals import ApprovalLedger, ConsumedOwnerApproval
from daedalus.schemas import EvidencePacket, _identifier, _revision
from daedalus.spine.envelope import canonical_sha

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PromotionAuthorizationError(RuntimeError):
    """Fail-closed refusal before any promotion-side effect."""


def _canonical_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise PromotionAuthorizationError(
            f"{name} must be a lowercase 64-character SHA-256 digest"
        )
    return value


def _canonical_revision(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise PromotionAuthorizationError(f"{name} must be a revision string")
    try:
        return _revision(value, name)
    except (TypeError, ValueError) as exc:
        raise PromotionAuthorizationError(f"{name} is not a canonical revision") from exc


def _canonical_identifier(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise PromotionAuthorizationError(f"{name} must be an identifier string")
    try:
        return _identifier(value, name)
    except (TypeError, ValueError) as exc:
        raise PromotionAuthorizationError(f"{name} is not a canonical identifier") from exc


@dataclass(frozen=True)
class PromotionCandidateSnapshot:
    """Immutable local view of the exact candidate material being authorized.

    ``GatedCandidate`` is intentionally a compatibility dataclass and is not
    frozen. The promotion boundary therefore copies its already-frozen
    ``AttemptResult`` and ``PatchArtifact`` before authentication, then uses
    this snapshot for both authorization and the retained integration path.
    That prevents a caller thread from swapping ``candidate.result`` after the
    owner-bound digest was checked but before patch bytes are applied.
    """

    assignment: Any
    spec: Any
    result: Any


@dataclass(frozen=True)
class PromotionAuthorization:
    promotion_id: str
    candidate_artifact_sha256: str
    evidence_packet_sha256: str
    source_revision: str
    target_ref: str
    live_target_revision: str
    approval_consumption_sha256: str
    authorization_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "promotion_id": self.promotion_id,
            "candidate_artifact_sha256": self.candidate_artifact_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "source_revision": self.source_revision,
            "target_ref": self.target_ref,
            "live_target_revision": self.live_target_revision,
            "approval_consumption_sha256": self.approval_consumption_sha256,
            "authorization_sha256": self.authorization_sha256,
        }


def _canonical_changed_paths(paths: Any, *, index: int) -> tuple[str, ...]:
    if not isinstance(paths, tuple) or not paths:
        raise PromotionAuthorizationError(
            f"candidate[{index}] changed_paths must be a non-empty tuple"
        )
    canonical: list[str] = []
    for position, raw in enumerate(paths):
        if not isinstance(raw, str) or not raw or "\x00" in raw or "\\" in raw:
            raise PromotionAuthorizationError(
                f"candidate[{index}] changed_paths[{position}] is not a canonical "
                "repo-relative POSIX path"
            )
        path = PurePosixPath(raw)
        if (
            path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or path.as_posix() != raw
        ):
            raise PromotionAuthorizationError(
                f"candidate[{index}] changed_paths[{position}] is not a canonical "
                "repo-relative POSIX path"
            )
        canonical.append(raw)
    if len(set(canonical)) != len(canonical):
        raise PromotionAuthorizationError(
            f"candidate[{index}] changed_paths contains duplicates"
        )
    return tuple(canonical)


def snapshot_promotion_candidates(
    candidates: Sequence[Any],
) -> tuple[PromotionCandidateSnapshot, ...]:
    """Validate and freeze the exact patch material used by promotion.

    The candidate-batch digest must describe the bytes later passed to
    ``git apply``. A ``PatchArtifact`` stores both bytes and a digest but its
    dataclass constructor is intentionally lightweight, so this trust boundary
    recomputes the digest rather than trusting the field. It also binds the
    ``AttemptResult`` identity/base to the artifact and requires an actual
    passed gate, not a caller-authored object that merely exposes ``ok=True``.
    """
    from daedalus.spine.attempt import (
        AttemptResult,
        GateResult,
        PatchArtifact,
        STATE_CLEAN,
    )

    submitted = tuple(candidates)
    if not submitted:
        raise PromotionAuthorizationError("promotion candidate batch is empty")

    snapshots: list[PromotionCandidateSnapshot] = []
    for index, candidate in enumerate(submitted):
        result = getattr(candidate, "result", None)
        if not isinstance(result, AttemptResult):
            raise PromotionAuthorizationError(
                f"candidate[{index}] does not carry a canonical AttemptResult"
            )
        artifact = result.artifact
        if not isinstance(artifact, PatchArtifact):
            raise PromotionAuthorizationError(
                f"candidate[{index}] does not carry a canonical PatchArtifact"
            )
        if result.state != STATE_CLEAN or not result.ok or artifact.is_empty:
            raise PromotionAuthorizationError(
                f"candidate[{index}] is not a clean non-empty gated artifact"
            )
        gate = result.gates
        if (
            not isinstance(gate, GateResult)
            or not gate.passed
            or gate.cancelled
            or gate.timed_out
        ):
            raise PromotionAuthorizationError(
                f"candidate[{index}] does not carry one passed terminal gate"
            )
        if not isinstance(artifact.diff_bytes, bytes):
            raise PromotionAuthorizationError(
                f"candidate[{index}] patch bytes are not immutable bytes"
            )
        actual_diff_sha256 = hashlib.sha256(artifact.diff_bytes).hexdigest()
        declared_diff_sha256 = _canonical_sha256(
            artifact.diff_sha256,
            f"candidate[{index}].artifact.diff_sha256",
        )
        if not hmac.compare_digest(actual_diff_sha256, declared_diff_sha256):
            raise PromotionAuthorizationError(
                f"candidate[{index}] patch digest does not match patch bytes"
            )

        artifact_base = _canonical_revision(
            artifact.base_revision,
            f"candidate[{index}].artifact.base_revision",
        )
        result_base = _canonical_revision(
            result.base_revision,
            f"candidate[{index}].result.base_revision",
        )
        if result_base != artifact_base:
            raise PromotionAuthorizationError(
                f"candidate[{index}] result base does not match artifact base"
            )
        if result.task_id != artifact.task_id:
            raise PromotionAuthorizationError(
                f"candidate[{index}] result task_id does not match artifact task_id"
            )
        if result.branch != artifact.branch:
            raise PromotionAuthorizationError(
                f"candidate[{index}] result branch does not match artifact branch"
            )
        if not isinstance(result.task_id, str) or not result.task_id:
            raise PromotionAuthorizationError(
                f"candidate[{index}] task_id must be a non-empty string"
            )
        if not isinstance(result.branch, str) or not result.branch:
            raise PromotionAuthorizationError(
                f"candidate[{index}] branch must be a non-empty string"
            )
        changed_paths = _canonical_changed_paths(
            artifact.changed_paths,
            index=index,
        )

        artifact_snapshot = replace(
            artifact,
            base_revision=artifact_base,
            diff_bytes=bytes(artifact.diff_bytes),
            diff_sha256=actual_diff_sha256,
            changed_paths=changed_paths,
        )
        result_snapshot = replace(
            result,
            task_id=str(result.task_id),
            branch=str(result.branch),
            base_revision=result_base,
            artifact=artifact_snapshot,
        )
        snapshots.append(
            PromotionCandidateSnapshot(
                assignment=getattr(candidate, "assignment", None),
                spec=getattr(candidate, "spec", None),
                result=result_snapshot,
            )
        )
    return tuple(snapshots)


def _candidate_batch_sha256_from_snapshots(
    candidates: Sequence[PromotionCandidateSnapshot],
) -> str:
    rows: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates):
        result = candidate.result
        artifact = result.artifact
        rows.append(
            {
                "index": index,
                "task_id": result.task_id,
                "base_revision": artifact.base_revision,
                "diff_sha256": artifact.diff_sha256,
                "changed_paths": list(artifact.changed_paths),
            }
        )
    return canonical_sha({"schema": "daedalus-candidate-batch/1", "candidates": rows})


def candidate_batch_sha256(candidates: Sequence[Any]) -> str:
    """Digest the exact ordered, validated patch batch intended for promotion."""
    return _candidate_batch_sha256_from_snapshots(
        snapshot_promotion_candidates(candidates)
    )


def resolve_live_target_revision(repo_root: str | Path, target_ref: str) -> str:
    """Read the target ref immediately before the first promotion mutation."""
    ref = _canonical_identifier(target_ref, "target_ref")
    root = Path(repo_root).resolve()
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if proc.returncode != 0:
        raise PromotionAuthorizationError(
            f"cannot resolve live target ref {ref!r}: {(proc.stderr or proc.stdout).strip()}"
        )
    return _canonical_revision(proc.stdout.strip(), "live_target_revision")


def authorize_promotion(
    *,
    consumed_approval: ConsumedOwnerApproval,
    evidence_packet: EvidencePacket,
    candidates: Sequence[Any],
    target_ref: str,
    live_target_revision: str,
) -> PromotionAuthorization:
    """Bind approval, evidence, candidates and the re-read target HEAD exactly.

    This is the pure binding primitive. Effectful callers must use
    :func:`authorize_persisted_promotion`, which first proves that the supplied
    consumption receipt is the exact record held by the authenticated approval
    ledger. Keeping this primitive separate allows deterministic contract tests
    without weakening the live mutation boundary.
    """
    if not isinstance(consumed_approval, ConsumedOwnerApproval):
        raise PromotionAuthorizationError("promotion requires a consumed OwnerApproval")
    if not isinstance(evidence_packet, EvidencePacket):
        raise PromotionAuthorizationError("promotion requires a canonical EvidencePacket")
    snapshots = snapshot_promotion_candidates(candidates)
    verified = consumed_approval.verified
    candidate_sha = _candidate_batch_sha256_from_snapshots(snapshots)
    packet_sha = evidence_packet.digest
    live_revision = _canonical_revision(
        live_target_revision,
        "live_target_revision",
    )
    ref = _canonical_identifier(target_ref, "target_ref")

    comparisons = {
        "operation": (verified.operation, "promote-candidate"),
        "promotion_id": (consumed_approval.promotion_id, consumed_approval.promotion_id),
        "candidate_approval": (verified.candidate_artifact_sha256, candidate_sha),
        "candidate_packet": (evidence_packet.candidate_artifact_sha256, candidate_sha),
        "subject_packet": (evidence_packet.subject_sha256, candidate_sha),
        "evidence_approval": (verified.evidence_packet_sha256, packet_sha),
        "source_revision": (evidence_packet.source_revision, verified.base_revision),
        "target_ref": (verified.target_ref, ref),
        "target_head": (verified.expected_target_revision, live_revision),
    }
    mismatches = sorted(name for name, (actual, expected) in comparisons.items() if actual != expected)
    if evidence_packet.evaluation_status != "passed":
        mismatches.append("evaluation_status")
    if evidence_packet.candidate_artifact_locator != f"artifact-locator:sha256:{candidate_sha}":
        mismatches.append("candidate_locator")
    base_revisions = {
        snapshot.result.artifact.base_revision for snapshot in snapshots
    }
    if base_revisions != {verified.base_revision}:
        mismatches.append("candidate_base_revision")
    if mismatches:
        raise PromotionAuthorizationError(
            "promotion authorization mismatch: " + ", ".join(sorted(set(mismatches)))
        )

    body = {
        "promotion_id": consumed_approval.promotion_id,
        "candidate_artifact_sha256": candidate_sha,
        "evidence_packet_sha256": packet_sha,
        "source_revision": verified.base_revision,
        "target_ref": ref,
        "live_target_revision": live_revision,
        "approval_consumption_sha256": consumed_approval.consumption_sha256,
    }
    return PromotionAuthorization(
        **body,
        authorization_sha256=canonical_sha(body),
    )


def authorize_persisted_promotion(
    *,
    approval_ledger: ApprovalLedger,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    consumed_approval: ConsumedOwnerApproval,
    evidence_packet: EvidencePacket,
    candidates: Sequence[Any],
    target_ref: str,
    live_target_revision: str,
) -> PromotionAuthorization:
    """Require persisted authenticated approval authority before authorization.

    A self-consistent :class:`ConsumedOwnerApproval` is not authority. The
    exact receipt must be present in the supplied approval ledger, its retained
    signed OwnerApproval must authenticate under the independently supplied
    owner keyring, and every persisted canonical byte/column binding must match
    before the pure candidate/evidence/HEAD binding is evaluated.

    This function performs no Git, worktree, provider or repository mutation.
    A dependent Work Packet must make it mandatory inside the live promotion
    lock immediately before the integration worktree is created.
    """
    if not isinstance(approval_ledger, ApprovalLedger):
        raise PromotionAuthorizationError(
            "persisted promotion authorization requires an ApprovalLedger"
        )
    if not isinstance(owner_keyring, Mapping) or not owner_keyring:
        raise PromotionAuthorizationError(
            "persisted promotion authorization requires a non-empty owner keyring"
        )
    if not isinstance(consumed_approval, ConsumedOwnerApproval):
        raise PromotionAuthorizationError(
            "persisted promotion authorization requires a ConsumedOwnerApproval"
        )

    trusted_keyring = dict(owner_keyring)
    try:
        persisted = approval_ledger.verify_consumption(
            consumed_approval,
            keyring=trusted_keyring,
        )
    except Exception as exc:
        raise PromotionAuthorizationError(
            "approval consumption is not authenticated persisted authority"
        ) from exc
    if persisted != consumed_approval:
        raise PromotionAuthorizationError(
            "approval ledger returned a different consumption capability"
        )

    return authorize_promotion(
        consumed_approval=persisted,
        evidence_packet=evidence_packet,
        candidates=candidates,
        target_ref=target_ref,
        live_target_revision=live_target_revision,
    )


__all__ = [
    "PromotionAuthorization",
    "PromotionAuthorizationError",
    "PromotionCandidateSnapshot",
    "authorize_persisted_promotion",
    "authorize_promotion",
    "candidate_batch_sha256",
    "resolve_live_target_revision",
    "snapshot_promotion_candidates",
]
