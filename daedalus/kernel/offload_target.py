"""Internal atomic publication primitive for the canonical offload executor.

This module exposes the inert after-observation and error records.  The one
effectful function is deliberately private and accepts only a fully bound
``AuthorizedOffloadExecution`` plus a ledger-authenticated live start and the
CAS-backed model/chat observations.  Candidate bytes are replayed from
canonical CAS; callers cannot supply substitute bytes or widen the write cap.

Canonical publication currently requires Linux ``renameat2(RENAME_EXCHANGE)``
through an anchored parent descriptor.  Other hosts are refused before the
durable publication commit.  Pre-existing staging or recovery paths are
reconciliation evidence and are never glob-deleted or silently reused.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.kairos.worktree import GitWorktreeManager
from daedalus.kernel.effects import (
    EffectExecutionClaim,
    EffectPublicationFinalization,
    EffectLeaseLedger,
    EffectLeaseError,
    EffectStartResult,
)
from daedalus.kernel.offload_authority import (
    AuthorizedOffloadExecution,
    OffloadAuthorityBindingError,
    authorize_offload_execution,
)
from daedalus.kernel.offload_observations import (
    OllamaChatObservation,
    OllamaModelObservation,
    OffloadObservationError,
    TargetBeforeObservation,
    TaskAttemptWorkspaceAttestation,
    _directory_chain_sha256,
    _identity_sha256,
    _is_link_or_reparse,
    _lexical_absolute,
    _require_git_blob_identity,
    _stable_regular_bytes,
    _target_index_entry,
)
from daedalus.kernel.offload_protocol import parse_offload_chat_response
from daedalus.kernel.resolved_kill_switch import ResolvedKillSwitch
from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _artifact_locator,
    _identifier,
    _locator_sha256,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.storage import ArtifactStore, ArtifactStoreError
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.killswitch import LoopHalted


_PUBLICATION_STRATEGY = "linux-renameat2-exchange-noreplace-retain-v1"
_DURABILITY_PROFILE = "file-fsync+directory-fsync-v1"
_METADATA_PROFILE_ID = "linux-owner-mode-no-xattrs-v1"
_METADATA_PROFILE_ARTIFACT_KIND = "daedalus.offload-target-metadata-profile/1"
_EFFECT_COMMITMENT_ARTIFACT_KIND = "daedalus.offload-target-effect-commitment/1"


class OffloadTargetError(RuntimeError):
    """Neutral base for safe refusals and crossed effect boundaries."""


class OffloadTargetWriteError(OffloadTargetError):
    """The target was provably not published as a candidate."""


class OffloadTargetDeadlineExceeded(OffloadTargetWriteError, TimeoutError):
    """The shared deadline expired before target publication began."""


class OffloadTargetWriteIndeterminate(OffloadTargetError):
    """Publication was attempted but its complete final state is not provable."""

    def __init__(
        self,
        message: str,
        *,
        after_observation: "TargetAfterObservation | None" = None,
        candidate_present: bool | None = None,
        staging_present: bool | None = None,
        recovery_present: bool | None = None,
    ) -> None:
        self.after_observation = after_observation
        self.candidate_present = candidate_present
        self.staging_present = staging_present
        self.recovery_present = recovery_present
        super().__init__(message)


@dataclass(frozen=True)
class OffloadTargetMetadataProfile(CanonicalContract):
    """Narrow Linux metadata profile proved before publication."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-target-metadata-profile"

    profile_id: str
    source_revision: str
    target_before_observation_sha256: str
    filesystem_mode: int
    owner_uid: int
    owner_gid: int
    target_link_count: int
    filesystem_flags: int
    target_xattrs_sha256: str
    parent_filesystem_mode: int
    parent_owner_uid: int
    parent_owner_gid: int
    parent_xattrs_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        if self.profile_id != _METADATA_PROFILE_ID:
            raise ValueError("unsupported offload target metadata profile")
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        for name in (
            "target_before_observation_sha256",
            "target_xattrs_sha256",
            "parent_xattrs_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        for name in (
            "filesystem_mode",
            "owner_uid",
            "owner_gid",
            "parent_filesystem_mode",
            "parent_owner_uid",
            "parent_owner_gid",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if type(self.target_link_count) is not int or self.target_link_count != 1:
            raise ValueError("metadata profile requires exactly one target hard link")
        if type(self.filesystem_flags) is not int or self.filesystem_flags != 0:
            raise ValueError("metadata profile requires zero Linux filesystem flags")
        if self.filesystem_mode not in {0o644, 0o755}:
            raise ValueError("metadata profile mode must be exactly 0644 or 0755")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("metadata profile source revision mismatches provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                self.target_before_observation_sha256,
                self.target_xattrs_sha256,
                self.parent_xattrs_sha256,
            ),
            "offload target metadata profile",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadTargetMetadataProfile":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OffloadTargetEffectCommitment(CanonicalContract):
    """Retained, timestamp-free instructions durably committed before I/O."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.offload-target-effect-commitment"

    lease_sha256: str
    source_revision: str
    execution_plan_sha256: str
    execution_request_sha256: str
    start_receipt_sha256: str
    claim_receipt_sha256: str
    workspace_attestation_sha256: str
    target_before_observation_sha256: str
    ollama_model_observation_sha256: str
    ollama_chat_observation_sha256: str
    artifact_store_root_sha256: str
    candidate_artifact_locator: str
    candidate_sha256: str
    candidate_size: int
    target_path: str
    staging_path: str
    staging_path_sha256: str
    recovery_path: str
    recovery_path_sha256: str
    target_before_content_sha256: str
    target_before_size: int
    target_before_file_identity_sha256: str
    target_parent_chain_sha256: str
    target_git_mode: str
    target_filesystem_mode: int
    metadata_profile_sha256: str
    metadata_profile_artifact_locator: str
    publication_strategy: str
    durability_profile: str
    kill_switch_ref: str
    kill_switch_generation: int
    kill_switch_path_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        from daedalus.kernel.contracts import (
            _portable_target_path,
            offload_recovery_path_sha256,
            offload_staging_path_sha256,
        )

        digest_fields = (
            "lease_sha256",
            "execution_plan_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "claim_receipt_sha256",
            "workspace_attestation_sha256",
            "target_before_observation_sha256",
            "ollama_model_observation_sha256",
            "ollama_chat_observation_sha256",
            "artifact_store_root_sha256",
            "candidate_sha256",
            "staging_path_sha256",
            "recovery_path_sha256",
            "target_before_content_sha256",
            "target_before_file_identity_sha256",
            "target_parent_chain_sha256",
            "metadata_profile_sha256",
            "kill_switch_path_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "candidate_artifact_locator",
            _artifact_locator(
                self.candidate_artifact_locator, "candidate_artifact_locator"
            ),
        )
        object.__setattr__(
            self,
            "metadata_profile_artifact_locator",
            _artifact_locator(
                self.metadata_profile_artifact_locator,
                "metadata_profile_artifact_locator",
            ),
        )
        for name in ("target_path", "staging_path", "recovery_path"):
            object.__setattr__(
                self,
                name,
                _portable_target_path(getattr(self, name), name),
            )
        if self.staging_path_sha256 != offload_staging_path_sha256(
            self.staging_path
        ):
            raise ValueError("commitment staging path digest mismatch")
        if self.recovery_path_sha256 != offload_recovery_path_sha256(
            self.recovery_path
        ):
            raise ValueError("commitment recovery path digest mismatch")
        if len({self.target_path, self.staging_path, self.recovery_path}) != 3:
            raise ValueError("commitment paths must be distinct")
        for name in (
            "candidate_size",
            "target_before_size",
            "target_filesystem_mode",
            "kill_switch_generation",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.target_git_mode not in {"100644", "100755"}:
            raise ValueError("unsupported target Git mode")
        expected_mode = 0o755 if self.target_git_mode == "100755" else 0o644
        if self.target_filesystem_mode != expected_mode:
            raise ValueError("target Git and filesystem modes disagree")
        if self.publication_strategy != _PUBLICATION_STRATEGY:
            raise ValueError("unsupported publication strategy")
        if self.durability_profile != _DURABILITY_PROFILE:
            raise ValueError("unsupported durability profile")
        if self.kill_switch_ref != f"kill-switch:{self.kill_switch_path_sha256}":
            raise ValueError("commitment kill-switch ref/path binding mismatch")
        if self.kill_switch_generation < 1:
            raise ValueError("commitment kill-switch generation must be positive")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("effect commitment source revision mismatches provenance")
        _require_provenance_inputs(
            self.provenance,
            (
                *(getattr(self, name) for name in digest_fields),
                _locator_sha256(self.candidate_artifact_locator),
                _locator_sha256(self.metadata_profile_artifact_locator),
            ),
            "offload target effect commitment",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "OffloadTargetEffectCommitment":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class OffloadTargetPublicationResult:
    """Exact inert records returned after a clean publication session."""

    effect_commitment: OffloadTargetEffectCommitment
    effect_commitment_artifact_locator: str
    metadata_profile: OffloadTargetMetadataProfile
    metadata_profile_artifact_locator: str
    after_observation: "TargetAfterObservation"
    finalization: EffectPublicationFinalization

    def __post_init__(self) -> None:
        if type(self.effect_commitment) is not OffloadTargetEffectCommitment:
            raise TypeError("effect_commitment must be exact")
        object.__setattr__(
            self,
            "effect_commitment_artifact_locator",
            _artifact_locator(
                self.effect_commitment_artifact_locator,
                "effect_commitment_artifact_locator",
            ),
        )
        if type(self.metadata_profile) is not OffloadTargetMetadataProfile:
            raise TypeError("metadata_profile must be exact")
        object.__setattr__(
            self,
            "metadata_profile_artifact_locator",
            _artifact_locator(
                self.metadata_profile_artifact_locator,
                "metadata_profile_artifact_locator",
            ),
        )
        if type(self.after_observation) is not TargetAfterObservation:
            raise TypeError("after_observation must be exact")
        if type(self.finalization) is not EffectPublicationFinalization:
            raise TypeError("finalization must be exact")
        if (
            self.after_observation.effect_commitment_sha256
            != self.effect_commitment.digest
            or self.after_observation.effect_commitment_artifact_locator
            != self.effect_commitment_artifact_locator
            or self.after_observation.metadata_profile_sha256
            != self.metadata_profile.digest
            or self.after_observation.metadata_profile_artifact_locator
            != self.metadata_profile_artifact_locator
            or self.effect_commitment.metadata_profile_sha256
            != self.metadata_profile.digest
            or self.effect_commitment.metadata_profile_artifact_locator
            != self.metadata_profile_artifact_locator
            or self.after_observation.publication_outcome_receipt_sha256
            != self.finalization.outcome_receipt.receipt_sha256
        ):
            raise OffloadTargetError("publication result record chain mismatch")


@dataclass(frozen=True)
class TargetAfterObservation(CanonicalContract):
    """Exact target and authority chain observed after atomic replacement."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.target-after-observation"

    execution_plan_sha256: str
    execution_request_sha256: str
    start_receipt_sha256: str
    claim_receipt_sha256: str
    effect_commitment_sha256: str
    effect_commitment_artifact_locator: str
    publication_commit_receipt_sha256: str
    publication_outcome_receipt_sha256: str
    metadata_profile_sha256: str
    metadata_profile_artifact_locator: str
    publication_strategy: str
    durability_profile: str
    ollama_chat_observation_sha256: str
    candidate_artifact_locator: str
    workspace_attestation_sha256: str
    target_before_observation_sha256: str
    source_revision: str
    target_path: str
    staging_path: str
    staging_path_sha256: str
    recovery_path: str
    recovery_path_sha256: str
    recovery_retained: bool
    recovery_content_sha256: str
    recovery_byte_length: int
    recovery_file_identity_sha256: str
    target_kind: str
    content_sha256: str
    byte_length: int
    git_mode: str
    filesystem_mode: int
    encoding: str
    file_identity_sha256: str
    parent_chain_sha256: str
    durability_assurance: str
    published_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        from daedalus.kernel.contracts import (
            _portable_target_path,
            offload_recovery_path_sha256,
            offload_staging_path_sha256,
        )

        digest_fields = (
            "execution_plan_sha256",
            "execution_request_sha256",
            "start_receipt_sha256",
            "claim_receipt_sha256",
            "effect_commitment_sha256",
            "publication_commit_receipt_sha256",
            "publication_outcome_receipt_sha256",
            "metadata_profile_sha256",
            "ollama_chat_observation_sha256",
            "workspace_attestation_sha256",
            "target_before_observation_sha256",
            "staging_path_sha256",
            "recovery_path_sha256",
            "recovery_content_sha256",
            "recovery_file_identity_sha256",
            "content_sha256",
            "file_identity_sha256",
            "parent_chain_sha256",
        )
        for name in digest_fields:
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(self, "target_path", _portable_target_path(self.target_path))
        object.__setattr__(
            self,
            "staging_path",
            _portable_target_path(self.staging_path, "staging_path"),
        )
        if self.staging_path == self.target_path:
            raise ValueError("staging_path must differ from target_path")
        if self.staging_path_sha256 != offload_staging_path_sha256(self.staging_path):
            raise ValueError("staging_path_sha256 mismatches staging_path")
        object.__setattr__(
            self,
            "recovery_path",
            _portable_target_path(self.recovery_path, "recovery_path"),
        )
        if self.recovery_path in {self.target_path, self.staging_path}:
            raise ValueError("recovery_path must differ from target and staging paths")
        if self.recovery_path_sha256 != offload_recovery_path_sha256(
            self.recovery_path
        ):
            raise ValueError("recovery_path_sha256 mismatches recovery_path")
        object.__setattr__(
            self,
            "candidate_artifact_locator",
            _artifact_locator(
                self.candidate_artifact_locator, "candidate_artifact_locator"
            ),
        )
        object.__setattr__(
            self,
            "effect_commitment_artifact_locator",
            _artifact_locator(
                self.effect_commitment_artifact_locator,
                "effect_commitment_artifact_locator",
            ),
        )
        object.__setattr__(
            self,
            "metadata_profile_artifact_locator",
            _artifact_locator(
                self.metadata_profile_artifact_locator,
                "metadata_profile_artifact_locator",
            ),
        )
        if self.target_kind != "existing-regular-utf8-file":
            raise ValueError(
                "target_kind must be exactly 'existing-regular-utf8-file'"
            )
        if self.encoding != "utf-8":
            raise ValueError("encoding must be exactly 'utf-8'")
        if self.git_mode not in {"100644", "100755"}:
            raise ValueError("git_mode must be 100644 or 100755")
        if self.recovery_retained is not True:
            raise ValueError("target-after requires retained recovery evidence")
        for name in ("byte_length", "filesystem_mode", "recovery_byte_length"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        if self.durability_assurance not in {
            "directory-fsync",
        }:
            raise ValueError("unknown durability_assurance")
        if self.publication_strategy != _PUBLICATION_STRATEGY:
            raise ValueError("unknown publication_strategy")
        if self.durability_profile != _DURABILITY_PROFILE:
            raise ValueError("unknown durability_profile")
        object.__setattr__(
            self, "published_at", _utc_timestamp(self.published_at, "published_at")
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("target-after source_revision must match provenance")
        if self.provenance.created_at != self.published_at:
            raise ValueError("target-after published_at must equal provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (
                *(getattr(self, name) for name in digest_fields),
                _locator_sha256(self.candidate_artifact_locator),
                _locator_sha256(self.effect_commitment_artifact_locator),
                _locator_sha256(self.metadata_profile_artifact_locator),
            ),
            "target-after observation",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TargetAfterObservation":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def verify_current(
        self,
        *,
        authorized: AuthorizedOffloadExecution,
        chat_observation: OllamaChatObservation,
        effect_commitment: OffloadTargetEffectCommitment,
        effect_commitment_artifact_locator: str,
        metadata_profile: OffloadTargetMetadataProfile,
        finalization: EffectPublicationFinalization,
        artifact_store: ArtifactStore,
        manager: GitWorktreeManager,
        workspace_path: str | os.PathLike[str],
    ) -> None:
        """Re-prove the exact published inode and CAS bytes before terminalization."""

        if type(authorized) is not AuthorizedOffloadExecution:
            raise TypeError("authorized must be an exact AuthorizedOffloadExecution")
        if type(chat_observation) is not OllamaChatObservation:
            raise TypeError("chat_observation must be an exact OllamaChatObservation")
        if type(effect_commitment) is not OffloadTargetEffectCommitment:
            raise TypeError("effect_commitment must be exact")
        if type(metadata_profile) is not OffloadTargetMetadataProfile:
            raise TypeError("metadata_profile must be exact")
        if type(finalization) is not EffectPublicationFinalization:
            raise TypeError("finalization must be exact")
        if not isinstance(artifact_store, ArtifactStore):
            raise TypeError("artifact_store must be an ArtifactStore")
        if not isinstance(manager, GitWorktreeManager):
            raise TypeError("manager must be a GitWorktreeManager")
        plan = authorized.plan
        expected = {
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": authorized.execution.digest,
            "start_receipt_sha256": finalization.start_receipt.receipt_sha256,
            "claim_receipt_sha256": finalization.claim_receipt.receipt_sha256,
            "effect_commitment_sha256": effect_commitment.digest,
            "effect_commitment_artifact_locator": (
                effect_commitment_artifact_locator
            ),
            "publication_commit_receipt_sha256": (
                finalization.commit_receipt.receipt_sha256
            ),
            "publication_outcome_receipt_sha256": (
                finalization.outcome_receipt.receipt_sha256
            ),
            "metadata_profile_sha256": metadata_profile.digest,
            "publication_strategy": effect_commitment.publication_strategy,
            "durability_profile": effect_commitment.durability_profile,
            "ollama_chat_observation_sha256": chat_observation.digest,
            "candidate_artifact_locator": chat_observation.candidate_artifact_locator,
            "workspace_attestation_sha256": authorized.workspace_attestation.digest,
            "target_before_observation_sha256": authorized.target_before.digest,
            "source_revision": plan.source_revision,
            "target_path": plan.target_path,
            "staging_path": plan.staging_path,
            "staging_path_sha256": plan.staging_path_sha256,
            "recovery_path": plan.recovery_path,
            "recovery_path_sha256": plan.recovery_path_sha256,
        }
        mismatches = sorted(
            name for name, value in expected.items() if getattr(self, name) != value
        )
        if mismatches:
            raise OffloadObservationError(
                "target-after authority binding changed: " + ", ".join(mismatches)
            )
        if artifact_store.root_sha256 != plan.artifact_store_root_sha256:
            raise OffloadObservationError("target-after artifact store binding changed")
        try:
            finalization.completion_capability.verify_publication(
                finalization.commit_receipt,
                finalization.outcome_receipt,
                require_finalizable=True,
            )
        except EffectLeaseError as exc:
            raise OffloadObservationError(
                "target-after publication finalization is not live and clean"
            ) from exc
        if (
            finalization.commit_receipt.effect_commitment_sha256
            != effect_commitment.digest
            or effect_commitment.metadata_profile_sha256 != metadata_profile.digest
            or effect_commitment.ollama_chat_observation_sha256
            != chat_observation.digest
        ):
            raise OffloadObservationError(
                "target-after commitment/finalization chain changed"
            )
        if self.published_at != finalization.outcome_receipt.published_at:
            raise OffloadObservationError(
                "target-after timestamp differs from publication outcome"
            )
        commitment_locator = _load_locator_uri(
            artifact_store, effect_commitment_artifact_locator
        )
        commitment_raw = artifact_store.get_bytes(effect_commitment.digest)
        if (
            commitment_locator.artifact_sha256 != effect_commitment.digest
            or commitment_raw != effect_commitment.to_json().encode("ascii")
        ):
            raise OffloadObservationError(
                "target-after effect commitment CAS replay changed"
            )

        workspace = _lexical_absolute(workspace_path)
        authorized.workspace_attestation.verify_current(manager, workspace)
        target_path = workspace.joinpath(*self.target_path.split("/"))
        staging_path = workspace.joinpath(*self.staging_path.split("/"))
        recovery_path = workspace.joinpath(*self.recovery_path.split("/"))
        if _stage_present(staging_path) is not False or _stage_present(recovery_path) is not False:
            raise OffloadObservationError(
                "target-after staging or recovery evidence is still present"
            )
        raw, metadata = _stable_regular_bytes(target_path, role="target after write")
        locator = _load_locator_uri(artifact_store, self.candidate_artifact_locator)
        candidate = artifact_store.get_bytes(locator.uri)
        parent_sha = _directory_chain_sha256(
            workspace,
            target_path.parent,
            role="workspace-to-target-parent",
        )
        observed = {
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "byte_length": len(raw),
            "filesystem_mode": stat.S_IMODE(metadata.st_mode),
            "file_identity_sha256": _identity_sha256(
                target_path, metadata, role="target file after write"
            ),
            "parent_chain_sha256": parent_sha,
        }
        _verify_metadata_profile(
            target_path,
            metadata,
            metadata_profile,
            role="current published target",
        )
        if (
            _empty_xattrs_sha256(target_path.parent, role="target parent")
            != metadata_profile.parent_xattrs_sha256
        ):
            mismatches = ["parent_xattrs"]
        else:
            mismatches = []
        mismatches.extend(
            sorted(
                name
                for name, value in observed.items()
                if getattr(self, name) != value
            )
        )
        if raw != candidate:
            mismatches.append("candidate_artifact_bytes")
        if mismatches:
            raise OffloadObservationError(
                "target-after observation no longer matches: "
                + ", ".join(sorted(set(mismatches)))
            )


def _require_remaining(deadline_monotonic: float) -> None:
    if time.monotonic() >= deadline_monotonic:
        raise OffloadTargetDeadlineExceeded(
            "shared offload deadline expired before target publication"
        )


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(descriptor, view[written:])
        if count < 1:
            raise OSError("short write while staging offload target")
        written += count


def _set_staging_mode(descriptor: int, mode: int) -> None:
    fchmod = getattr(os, "fchmod", None)
    if not callable(fchmod):
        raise OffloadTargetWriteError(
            "canonical target publication requires descriptor-relative chmod"
        )
    fchmod(descriptor, mode)


def _load_locator_uri(store: ArtifactStore, uri: str):
    prefix = "artifact-locator:sha256:"
    if not uri.startswith(prefix):
        raise OffloadTargetWriteError("artifact locator is not canonical")
    locator = store.verify(store.load_locator(uri[len(prefix) :]))
    if locator.locator_uri != uri:
        raise OffloadTargetWriteError("artifact locator identity changed")
    return locator


def _metadata_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return (
        int(getattr(metadata, "st_dev", 0)),
        int(getattr(metadata, "st_ino", 0)),
        stat.S_IFMT(metadata.st_mode),
    )


def _empty_xattrs_sha256(path_or_descriptor: Path | int, *, role: str) -> str:
    listxattr = getattr(os, "listxattr", None)
    if not callable(listxattr):
        raise OffloadTargetWriteError(
            f"{role} extended attributes cannot be inspected on this host"
        )
    try:
        if isinstance(path_or_descriptor, int):
            names = tuple(sorted(listxattr(path_or_descriptor)))
        else:
            names = tuple(
                sorted(listxattr(path_or_descriptor, follow_symlinks=False))
            )
    except (OSError, TypeError) as exc:
        raise OffloadTargetWriteError(
            f"{role} extended attributes could not be inspected"
        ) from exc
    if names:
        raise OffloadTargetWriteError(
            f"{role} carries unsupported extended attributes or ACLs"
        )
    return canonical_sha(list(names))


def _linux_filesystem_flags(descriptor: int, *, role: str) -> int:
    """Read exact inode flags through ``FS_IOC_GETFLAGS`` or refuse."""

    if descriptor < 0 or os.name != "posix" or not sys.platform.startswith("linux"):
        raise OffloadTargetWriteError(
            f"{role} Linux filesystem flags require an anchored descriptor"
        )
    try:
        import array
        import fcntl

        value = array.array("L", [0])
        # Linux defines FS_IOC_GETFLAGS as _IOR('f', 1, long).  Deriving the
        # size keeps the ioctl exact on both 32- and 64-bit userspace.
        request = 0x80000000 | (value.itemsize << 16) | (ord("f") << 8) | 1
        fcntl.ioctl(descriptor, request, value, True)
        flags = int(value[0])
    except (ImportError, OSError, TypeError, ValueError) as exc:
        raise OffloadTargetWriteError(
            f"{role} Linux filesystem flags could not be inspected exactly"
        ) from exc
    if flags != 0:
        raise OffloadTargetWriteError(
            f"{role} carries unsupported Linux filesystem flags"
        )
    return flags


def _open_regular_anchor(
    path: Path,
    metadata: os.stat_result,
    *,
    parent_descriptor: int,
    role: str,
) -> int:
    """Open and identity-check one regular sibling without following links."""

    if parent_descriptor < 0:
        raise OffloadTargetWriteError(f"{role} requires an anchored parent")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
    except OSError as exc:
        raise OffloadTargetWriteError(f"{role} could not be opened exactly") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or _metadata_identity(opened) != _metadata_identity(metadata)
        ):
            raise OffloadTargetWriteError(
                f"{role} identity changed while its descriptor was opened"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _capture_metadata_profile(
    *,
    target_path: Path,
    parent_path: Path,
    target_metadata: os.stat_result,
    target_before: TargetBeforeObservation,
    parent_descriptor: int,
    origin: str,
) -> OffloadTargetMetadataProfile:
    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise OffloadTargetWriteError(
            "canonical target publication currently supports Linux only"
        )
    if not hasattr(os, "geteuid") or not hasattr(os, "getegid"):
        raise OffloadTargetWriteError("Linux ownership cannot be resolved exactly")
    if int(getattr(target_metadata, "st_nlink", 0)) != 1:
        raise OffloadTargetWriteError(
            "target hard-link count is outside the supported metadata profile"
        )
    expected_mode = 0o755 if target_before.git_mode == "100755" else 0o644
    actual_mode = stat.S_IMODE(target_metadata.st_mode)
    if actual_mode != expected_mode or target_before.filesystem_mode != expected_mode:
        raise OffloadTargetWriteError(
            "target mode is outside the exact 0644/0755 metadata profile"
        )
    _verify_parent_anchor(parent_descriptor, parent_path)
    parent_metadata = os.fstat(parent_descriptor)
    if not stat.S_ISDIR(parent_metadata.st_mode) or _is_link_or_reparse(
        parent_metadata
    ):
        raise OffloadTargetWriteError("target parent is not an exact directory")
    expected_uid = int(os.geteuid())
    expected_gid = (
        int(parent_metadata.st_gid)
        if parent_metadata.st_mode & stat.S_ISGID
        else int(os.getegid())
    )
    if (
        int(getattr(target_metadata, "st_uid", -1)) != expected_uid
        or int(getattr(target_metadata, "st_gid", -1)) != expected_gid
    ):
        raise OffloadTargetWriteError(
            "target ownership cannot be reproduced by a bounded staging file"
        )
    target_descriptor = _open_regular_anchor(
        target_path,
        target_metadata,
        parent_descriptor=parent_descriptor,
        role="target metadata profile",
    )
    try:
        filesystem_flags = _linux_filesystem_flags(
            target_descriptor,
            role="target",
        )
        target_xattrs = _empty_xattrs_sha256(target_descriptor, role="target")
    finally:
        os.close(target_descriptor)
    parent_xattrs = _empty_xattrs_sha256(
        parent_descriptor,
        role="target parent",
    )
    return OffloadTargetMetadataProfile(
        profile_id=_METADATA_PROFILE_ID,
        source_revision=target_before.source_revision,
        target_before_observation_sha256=target_before.digest,
        filesystem_mode=actual_mode,
        owner_uid=expected_uid,
        owner_gid=expected_gid,
        target_link_count=1,
        filesystem_flags=filesystem_flags,
        target_xattrs_sha256=target_xattrs,
        parent_filesystem_mode=stat.S_IMODE(parent_metadata.st_mode),
        parent_owner_uid=int(parent_metadata.st_uid),
        parent_owner_gid=int(parent_metadata.st_gid),
        parent_xattrs_sha256=parent_xattrs,
        provenance=ContractProvenance(
            origin=origin,
            source_revision=target_before.source_revision,
            created_at=target_before.provenance.created_at,
            input_digests=(target_before.digest, target_xattrs, parent_xattrs),
            trace_id=target_before.provenance.trace_id,
        ),
    )


def _verify_metadata_profile(
    path: Path,
    metadata: os.stat_result,
    profile: OffloadTargetMetadataProfile,
    *,
    role: str,
    parent_descriptor: int,
) -> None:
    mismatches = sorted(
        name
        for name, actual, expected in (
            ("filesystem_mode", stat.S_IMODE(metadata.st_mode), profile.filesystem_mode),
            ("owner_uid", int(getattr(metadata, "st_uid", -1)), profile.owner_uid),
            ("owner_gid", int(getattr(metadata, "st_gid", -1)), profile.owner_gid),
            ("link_count", int(getattr(metadata, "st_nlink", 0)), 1),
        )
        if actual != expected
    )
    descriptor = _open_regular_anchor(
        path,
        metadata,
        parent_descriptor=parent_descriptor,
        role=role,
    )
    try:
        if (
            _linux_filesystem_flags(descriptor, role=role)
            != profile.filesystem_flags
        ):
            mismatches.append("filesystem_flags")
        if (
            _empty_xattrs_sha256(descriptor, role=role)
            != profile.target_xattrs_sha256
        ):
            mismatches.append("xattrs")
    finally:
        os.close(descriptor)
    if mismatches:
        raise OffloadTargetWriteError(
            f"{role} violates the committed metadata profile: "
            + ", ".join(sorted(set(mismatches)))
        )


def _verify_parent_metadata_profile(
    parent_descriptor: int,
    profile: OffloadTargetMetadataProfile,
    *,
    role: str,
) -> None:
    """Re-prove the exact parent mode/ownership/default ACL profile."""

    if parent_descriptor < 0:
        raise OffloadTargetWriteError(f"{role} requires an anchored parent")
    metadata = os.fstat(parent_descriptor)
    mismatches = sorted(
        name
        for name, actual, expected in (
            (
                "filesystem_mode",
                stat.S_IMODE(metadata.st_mode),
                profile.parent_filesystem_mode,
            ),
            ("owner_uid", int(getattr(metadata, "st_uid", -1)), profile.parent_owner_uid),
            ("owner_gid", int(getattr(metadata, "st_gid", -1)), profile.parent_owner_gid),
        )
        if actual != expected
    )
    if not stat.S_ISDIR(metadata.st_mode):
        mismatches.append("file_type")
    if (
        _empty_xattrs_sha256(parent_descriptor, role=role)
        != profile.parent_xattrs_sha256
    ):
        mismatches.append("xattrs_or_default_acl")
    if mismatches:
        raise OffloadTargetWriteError(
            f"{role} violates the committed parent metadata profile: "
            + ", ".join(sorted(set(mismatches)))
        )


def _open_parent_anchor(path: Path) -> int:
    """Hold the exact Linux target parent across staging and rename."""

    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise OffloadTargetWriteError(
            "canonical target publication currently supports Linux only"
        )
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        live = os.lstat(path)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or _is_link_or_reparse(live)
            or _metadata_identity(opened) != _metadata_identity(live)
        ):
            raise OffloadTargetWriteError(
                "target parent changed while its identity anchor was opened"
            )
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _verify_parent_anchor(descriptor: int, path: Path) -> None:
    if descriptor < 0:
        return
    try:
        opened = os.fstat(descriptor)
        live = os.lstat(path)
    except OSError as exc:
        raise OffloadTargetWriteError("target parent anchor is no longer observable") from exc
    if (
        not stat.S_ISDIR(opened.st_mode)
        or _is_link_or_reparse(live)
        or _metadata_identity(opened) != _metadata_identity(live)
    ):
        raise OffloadTargetWriteError("target parent changed after it was anchored")


def _fsync_directory(path: Path, descriptor: int = -1) -> str:
    if descriptor >= 0:
        os.fsync(descriptor)
        return "directory-fsync"
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return "directory-fsync"


def _stage_present(path: Path, parent_descriptor: int = -1) -> bool | None:
    try:
        if parent_descriptor >= 0:
            os.stat(path.name, dir_fd=parent_descriptor, follow_symlinks=False)
        else:
            os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    return True


def _require_atomic_exchange_support() -> None:
    """Fail before staging when this host cannot retain displaced target bytes."""

    if os.name != "posix" or not sys.platform.startswith("linux"):
        raise OffloadTargetWriteError(
            "canonical target publication currently supports Linux renameat2 only"
        )
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if getattr(libc, "renameat2", None) is None:
        raise OffloadTargetWriteError(
            "host lacks a lossless atomic exchange primitive; refusing publication"
        )


def _posix_exchange(
    left: Path,
    right: Path,
    parent_descriptor: int,
) -> None:
    """Atomically exchange two sibling names through the anchored directory."""

    import ctypes

    if parent_descriptor < 0:
        raise OffloadTargetWriteError("POSIX atomic exchange requires a parent anchor")
    libc = ctypes.CDLL(None, use_errno=True)
    left_name = os.fsencode(left.name)
    right_name = os.fsencode(right.name)
    rename_exchange = 0x00000002
    function = libc.renameat2
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        parent_descriptor,
        left_name,
        parent_descriptor,
        right_name,
        rename_exchange,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), f"{left.name}<->{right.name}")


