"""Sealed promotion authorization for Gate 0.

The existing Kairos integration-worktree machinery is retained, but it may not
start until this module proves that one persisted and re-authenticated
OwnerApproval consumption, one passed EvidencePacket, the exact ordered
candidate batch, and the live target HEAD all name the same immutable promotion
subject.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.kernel.approvals import ApprovalLedger, ConsumedOwnerApproval
from daedalus.schemas import EvidencePacket, _identifier, _revision
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
    "authorize_persisted_promotion",
    "authorize_promotion",
    "candidate_batch_sha256",
    "resolve_live_target_revision",
]
