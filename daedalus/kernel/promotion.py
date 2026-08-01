"""Sealed promotion authorization for Gate 0.

The existing Kairos integration-worktree machinery is retained, but it may not
start until this module proves that one consumed OwnerApproval, one passed
EvidencePacket, the exact ordered candidate batch, and the live target HEAD all
name the same immutable promotion subject.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from daedalus.kernel.approvals import ConsumedOwnerApproval
from daedalus.schemas import EvidencePacket, _identifier, _revision, _sha256
from daedalus.spine.envelope import canonical_sha


class PromotionAuthorizationError(RuntimeError):
    """Fail-closed refusal before any promotion-side effect."""


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


def candidate_batch_sha256(candidates: Sequence[Any]) -> str:
    """Digest the exact ordered, clean patch batch intended for promotion."""
    if not candidates:
        raise PromotionAuthorizationError("promotion candidate batch is empty")
    rows: list[dict[str, object]] = []
    for index, candidate in enumerate(candidates):
        result = getattr(candidate, "result", None)
        artifact = getattr(result, "artifact", None)
        if not bool(getattr(result, "ok", False)) or artifact is None or artifact.is_empty:
            raise PromotionAuthorizationError(
                f"candidate[{index}] is not a clean non-empty gated artifact"
            )
        rows.append(
            {
                "index": index,
                "task_id": str(result.task_id),
                "base_revision": str(artifact.base_revision),
                "diff_sha256": str(artifact.diff_sha256),
                "changed_paths": list(artifact.changed_paths),
            }
        )
    return canonical_sha({"schema": "daedalus-candidate-batch/1", "candidates": rows})


def resolve_live_target_revision(repo_root: str | Path, target_ref: str) -> str:
    """Read the target ref immediately before the first promotion mutation."""
    ref = _identifier(target_ref, "target_ref")
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
    try:
        return _revision(proc.stdout.strip(), "live_target_revision")
    except ValueError as exc:
        raise PromotionAuthorizationError("live target ref did not resolve to a revision") from exc


def authorize_promotion(
    *,
    consumed_approval: ConsumedOwnerApproval,
    evidence_packet: EvidencePacket,
    candidates: Sequence[Any],
    target_ref: str,
    live_target_revision: str,
) -> PromotionAuthorization:
    """Bind approval, evidence, candidates and the re-read target HEAD exactly."""
    if not isinstance(consumed_approval, ConsumedOwnerApproval):
        raise PromotionAuthorizationError("promotion requires a consumed OwnerApproval")
    if not isinstance(evidence_packet, EvidencePacket):
        raise PromotionAuthorizationError("promotion requires a canonical EvidencePacket")
    verified = consumed_approval.verified
    candidate_sha = candidate_batch_sha256(candidates)
    packet_sha = evidence_packet.digest
    live_revision = _revision(live_target_revision, "live_target_revision")
    ref = _identifier(target_ref, "target_ref")

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
        str(candidate.result.artifact.base_revision) for candidate in candidates
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


__all__ = [
    "PromotionAuthorization",
    "PromotionAuthorizationError",
    "authorize_promotion",
    "candidate_batch_sha256",
    "resolve_live_target_revision",
]