def _posix_rename_noreplace(
    source: Path,
    destination: Path,
    parent_descriptor: int,
) -> None:
    """Atomically move one sibling name without replacing raced evidence."""

    import ctypes

    if parent_descriptor < 0:
        raise OffloadTargetWriteError(
            "POSIX no-replace rename requires a parent anchor"
        )
    libc = ctypes.CDLL(None, use_errno=True)
    function = libc.renameat2
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        parent_descriptor,
        os.fsencode(source.name),
        parent_descriptor,
        os.fsencode(destination.name),
        0x00000001,
    )
    if result != 0:
        error = ctypes.get_errno()
        raise OSError(
            error,
            os.strerror(error),
            f"{source.name}->{destination.name}",
        )


def _swap_candidate_into_target(
    *,
    staging_path: Path,
    target_path: Path,
    recovery_path: Path,
    parent_descriptor: int,
) -> None:
    """Publish candidate and retain the exact displaced target at recovery."""

    _posix_exchange(staging_path, target_path, parent_descriptor)
    # Exchange leaves the displaced target at staging. Move that exact name to
    # recovery without replacing a raced artifact and without a separate
    # unlink-by-name window. Successful publication retains recovery evidence.
    _posix_rename_noreplace(
        staging_path,
        recovery_path,
        parent_descriptor,
    )


