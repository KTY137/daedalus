"""Sealed promotion authorization for Gate 0.

The existing Kairos integration-worktree machinery is retained, but it may not
start until this module proves that one owner-signed approval, one passed
EvidencePacket, the exact ordered candidate batch, and the live target HEAD all
name the same immutable promotion subject.

D5 (owner decision, ``hybrid with B as root``) makes
:mod:`daedalus.kernel.promotion_trust_root` the authority for "did the owner
approve this". This module is its ONE canonical caller: the structural test
``tests/test_promotion_trust_root_single_caller.py`` fails if any second module
reaches the root, because two callers of a trust root are two promotion paths
wearing one name.

The HMAC approval ledger in :mod:`daedalus.kernel.approvals` is retained as the
demoted second factor. It is re-authenticated on every promotion and every
outcome is written down, but it cannot grant: see the truth table in the trust
root module.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import subprocess
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from daedalus.kernel.approvals import ApprovalLedger, ConsumedOwnerApproval
from daedalus.kernel.promotion_trust_root import (
    PREAUTHORIZATION_STAGE,
    PROMOTION_STAGES,
    SEALED_STAGE,
    PromotionTrustDecision,
    _append_record,
    evaluate_promotion_trust,
)
from daedalus.schemas import EvidencePacket, _identifier, _revision
from daedalus.spine.envelope import canonical_sha

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PromotionAuthorizationError(RuntimeError):
    """Fail-closed refusal before any promotion-side effect."""

    def __init__(self, message: str, *, deny_receipt: Mapping[str, Any] | None = None):
        super().__init__(message)
        #: Populated when the D5 trust root refused. Names the failing factor,
        #: which the truth table requires of every REJECT.
        self.deny_receipt = dict(deny_receipt or {})


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
    #: The content-addressed locator of the signed tag object the D5 root
    #: verified. Empty only for :func:`authorize_promotion`, the pure binding
    #: primitive, which is never a promotion authority on its own.
    owner_approval_ref: str = ""
    #: The evaluated truth-table cell, both factor outcomes and the record
    #: digest. Present on every persisted authorization.
    trust: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "promotion_id": self.promotion_id,
            "candidate_artifact_sha256": self.candidate_artifact_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "source_revision": self.source_revision,
            "target_ref": self.target_ref,
            "live_target_revision": self.live_target_revision,
            "approval_consumption_sha256": self.approval_consumption_sha256,
            "authorization_sha256": self.authorization_sha256,
            "owner_approval_ref": self.owner_approval_ref,
            "trust": dict(self.trust),
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


def _authorize_from_root(
    *,
    decision: PromotionTrustDecision,
    evidence_packet: EvidencePacket,
    snapshots: Sequence[PromotionCandidateSnapshot],
    candidate_sha: str,
    packet_sha: str,
    target_ref: str,
    live_target_revision: str | None,
) -> dict[str, str]:
    """Bind the promotion subject to what the OWNER SIGNED, not to a receipt.

    The pure :func:`authorize_promotion` anchors every comparison on the
    ``VerifiedOwnerApproval`` inside a consumption receipt -- that is, on the
    HMAC factor. Under D5 the HMAC factor cannot grant, so it cannot bind
    either: an approval whose binding is checked against a forgeable receipt is
    bound to a forgeable receipt. Every comparison here is anchored on the
    signed tag instead.

    The signed body carries no target ref, and it does not need one: it names
    the exact ``source_revision`` the owner reviewed, and the live target HEAD
    read under the promotion lock must BE that revision. An approval therefore
    cannot land on a tree that moved after it was signed.
    """
    root = decision.root
    ref = _canonical_identifier(target_ref, "target_ref")
    if live_target_revision is None:
        # Before the promotion lock the live HEAD is genuinely unknown, and
        # reading it there would be a sample the lock then invalidates. The
        # preauthorization therefore binds everything except the live head and
        # substitutes the revision the owner signed. Only that stage may do so.
        if decision.stage != PREAUTHORIZATION_STAGE:
            raise PromotionAuthorizationError(
                "a sealed promotion authorization requires the live target "
                "revision read under the promotion lock",
                deny_receipt=decision.deny_receipt(),
            )
        live_target_revision = root.source_revision
    live_revision = _canonical_revision(live_target_revision, "live_target_revision")

    mismatches: list[str] = []
    comparisons = {
        "candidate_root": (root.candidate_sha256, candidate_sha),
        "evidence_root": (root.evidence_sha256, packet_sha),
        "candidate_packet": (evidence_packet.candidate_artifact_sha256, candidate_sha),
        "subject_packet": (evidence_packet.subject_sha256, candidate_sha),
        "source_revision": (evidence_packet.source_revision, root.source_revision),
        "target_head": (live_revision, root.source_revision),
    }
    mismatches.extend(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if evidence_packet.evaluation_status != "passed":
        mismatches.append("evaluation_status")
    if (
        evidence_packet.candidate_artifact_locator
        != f"artifact-locator:sha256:{candidate_sha}"
    ):
        mismatches.append("candidate_locator")
    base_revisions = {snapshot.result.artifact.base_revision for snapshot in snapshots}
    if base_revisions != {root.source_revision}:
        mismatches.append("candidate_base_revision")
    if mismatches:
        raise PromotionAuthorizationError(
            "promotion authorization mismatch against the owner-signed root: "
            + ", ".join(sorted(set(mismatches))),
            deny_receipt=decision.deny_receipt(),
        )

    return {
        "candidate_artifact_sha256": candidate_sha,
        "evidence_packet_sha256": packet_sha,
        "source_revision": root.source_revision or "",
        "target_ref": ref,
        "live_target_revision": live_revision,
    }


def authorize_persisted_promotion(
    *,
    approval_ledger: ApprovalLedger,
    owner_keyring: Mapping[tuple[str, str], bytes | str],
    consumed_approval: ConsumedOwnerApproval,
    evidence_packet: EvidencePacket,
    candidates: Sequence[Any],
    target_ref: str,
    live_target_revision: str | None,
    repo_root: str | Path,
    promotion_stage: str = SEALED_STAGE,
) -> PromotionAuthorization:
    """THE canonical call into the D5 trust root. Nothing else may call it.

    ``repo_root`` is required because the root is a git-signed tag verified
    against an allowed-signers file read from the COMMITTED tree: there is no
    trust root without a repository to read it out of, and a default would
    quietly choose one.

    ``promotion_stage`` distinguishes the effect-free preauthorization that
    :func:`daedalus.kairos.gated_writes.promote_candidates` performs before any
    lock from the sealed evaluation inside it. Only the sealed stage spends the
    approval's single use, so the preflight cannot burn the owner's approval on
    a promotion that then refuses for an unrelated reason. The default is the
    sealed stage: an unknown caller gets the strict path.

    "The default is the sealed stage" was true and insufficient: a caller who
    PASSED something -- ``'SEALED'``, ``'sealed '``, a typo -- did not get the
    default and did not get the sealed path either, because the trust root
    selected the single-use claim by exact string equality and every other
    string fell through to the branch that skips it. The stage is therefore
    validated here as well as there: rejected at the public keyword, where the
    caller's own name for the value still appears in the error.

    This function performs no worktree, provider or repository mutation. It
    reads git (tag objects, the committed allowed-signers blob) and appends to
    the checkout-external second-factor record.
    """
    if str(promotion_stage) not in PROMOTION_STAGES:
        raise PromotionAuthorizationError(
            f"unknown promotion_stage {promotion_stage!r}: expected one of "
            + ", ".join(repr(s) for s in PROMOTION_STAGES)
            + ". An unrecognised stage is not a milder stage -- it skipped the "
            "single-use claim while still authorising a promotion."
        )
    snapshots = tuple(snapshot_promotion_candidates(candidates))
    if not isinstance(evidence_packet, EvidencePacket):
        raise PromotionAuthorizationError(
            "promotion requires a canonical EvidencePacket"
        )
    candidate_sha = _candidate_batch_sha256_from_snapshots(snapshots)
    packet_sha = evidence_packet.digest

    # The root's source_revision comes from the EvidencePacket rather than from
    # the consumption receipt on purpose: the receipt is the demoted factor, so
    # taking the revision from it would let the demoted factor choose which
    # revision the root is asked about.
    decision = evaluate_promotion_trust(
        repo_root=repo_root,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet_sha,
        source_revision=evidence_packet.source_revision,
        approval_ledger=approval_ledger,
        owner_keyring=owner_keyring,
        consumed_approval=consumed_approval,
        stage=promotion_stage,
    )
    if decision.seams_used:
        # The trust root exposes test seams so the truth-table suite can
        # exercise all four cells without minting an owner signature. A
        # production authorization that used one is not an authorization.
        raise PromotionAuthorizationError(
            "trust-root test seams are not a promotion authority: "
            + ", ".join(decision.seams_used),
            deny_receipt=decision.deny_receipt(),
        )
    if not decision.promote:
        raise PromotionAuthorizationError(
            decision.deny_reason or "sealed promotion refused by the D5 trust root",
            deny_receipt=decision.deny_receipt(),
        )

    body = _authorize_from_root(
        decision=decision,
        evidence_packet=evidence_packet,
        snapshots=snapshots,
        candidate_sha=candidate_sha,
        packet_sha=packet_sha,
        target_ref=target_ref,
        live_target_revision=live_target_revision,
    )

    # THE SECOND FACTOR, RECORDED AND NEVER OBEYED. When the HMAC factor
    # authenticated, its own binding view is computed too. A disagreement is
    # written down as a divergence -- "never silently dropped" -- and changes
    # no verdict, because a factor that can veto is a factor that can grant by
    # withholding a veto.
    second_factor_binding = "not-evaluated: second factor invalid"
    if decision.second_factor.valid:
        try:
            authorize_promotion(
                consumed_approval=consumed_approval,
                evidence_packet=evidence_packet,
                candidates=snapshots,
                target_ref=target_ref,
                live_target_revision=body["live_target_revision"],
            )
            second_factor_binding = "agrees"
        except Exception as exc:  # noqa: BLE001 - advisory, recorded, not fatal
            second_factor_binding = f"diverges: {type(exc).__name__}: {exc}"
            _append_record(
                repo_root,
                {
                    "trust_root_mode": "hybrid-b-as-root",
                    "stage": str(promotion_stage),
                    "candidate_artifact_sha256": candidate_sha,
                    "evidence_packet_sha256": packet_sha,
                    "record_note": "second-factor-binding-divergence",
                    "detail": second_factor_binding,
                    "root_owner_approval_ref": decision.root.owner_approval_ref,
                },
            )

    trust = decision.to_dict()
    trust["second_factor_binding"] = second_factor_binding
    digest_body = dict(body)
    digest_body["promotion_id"] = _identifier(
        getattr(consumed_approval, "promotion_id", "promotion-unbound"),
        "promotion_id",
    )
    digest_body["owner_approval_ref"] = decision.root.owner_approval_ref or ""
    digest_body["trust_record_sha256"] = decision.record_sha256 or ""
    digest_body["approval_consumption_sha256"] = (
        decision.second_factor.consumption_sha256
        or "absent:second-factor-invalid"
    )
    return PromotionAuthorization(
        promotion_id=digest_body["promotion_id"],
        candidate_artifact_sha256=body["candidate_artifact_sha256"],
        evidence_packet_sha256=body["evidence_packet_sha256"],
        source_revision=body["source_revision"],
        target_ref=body["target_ref"],
        live_target_revision=body["live_target_revision"],
        approval_consumption_sha256=digest_body["approval_consumption_sha256"],
        authorization_sha256=canonical_sha(digest_body),
        owner_approval_ref=decision.root.owner_approval_ref or "",
        trust=trust,
    )


__all__ = [
    "PREAUTHORIZATION_STAGE",
    "PROMOTION_STAGES",
    "PromotionAuthorization",
    "PromotionAuthorizationError",
    "PromotionCandidateSnapshot",
    "SEALED_STAGE",
    "authorize_persisted_promotion",
    "authorize_promotion",
    "candidate_batch_sha256",
    "resolve_live_target_revision",
    "snapshot_promotion_candidates",
]