def _same_file_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return _metadata_identity(left) == _metadata_identity(right)


def _candidate_present(path: Path, candidate: bytes) -> bool | None:
    try:
        raw, _metadata = _stable_regular_bytes(path, role="target after publication")
    except (OffloadObservationError, OSError):
        return None
    return raw == candidate


def _verify_original_index(
    workspace: Path,
    target_before: TargetBeforeObservation,
    before_bytes: bytes,
) -> None:
    mode, object_id = _target_index_entry(workspace, target_before.target_path)
    if mode != target_before.git_mode:
        raise OffloadObservationError("target Git index mode changed during publication")
    _require_git_blob_identity(before_bytes, object_id)


def _persist_metadata_profile(
    *,
    profile: OffloadTargetMetadataProfile,
    authorized: AuthorizedOffloadExecution,
    execution_claim: EffectExecutionClaim,
    artifact_store: ArtifactStore,
) -> str:
    """Retain the exact profile bytes and claim-bound CAS provenance."""

    raw = profile.to_json().encode("ascii")
    if hashlib.sha256(raw).hexdigest() != profile.digest:
        raise OffloadTargetWriteError(
            "metadata profile JSON does not match its canonical digest"
        )
    plan = authorized.plan
    execution = authorized.execution
    locator = artifact_store.put_bytes(
        raw,
        expected_sha256=profile.digest,
        media_type="application/vnd.daedalus.offload-target-metadata-profile+json",
        metadata={
            "claim_receipt_sha256": execution_claim.claim_receipt.receipt_sha256,
            "execution_plan_sha256": plan.digest,
            "execution_request_sha256": execution.digest,
            "kind": _METADATA_PROFILE_ARTIFACT_KIND,
            "metadata_profile_sha256": profile.digest,
            "start_receipt_sha256": execution_claim.start_receipt.receipt_sha256,
        },
        provenance=ContractProvenance(
            origin="daedalus.offload-target.metadata-profile",
            source_revision=profile.source_revision,
            created_at=profile.provenance.created_at,
            input_digests=(
                profile.digest,
                plan.digest,
                execution.digest,
                execution_claim.start_receipt.receipt_sha256,
                execution_claim.claim_receipt.receipt_sha256,
            ),
            trace_id=profile.provenance.trace_id,
        ).to_dict(),
    )
    verified = artifact_store.verify(locator)
    if (
        verified.artifact_sha256 != profile.digest
        or artifact_store.get_bytes(profile.digest) != raw
    ):
        raise OffloadTargetWriteError("metadata profile CAS replay mismatch")
    return verified.locator_uri


def _build_effect_commitment(
    *,
    authorized: AuthorizedOffloadExecution,
    execution_claim: EffectExecutionClaim,
    model_observation: OllamaModelObservation,
    chat_observation: OllamaChatObservation,
    metadata_profile: OffloadTargetMetadataProfile,
    metadata_profile_artifact_locator: str,
    resolved_kill_switch: ResolvedKillSwitch,
    origin: str,
) -> OffloadTargetEffectCommitment:
    plan = authorized.plan
    target_before = authorized.target_before
    digest_inputs = (
        authorized.authorization.lease.digest,
        plan.digest,
        authorized.execution.digest,
        execution_claim.start_receipt.receipt_sha256,
        execution_claim.claim_receipt.receipt_sha256,
        authorized.workspace_attestation.digest,
        target_before.digest,
        model_observation.digest,
        chat_observation.digest,
        plan.artifact_store_root_sha256,
        chat_observation.candidate_sha256,
        plan.staging_path_sha256,
        plan.recovery_path_sha256,
        target_before.content_sha256,
        target_before.file_identity_sha256,
        target_before.parent_chain_sha256,
        metadata_profile.digest,
        resolved_kill_switch.path_sha256,
        _locator_sha256(chat_observation.candidate_artifact_locator),
        _locator_sha256(metadata_profile_artifact_locator),
    )
    return OffloadTargetEffectCommitment(
        lease_sha256=authorized.authorization.lease.digest,
        source_revision=plan.source_revision,
        execution_plan_sha256=plan.digest,
        execution_request_sha256=authorized.execution.digest,
        start_receipt_sha256=execution_claim.start_receipt.receipt_sha256,
        claim_receipt_sha256=execution_claim.claim_receipt.receipt_sha256,
        workspace_attestation_sha256=authorized.workspace_attestation.digest,
        target_before_observation_sha256=target_before.digest,
        ollama_model_observation_sha256=model_observation.digest,
        ollama_chat_observation_sha256=chat_observation.digest,
        artifact_store_root_sha256=plan.artifact_store_root_sha256,
        candidate_artifact_locator=chat_observation.candidate_artifact_locator,
        candidate_sha256=chat_observation.candidate_sha256,
        candidate_size=chat_observation.candidate_size,
        target_path=plan.target_path,
        staging_path=plan.staging_path,
        staging_path_sha256=plan.staging_path_sha256,
        recovery_path=plan.recovery_path,
        recovery_path_sha256=plan.recovery_path_sha256,
        target_before_content_sha256=target_before.content_sha256,
        target_before_size=target_before.byte_length,
        target_before_file_identity_sha256=target_before.file_identity_sha256,
        target_parent_chain_sha256=target_before.parent_chain_sha256,
        target_git_mode=target_before.git_mode,
        target_filesystem_mode=target_before.filesystem_mode,
        metadata_profile_sha256=metadata_profile.digest,
        metadata_profile_artifact_locator=metadata_profile_artifact_locator,
        publication_strategy=_PUBLICATION_STRATEGY,
        durability_profile=_DURABILITY_PROFILE,
        kill_switch_ref=resolved_kill_switch.kill_switch_ref,
        kill_switch_generation=resolved_kill_switch.generation,
        kill_switch_path_sha256=resolved_kill_switch.path_sha256,
        provenance=ContractProvenance(
            origin=origin,
            source_revision=plan.source_revision,
            created_at=chat_observation.provenance.created_at,
            input_digests=digest_inputs,
            trace_id=chat_observation.provenance.trace_id,
        ),
    )


def _persist_effect_commitment(
    *,
    commitment: OffloadTargetEffectCommitment,
    artifact_store: ArtifactStore,
) -> str:
    raw = commitment.to_json().encode("ascii")
    if hashlib.sha256(raw).hexdigest() != commitment.digest:
        raise OffloadTargetWriteError(
            "effect commitment JSON does not match its canonical digest"
        )
    locator = artifact_store.put_bytes(
        raw,
        expected_sha256=commitment.digest,
        media_type="application/vnd.daedalus.offload-target-effect-commitment+json",
        metadata={
            "claim_receipt_sha256": commitment.claim_receipt_sha256,
            "effect_commitment_sha256": commitment.digest,
            "execution_plan_sha256": commitment.execution_plan_sha256,
            "execution_request_sha256": commitment.execution_request_sha256,
            "kind": _EFFECT_COMMITMENT_ARTIFACT_KIND,
        },
        provenance=ContractProvenance(
            origin="daedalus.offload-target.effect-commitment",
            source_revision=commitment.provenance.source_revision,
            created_at=commitment.provenance.created_at,
            input_digests=(
                commitment.digest,
                commitment.claim_receipt_sha256,
                commitment.execution_plan_sha256,
                commitment.execution_request_sha256,
            ),
            trace_id=commitment.provenance.trace_id,
        ).to_dict(),
    )
    verified = artifact_store.verify(locator)
    if (
        verified.artifact_sha256 != commitment.digest
        or artifact_store.get_bytes(commitment.digest) != raw
    ):
        raise OffloadTargetWriteError("effect commitment CAS replay mismatch")
    return verified.locator_uri


def _persist_target_after(
    *,
    after: TargetAfterObservation,
    artifact_store: ArtifactStore,
) -> str:
    raw = after.to_json().encode("ascii")
    if hashlib.sha256(raw).hexdigest() != after.digest:
        raise OffloadTargetWriteError(
            "target-after JSON does not match its canonical digest"
        )
    locator = artifact_store.put_bytes(
        raw,
        expected_sha256=after.digest,
        media_type="application/vnd.daedalus.target-after-observation+json",
        metadata={
            "effect_commitment_sha256": after.effect_commitment_sha256,
            "execution_plan_sha256": after.execution_plan_sha256,
            "kind": _TARGET_AFTER_ARTIFACT_KIND,
            "publication_outcome_receipt_sha256": (
                after.publication_outcome_receipt_sha256
            ),
            "target_after_observation_sha256": after.digest,
        },
        provenance=ContractProvenance(
            origin="daedalus.offload-target.target-after",
            source_revision=after.source_revision,
            created_at=after.published_at,
            input_digests=(
                after.digest,
                after.effect_commitment_sha256,
                after.execution_plan_sha256,
                after.publication_outcome_receipt_sha256,
            ),
            trace_id=after.provenance.trace_id,
        ).to_dict(),
    )
    verified = artifact_store.verify(locator)
    if (
        verified.artifact_sha256 != after.digest
        or artifact_store.get_bytes(after.digest) != raw
    ):
        raise OffloadTargetWriteError("target-after CAS replay mismatch")
    return verified.locator_uri


def _capture_after(
    *,
    authorized: AuthorizedOffloadExecution,
    chat_observation: OllamaChatObservation,
    effect_commitment: OffloadTargetEffectCommitment,
    effect_commitment_artifact_locator: str,
    metadata_profile: OffloadTargetMetadataProfile,
    finalization: EffectPublicationFinalization,
    manager: GitWorktreeManager,
    workspace: Path,
    target_path: Path,
    before_bytes: bytes,
    candidate_bytes: bytes,
    durability_assurance: str,
    origin: str,
) -> TargetAfterObservation:
    plan = authorized.plan
    attestation = authorized.workspace_attestation
    target_before = authorized.target_before
    attestation.verify_current(manager, workspace)
    _verify_original_index(workspace, target_before, before_bytes)
    parent_before = _directory_chain_sha256(
        workspace,
        target_path.parent,
        role="workspace-to-target-parent",
    )
    raw, metadata = _stable_regular_bytes(target_path, role="target after write")
    if raw != candidate_bytes:
        raise OffloadObservationError(
            "target bytes after atomic replacement differ from CAS candidate"
        )
    if stat.S_IMODE(metadata.st_mode) != target_before.filesystem_mode:
        raise OffloadObservationError(
            "target filesystem mode after replacement differs from target-before"
        )
    _verify_metadata_profile(
        target_path,
        metadata,
        metadata_profile,
        role="published target",
    )
    if (
        _empty_xattrs_sha256(target_path.parent, role="target parent")
        != metadata_profile.parent_xattrs_sha256
    ):
        raise OffloadObservationError(
            "target parent metadata changed during publication"
        )
    parent_after = _directory_chain_sha256(
        workspace,
        target_path.parent,
        role="workspace-to-target-parent",
    )
    if (
        parent_before != target_before.parent_chain_sha256
        or parent_after != parent_before
    ):
        raise OffloadObservationError("target parent chain changed during publication")
    _verify_original_index(workspace, target_before, before_bytes)
    attestation.verify_current(manager, workspace)

    content_sha = hashlib.sha256(raw).hexdigest()
    file_identity = _identity_sha256(
        target_path, metadata, role="target file after write"
    )
    inputs = tuple(sorted({
        plan.digest,
        authorized.execution.digest,
        finalization.start_receipt.receipt_sha256,
        finalization.claim_receipt.receipt_sha256,
        effect_commitment.digest,
        finalization.commit_receipt.receipt_sha256,
        finalization.outcome_receipt.receipt_sha256,
        metadata_profile.digest,
        chat_observation.digest,
        attestation.digest,
        target_before.digest,
        plan.staging_path_sha256,
        plan.recovery_path_sha256,
        plan.artifact_store_root_sha256,
        content_sha,
        file_identity,
        parent_after,
        _locator_sha256(chat_observation.candidate_artifact_locator),
        _locator_sha256(effect_commitment_artifact_locator),
    }))
    return TargetAfterObservation(
        execution_plan_sha256=plan.digest,
        execution_request_sha256=authorized.execution.digest,
        start_receipt_sha256=finalization.start_receipt.receipt_sha256,
        claim_receipt_sha256=finalization.claim_receipt.receipt_sha256,
        effect_commitment_sha256=effect_commitment.digest,
        effect_commitment_artifact_locator=effect_commitment_artifact_locator,
        publication_commit_receipt_sha256=(
            finalization.commit_receipt.receipt_sha256
        ),
        publication_outcome_receipt_sha256=(
            finalization.outcome_receipt.receipt_sha256
        ),
        metadata_profile_sha256=metadata_profile.digest,
        publication_strategy=effect_commitment.publication_strategy,
        durability_profile=effect_commitment.durability_profile,
        ollama_chat_observation_sha256=chat_observation.digest,
        candidate_artifact_locator=chat_observation.candidate_artifact_locator,
        workspace_attestation_sha256=attestation.digest,
        target_before_observation_sha256=target_before.digest,
        source_revision=plan.source_revision,
        target_path=plan.target_path,
        staging_path=plan.staging_path,
        staging_path_sha256=plan.staging_path_sha256,
        recovery_path=plan.recovery_path,
        recovery_path_sha256=plan.recovery_path_sha256,
        target_kind=plan.target_kind,
        content_sha256=content_sha,
        byte_length=len(raw),
        git_mode=target_before.git_mode,
        filesystem_mode=stat.S_IMODE(metadata.st_mode),
        encoding="utf-8",
        file_identity_sha256=file_identity,
        parent_chain_sha256=parent_after,
        durability_assurance=durability_assurance,
        published_at=finalization.outcome_receipt.published_at,
        provenance=ContractProvenance(
            origin=origin,
            source_revision=plan.source_revision,
            created_at=finalization.outcome_receipt.published_at,
            input_digests=inputs,
            trace_id=chat_observation.provenance.trace_id,
        ),
    )


def _load_bound_candidate(
    *,
    authorized: AuthorizedOffloadExecution,
    start_result: EffectStartResult,
    execution_claim: EffectExecutionClaim,
    model_observation: OllamaModelObservation,
    chat_observation: OllamaChatObservation,
    artifact_store: ArtifactStore,
) -> bytes:
    plan = authorized.plan
    if artifact_store.root_sha256 != plan.artifact_store_root_sha256:
        raise OffloadTargetWriteError(
            "artifact store root differs from the execution plan binding"
        )
    receipt = start_result.receipt
    if type(execution_claim) is not EffectExecutionClaim:
        raise OffloadTargetWriteError(
            "publication requires an exact durable execution claim"
        )
    if execution_claim.start_receipt != receipt:
        raise OffloadTargetWriteError(
            "publication claim does not bind the observation start receipt"
        )
    if type(authorized.authorization.ledger) is not EffectLeaseLedger:
        raise OffloadTargetWriteError(
            "publication requires the canonical persisted effect ledger"
        )
    try:
        authorized.authorization.require_live_claim(
            execution_claim,
            authorized.execution,
        )
    except EffectLeaseError as exc:
        raise OffloadTargetWriteError(
            "publication claim is not authenticated by the canonical ledger"
        ) from exc
    mismatches = sorted(
        name
        for name, actual, expected in (
            ("start_execution", receipt.execution_id, authorized.execution.execution_id),
            (
                "start_execution_request",
                receipt.execution_request_sha256,
                authorized.execution.digest,
            ),
            ("start_lease", receipt.lease_sha256, authorized.authorization.lease.digest),
            ("chat_plan", chat_observation.execution_plan_sha256, plan.digest),
            (
                "chat_execution_request",
                chat_observation.execution_request_sha256,
                authorized.execution.digest,
            ),
            (
                "chat_start_receipt",
                chat_observation.start_receipt_sha256,
                receipt.receipt_sha256,
            ),
            (
                "model_claim_receipt",
                model_observation.claim_receipt_sha256,
                execution_claim.claim_receipt.receipt_sha256,
            ),
            (
                "chat_claim_receipt",
                chat_observation.claim_receipt_sha256,
                execution_claim.claim_receipt.receipt_sha256,
            ),
            (
                "chat_target_before",
                chat_observation.target_before_observation_sha256,
                authorized.target_before.digest,
            ),
            ("chat_target_path", chat_observation.target_path, plan.target_path),
            (
                "chat_target_before_bytes",
                chat_observation.target_before_sha256,
                authorized.target_before.content_sha256,
            ),
            (
                "chat_source_revision",
                chat_observation.source_revision,
                plan.source_revision,
            ),
            (
                "chat_ollama_request",
                chat_observation.ollama_request_sha256,
                plan.ollama_request_sha256,
            ),
            (
                "chat_model_observation",
                chat_observation.ollama_model_observation_sha256,
                model_observation.digest,
            ),
            (
                "candidate_size_cap",
                chat_observation.candidate_size <= plan.max_response_bytes,
                True,
            ),
        )
        if actual != expected
    )
    if mismatches:
        raise OffloadTargetWriteError(
            "publication authority/chat binding mismatch: " + ", ".join(mismatches)
        )
    if not chat_observation.changes_target:
        raise OffloadTargetWriteError("no-change candidate must not be published")

    try:
        model_locator = _load_locator_uri(
            artifact_store, model_observation.raw_response_artifact_locator
        )
        model_raw = artifact_store.get_bytes(model_observation.raw_response_sha256)
        replayed_model = OllamaModelObservation.capture_from_response_bytes(
            execution_request=authorized.execution,
            execution_claim=execution_claim,
            authorization=authorized.authorization,
            execution_plan=plan,
            metadata_request_sha256=model_observation.metadata_request_sha256,
            raw_response_bytes=model_raw,
            raw_response_locator=model_locator,
            artifact_store=artifact_store,
            origin=model_observation.provenance.origin,
            created_at=model_observation.provenance.created_at,
            trace_id=model_observation.provenance.trace_id,
        )
        if replayed_model != model_observation:
            raise OffloadTargetWriteError(
                "model observation differs from its replayed CAS chain"
            )

        raw_locator = _load_locator_uri(
            artifact_store, chat_observation.raw_response_artifact_locator
        )
        raw_response = artifact_store.get_bytes(chat_observation.raw_response_sha256)
        candidate_locator = _load_locator_uri(
            artifact_store, chat_observation.candidate_artifact_locator
        )
        parsed = parse_offload_chat_response(
            raw_response_bytes=raw_response,
            plan=plan,
            target_before=authorized.target_before,
        )
        replayed_chat = OllamaChatObservation.capture_from_response_bytes(
            execution_request=authorized.execution,
            execution_claim=execution_claim,
            authorization=authorized.authorization,
            execution_plan=plan,
            model_observation=model_observation,
            target_before=authorized.target_before,
            parsed_candidate=parsed,
            raw_response_bytes=raw_response,
            raw_response_locator=raw_locator,
            candidate_locator=candidate_locator,
            artifact_store=artifact_store,
            origin=chat_observation.provenance.origin,
            created_at=chat_observation.provenance.created_at,
            trace_id=chat_observation.provenance.trace_id,
        )
        if replayed_chat != chat_observation:
            raise OffloadTargetWriteError(
                "chat observation differs from its replayed CAS chain"
            )
    except OffloadTargetWriteError:
        raise
    except (ArtifactStoreError, OffloadObservationError, ValueError) as exc:
        raise OffloadTargetWriteError(
            "publication CAS observation chain did not replay exactly"
        ) from exc
    return parsed.content_bytes


def _require_persisted_live_claim(
    authorized: AuthorizedOffloadExecution,
    execution_claim: EffectExecutionClaim,
) -> None:
    try:
        authorized.authorization.require_live_claim(
            execution_claim,
            authorized.execution,
        )
    except EffectLeaseError as exc:
        raise OffloadTargetWriteError(
            "publication claim is no longer EXECUTING in the canonical ledger"
        ) from exc


def _publish_authorized_candidate(
    *,
    authorized: AuthorizedOffloadExecution,
    start_result: EffectStartResult,
    execution_claim: EffectExecutionClaim,
    model_observation: OllamaModelObservation,
    chat_observation: OllamaChatObservation,
    artifact_store: ArtifactStore,
    manager: GitWorktreeManager,
    workspace_path: str | os.PathLike[str],
    resolved_kill_switch: ResolvedKillSwitch,
    deadline_monotonic: float,
    origin: str,
) -> OffloadTargetPublicationResult:
    """Commit exact instructions, then publish once through the target capability."""

    if type(authorized) is not AuthorizedOffloadExecution:
        raise TypeError("authorized must be an exact AuthorizedOffloadExecution")
    if type(start_result) is not EffectStartResult:
        raise TypeError("start_result must be an exact EffectStartResult")
    if type(execution_claim) is not EffectExecutionClaim:
        raise TypeError("execution_claim must be an exact EffectExecutionClaim")
    if type(model_observation) is not OllamaModelObservation:
        raise TypeError("model_observation must be an exact OllamaModelObservation")
    if type(chat_observation) is not OllamaChatObservation:
        raise TypeError("chat_observation must be an exact OllamaChatObservation")
    if not isinstance(artifact_store, ArtifactStore):
        raise TypeError("artifact_store must be an ArtifactStore")
    if not isinstance(manager, GitWorktreeManager):
        raise TypeError("manager must be a GitWorktreeManager")
    if type(resolved_kill_switch) is not ResolvedKillSwitch:
        raise TypeError("resolved_kill_switch must be exact")
    if (
        isinstance(deadline_monotonic, bool)
        or not isinstance(deadline_monotonic, (int, float))
        or not math.isfinite(float(deadline_monotonic))
    ):
        raise ValueError("deadline_monotonic must be finite")
    canonical_origin = _identifier(origin, "origin")

    try:
        rebound = authorize_offload_execution(
            plan=authorized.plan,
            attempt=authorized.attempt,
            workspace_attestation=authorized.workspace_attestation,
            target_before=authorized.target_before,
            workspace_observation=authorized.workspace_observation,
            runtime_tool_binding=authorized.runtime_tool_binding,
            authorization=authorized.authorization,
            execution=authorized.execution,
        )
    except OffloadAuthorityBindingError as exc:
        raise OffloadTargetWriteError(
            "publication authority no longer forms one canonical binding"
        ) from exc
    if rebound != authorized:
        raise OffloadTargetWriteError(
            "publication authority differs from its canonical rebound"
        )

    plan = authorized.plan
    attestation: TaskAttemptWorkspaceAttestation = authorized.workspace_attestation
    target_before: TargetBeforeObservation = authorized.target_before
    if (
        resolved_kill_switch.kill_switch_ref != plan.effect_scope.kill_switch_ref
        or resolved_kill_switch.generation != plan.kill_switch_generation
    ):
        raise OffloadTargetWriteError(
            "resolved kill switch differs from signed execution authority"
        )
    deadline = float(deadline_monotonic)
    now_monotonic = time.monotonic()
    if deadline > now_monotonic + plan.total_timeout_s:
        raise OffloadTargetWriteError(
            "shared deadline exceeds the signed total timeout"
        )

    def runtime_checkpoint() -> None:
        try:
            resolved_kill_switch.checkpoint()
        except LoopHalted as exc:
            raise OffloadTargetWriteError(
                "resolved kill switch refused target publication"
            ) from exc
        _require_remaining(deadline)

    runtime_checkpoint()
    candidate = _load_bound_candidate(
        authorized=authorized,
        start_result=start_result,
        execution_claim=execution_claim,
        model_observation=model_observation,
        chat_observation=chat_observation,
        artifact_store=artifact_store,
    )
    workspace = _lexical_absolute(workspace_path)
    target_path = workspace.joinpath(*plan.target_path.split("/"))
    staging_path = workspace.joinpath(*plan.staging_path.split("/"))
    recovery_path = workspace.joinpath(*plan.recovery_path.split("/"))
    if not staging_path.parent == recovery_path.parent == target_path.parent:
        raise OffloadTargetWriteError(
            "authorized staging/recovery paths are not target-adjacent"
        )

    descriptor = -1
    parent_descriptor = -1
    commitment: OffloadTargetEffectCommitment | None = None
    commitment_locator_uri: str | None = None
    try:
        attestation.verify_current(manager, workspace)
        target_before.verify_current(
            manager=manager,
            workspace_path=workspace,
            workspace_attestation=attestation,
        )
        before_bytes, before_metadata = _stable_regular_bytes(
            target_path, role="target immediately before commitment"
        )
        if (
            hashlib.sha256(before_bytes).hexdigest() != target_before.content_sha256
            or len(before_bytes) != target_before.byte_length
            or _identity_sha256(target_path, before_metadata, role="target file")
            != target_before.file_identity_sha256
            or stat.S_IMODE(before_metadata.st_mode)
            != target_before.filesystem_mode
        ):
            raise OffloadTargetWriteError(
                "target changed after its before observation"
            )
        if candidate == before_bytes:
            raise OffloadTargetWriteError(
                "candidate is byte-identical to target-before"
            )
        if _directory_chain_sha256(
            workspace,
            target_path.parent,
            role="workspace-to-target-parent",
        ) != target_before.parent_chain_sha256:
            raise OffloadTargetWriteError(
                "target parent differs from its before observation"
            )
        _verify_original_index(workspace, target_before, before_bytes)
        _require_atomic_exchange_support()
        metadata_profile = _capture_metadata_profile(
            target_path=target_path,
            parent_path=target_path.parent,
            target_metadata=before_metadata,
            target_before=target_before,
            origin=canonical_origin,
        )
        parent_descriptor = _open_parent_anchor(target_path.parent)
        _verify_parent_anchor(parent_descriptor, target_path.parent)
        if _stage_present(staging_path, parent_descriptor) is not False:
            raise OffloadTargetWriteError(
                "authorized staging path already exists; reconciliation is required"
            )
        if _stage_present(recovery_path, parent_descriptor) is not False:
            raise OffloadTargetWriteError(
                "authorized recovery path already exists; reconciliation is required"
            )
        runtime_checkpoint()
        _require_persisted_live_claim(authorized, execution_claim)

        commitment = _build_effect_commitment(
            authorized=authorized,
            execution_claim=execution_claim,
            model_observation=model_observation,
            chat_observation=chat_observation,
            metadata_profile=metadata_profile,
            resolved_kill_switch=resolved_kill_switch,
            origin=canonical_origin,
        )
        try:
            commitment_locator_uri = _persist_effect_commitment(
                commitment=commitment,
                artifact_store=artifact_store,
            )
        except (ArtifactStoreError, OSError, ValueError) as exc:
            raise OffloadTargetWriteError(
                "effect commitment could not be retained in canonical CAS"
            ) from exc

        runtime_checkpoint()
        _require_persisted_live_claim(authorized, execution_claim)
        attestation.verify_current(manager, workspace)
        target_before.verify_current(
            manager=manager,
            workspace_path=workspace,
            workspace_attestation=attestation,
        )
        _verify_parent_anchor(parent_descriptor, target_path.parent)
        if (
            _stage_present(staging_path, parent_descriptor) is not False
            or _stage_present(recovery_path, parent_descriptor) is not False
        ):
            raise OffloadTargetWriteError(
                "publication evidence path appeared before durable commit"
            )
        current_before, current_metadata = _stable_regular_bytes(
            target_path, role="target at durable commitment"
        )
        if (
            current_before != before_bytes
            or not _same_file_identity(current_metadata, before_metadata)
        ):
            raise OffloadTargetWriteError(
                "target changed while effect commitment was retained"
            )
        _verify_metadata_profile(
            target_path,
            current_metadata,
            metadata_profile,
            role="target at durable commitment",
        )

        commit = authorized.authorization.commit_publication(
            execution_claim,
            authorized.execution,
            effect_commitment_sha256=commitment.digest,
        )
        authorized.authorization.require_live_commit(
            commit,
            authorized.execution,
        )

        with commit.publication_capability.open_target_publication() as publication:
            runtime_checkpoint()
            _verify_parent_anchor(parent_descriptor, target_path.parent)
            if (
                _stage_present(staging_path, parent_descriptor) is not False
                or _stage_present(recovery_path, parent_descriptor) is not False
            ):
                raise OffloadTargetWriteError(
                    "publication evidence path appeared after durable commit"
                )

            flags = (
                os.O_WRONLY
                | os.O_CREAT
                | os.O_EXCL
                | getattr(os, "O_BINARY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            publication.mark_effect_boundary_crossed()
            descriptor = os.open(
                staging_path.name,
                flags,
                0o600,
                dir_fd=parent_descriptor,
            )
            _write_all(descriptor, candidate)
            os.fsync(descriptor)
            _set_staging_mode(
                descriptor,
                metadata_profile.filesystem_mode,
            )
            os.fsync(descriptor)
            staged_descriptor_metadata = os.fstat(descriptor)
            _verify_metadata_profile(
                staging_path,
                staged_descriptor_metadata,
                metadata_profile,
                role="staging target",
            )
            os.close(descriptor)
            descriptor = -1

            staged_bytes, staged_metadata = _stable_regular_bytes(
                staging_path, role="authorized staging file"
            )
            if staged_bytes != candidate:
                raise OffloadTargetWriteError(
                    "staging file differs from CAS candidate"
                )
            _verify_metadata_profile(
                staging_path,
                staged_metadata,
                metadata_profile,
                role="staging target",
            )

            runtime_checkpoint()
            _verify_parent_anchor(parent_descriptor, target_path.parent)
            target_before.verify_current(
                manager=manager,
                workspace_path=workspace,
                workspace_attestation=attestation,
            )
            _verify_parent_anchor(parent_descriptor, target_path.parent)
            _swap_candidate_into_target(
                staging_path=staging_path,
                target_path=target_path,
                recovery_path=recovery_path,
                parent_descriptor=parent_descriptor,
            )

            displaced_bytes, displaced_metadata = _stable_regular_bytes(
                recovery_path, role="target displaced by atomic publication"
            )
            if (
                displaced_bytes != before_bytes
                or not _same_file_identity(displaced_metadata, before_metadata)
            ):
                raise OffloadTargetWriteError(
                    "atomic exchange displaced unexpected target bytes"
                )
            _verify_metadata_profile(
                recovery_path,
                displaced_metadata,
                metadata_profile,
                role="displaced target",
            )
            visible_bytes, visible_metadata = _stable_regular_bytes(
                target_path, role="published candidate"
            )
            if (
                visible_bytes != candidate
                or not _same_file_identity(visible_metadata, staged_metadata)
            ):
                raise OffloadTargetWriteError(
                    "visible target differs from the staged candidate"
                )
            _verify_metadata_profile(
                target_path,
                visible_metadata,
                metadata_profile,
                role="published candidate",
            )
            if _stage_present(staging_path, parent_descriptor) is not False:
                raise OffloadTargetWriteError(
                    "staging alias remained after atomic publication"
                )
            _verify_original_index(workspace, target_before, before_bytes)
            attestation.verify_current(manager, workspace)
            if _directory_chain_sha256(
                workspace,
                target_path.parent,
                role="workspace-to-target-parent",
            ) != target_before.parent_chain_sha256:
                raise OffloadTargetWriteError(
                    "target parent identity changed during publication"
                )
            durability = _fsync_directory(
                target_path.parent,
                parent_descriptor,
            )
            if durability != "directory-fsync":
                raise OffloadTargetWriteError(
                    "publication did not achieve the committed durability profile"
                )

            runtime_checkpoint()
            recovery_cleanup = _remove_stage(
                recovery_path,
                parent_descriptor,
            )
            if recovery_cleanup is not None:
                raise OffloadTargetWriteError(
                    "validated recovery evidence could not be removed"
                )
            _fsync_directory(target_path.parent, parent_descriptor)
            if (
                _stage_present(staging_path, parent_descriptor) is not False
                or _stage_present(recovery_path, parent_descriptor) is not False
            ):
                raise OffloadTargetWriteError(
                    "publication evidence paths remain after cleanup"
                )
            final_bytes, final_metadata = _stable_regular_bytes(
                target_path, role="final published candidate"
            )
            if (
                final_bytes != candidate
                or not _same_file_identity(final_metadata, staged_metadata)
            ):
                raise OffloadTargetWriteError(
                    "final target differs from the published candidate"
                )
            _verify_metadata_profile(
                target_path,
                final_metadata,
                metadata_profile,
                role="final published candidate",
            )
            _verify_original_index(workspace, target_before, before_bytes)
            attestation.verify_current(manager, workspace)
            if _directory_chain_sha256(
                workspace,
                target_path.parent,
                role="workspace-to-target-parent",
            ) != target_before.parent_chain_sha256:
                raise OffloadTargetWriteError(
                    "target parent changed after publication cleanup"
                )
            _require_remaining(deadline)

            published_at = datetime.now(timezone.utc)
            finalization = publication.publication_succeeded(
                commit_receipt=commit.commit_receipt,
                published_at=published_at,
            )
            after = _capture_after(
                authorized=authorized,
                chat_observation=chat_observation,
                effect_commitment=commitment,
                effect_commitment_artifact_locator=commitment_locator_uri,
                metadata_profile=metadata_profile,
                finalization=finalization,
                manager=manager,
                workspace=workspace,
                target_path=target_path,
                before_bytes=before_bytes,
                candidate_bytes=candidate,
                durability_assurance=durability,
                origin=canonical_origin,
            )
            try:
                target_after_locator_uri = _persist_target_after(
                    after=after,
                    artifact_store=artifact_store,
                )
            except (ArtifactStoreError, OSError, ValueError) as exc:
                raise OffloadTargetWriteError(
                    "target-after evidence could not be retained in canonical CAS"
                ) from exc
            result = OffloadTargetPublicationResult(
                effect_commitment=commitment,
                effect_commitment_artifact_locator=commitment_locator_uri,
                metadata_profile=metadata_profile,
                after_observation=after,
                target_after_artifact_locator=target_after_locator_uri,
                finalization=finalization,
            )
        return result
    except Exception as exc:
        try:
            state = authorized.authorization.ledger.execution_state(
                authorized.execution.execution_id
            )
        except Exception:
            state = None
        if state == "COMMITTING":
            raise OffloadTargetWriteIndeterminate(
                "target publication is durably COMMITTING and requires reconciliation",
                after_observation=None,
                candidate_present=_candidate_present(target_path, candidate),
                staging_present=_stage_present(staging_path, parent_descriptor),
                recovery_present=_stage_present(recovery_path, parent_descriptor),
            ) from exc
        raise
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                pass
        if parent_descriptor >= 0:
            try:
                os.close(parent_descriptor)
            except OSError:
                pass


__all__ = [
    "OffloadTargetEffectCommitment",
    "OffloadTargetError",
    "OffloadTargetDeadlineExceeded",
    "OffloadTargetMetadataProfile",
    "OffloadTargetPublicationResult",
    "OffloadTargetWriteError",
    "OffloadTargetWriteIndeterminate",
    "TargetAfterObservation",
]
