# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Canonical contracts and shared invariants for isolated Attempt lifecycle."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, ClassVar, Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.schemas import (
    AttemptContract,
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _record_payload,
    _repo_path,
    _require_provenance_inputs,
    _revision,
    _sha256,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha


_ATTEMPT_WORKSPACE_SCHEMA = "daedalus-attempt-workspace/1"
_ATTEMPT_EVENT_SCHEMA = "daedalus-attempt-lifecycle-event/1"
_ATTEMPT_TERMINAL_SCHEMA = "daedalus-attempt-lifecycle-terminal/1"
_ATTEMPT_INTENT_KIND = "attempt.lifecycle"
_ATTEMPT_EFFECT_PREFIX = "attempt-lifecycle:"
_TERMINAL_OUTCOMES = {"succeeded", "failed", "cancelled", "faulted"}
_MAX_REPORT_BYTES = 16 * 1024 * 1024


class AttemptLifecycleError(RuntimeError):
    """Base class for malformed, stale, replayed, or inconsistent lifecycle state."""


class AttemptBindingMismatch(AttemptLifecycleError):
    """The Attempt, input tree, workspace, or terminal material does not bind."""


class AttemptReplay(AttemptLifecycleError):
    """An identity was reused with different immutable lifecycle material."""


class AttemptStateError(AttemptLifecycleError):
    """Persisted attempt state is missing, corrupt, or transitioned illegally."""


class AttemptWorkspaceError(AttemptLifecycleError):
    """The checkout-external workspace boundary is unsafe or unavailable."""


def _artifact_ref(payload: Mapping[str, Any], label: str) -> ArtifactRef:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return ArtifactRef(**_record_payload(ArtifactRef, payload, label))


def _path_identity(path: Path) -> str:
    normalized = os.path.normcase(str(path.resolve())).replace("\\", "/")
    return canonical_sha({"schema": _ATTEMPT_WORKSPACE_SCHEMA, "path": normalized})


def _workspace_relative_path(attempt: AttemptContract) -> str:
    return f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"


def _effect_key(attempt_id: str) -> str:
    return _ATTEMPT_EFFECT_PREFIX + _identifier(attempt_id, "attempt_id")


def _is_same_or_within(candidate: Path, parent: Path) -> bool:
    return candidate == parent or parent in candidate.parents


def _timestamp_value(value: str, label: str) -> datetime:
    normalized = _utc_timestamp(value, label)
    return datetime.fromisoformat(normalized.replace("Z", "+00:00"))


def _strict_json(payload: str, label: str) -> Mapping[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise AttemptStateError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        parsed = json.loads(payload, object_pairs_hook=pairs)
    except (json.JSONDecodeError, ValueError) as exc:
        raise AttemptStateError(f"{label} is not strict JSON") from exc
    if not isinstance(parsed, Mapping):
        raise AttemptStateError(f"{label} must be a JSON object")
    return parsed


@dataclass(frozen=True)
class AttemptStartRecord(CanonicalContract):
    """Durable intent to materialize and execute one exact Attempt once."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-start"

    start_id: str
    attempt_id: str
    attempt_sha256: str
    source_revision: str
    input_tree: ArtifactRef
    workspace_parent_sha256: str
    workspace_relative_path: str
    started_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("start_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "attempt_sha256",
            _sha256(self.attempt_sha256, "attempt_sha256"),
        )
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        if not isinstance(self.input_tree, ArtifactRef):
            raise ValueError("input_tree must be an ArtifactRef")
        object.__setattr__(
            self,
            "workspace_parent_sha256",
            _sha256(self.workspace_parent_sha256, "workspace_parent_sha256"),
        )
        relative = _repo_path(self.workspace_relative_path, "workspace_relative_path")
        if relative == "." or not relative.startswith("attempts/"):
            raise ValueError("workspace_relative_path must be below attempts/")
        object.__setattr__(self, "workspace_relative_path", relative)
        started_at = _utc_timestamp(self.started_at, "started_at")
        object.__setattr__(self, "started_at", started_at)
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("start provenance must be ContractProvenance")
        if self.provenance.source_revision != revision:
            raise ValueError("start provenance must use the source revision")
        if self.provenance.created_at != started_at:
            raise ValueError("start provenance time must equal trusted start time")
        expected = tuple(
            sorted(
                {
                    self.attempt_sha256,
                    self.input_tree.sha256,
                    self.workspace_parent_sha256,
                }
            )
        )
        _require_provenance_inputs(self.provenance, expected, "attempt start")
        if tuple(self.provenance.input_digests) != expected:
            raise ValueError("attempt start provenance must bind exactly its inputs")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptStartRecord":
        body = cls._contract_payload(payload)
        body["input_tree"] = _artifact_ref(body["input_tree"], "input_tree")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def same_subject(self, other: "AttemptStartRecord") -> bool:
        """Compare replay identity while retaining the first persisted timestamp."""
        return isinstance(other, AttemptStartRecord) and (
            self.start_id,
            self.attempt_id,
            self.attempt_sha256,
            self.source_revision,
            self.input_tree,
            self.workspace_parent_sha256,
            self.workspace_relative_path,
        ) == (
            other.start_id,
            other.attempt_id,
            other.attempt_sha256,
            other.source_revision,
            other.input_tree,
            other.workspace_parent_sha256,
            other.workspace_relative_path,
        )


@dataclass(frozen=True)
class AttemptTerminalReceipt(CanonicalContract):
    """One immutable terminal outcome for one exact persisted start."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-terminal"

    receipt_id: str
    start_sha256: str
    attempt_id: str
    attempt_sha256: str
    source_revision: str
    input_tree_sha256: str
    outcome: str
    report: ArtifactRef
    candidate_tree: ArtifactRef | None
    completed_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("receipt_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("start_sha256", "attempt_sha256", "input_tree_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        if self.outcome not in _TERMINAL_OUTCOMES:
            raise ValueError(
                "attempt outcome must be succeeded, failed, cancelled, or faulted"
            )
        if not isinstance(self.report, ArtifactRef):
            raise ValueError("terminal report must be an ArtifactRef")
        if self.candidate_tree is not None and not isinstance(
            self.candidate_tree, ArtifactRef
        ):
            raise ValueError("candidate_tree must be an ArtifactRef or null")
        if self.outcome == "succeeded" and self.candidate_tree is None:
            raise ValueError("successful attempt must bind a candidate source tree")
        completed_at = _utc_timestamp(self.completed_at, "completed_at")
        object.__setattr__(self, "completed_at", completed_at)
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("terminal provenance must be ContractProvenance")
        if self.provenance.source_revision != revision:
            raise ValueError("terminal provenance must use the source revision")
        if self.provenance.created_at != completed_at:
            raise ValueError("terminal provenance time must equal trusted completion time")
        required = {
            self.start_sha256,
            self.attempt_sha256,
            self.input_tree_sha256,
            self.report.sha256,
        }
        if self.candidate_tree is not None:
            required.add(self.candidate_tree.sha256)
        expected = tuple(sorted(required))
        _require_provenance_inputs(self.provenance, expected, "attempt terminal")
        if tuple(self.provenance.input_digests) != expected:
            raise ValueError("attempt terminal provenance must bind exactly its inputs")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptTerminalReceipt":
        body = cls._contract_payload(payload)
        body["report"] = _artifact_ref(body["report"], "report")
        if body.get("candidate_tree") is not None:
            body["candidate_tree"] = _artifact_ref(
                body["candidate_tree"], "candidate_tree"
            )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)

    def same_subject(self, other: "AttemptTerminalReceipt") -> bool:
        """Compare exact terminal material while retaining first completion time."""
        return isinstance(other, AttemptTerminalReceipt) and (
            self.receipt_id,
            self.start_sha256,
            self.attempt_id,
            self.attempt_sha256,
            self.source_revision,
            self.input_tree_sha256,
            self.outcome,
            self.report,
            self.candidate_tree,
        ) == (
            other.receipt_id,
            other.start_sha256,
            other.attempt_id,
            other.attempt_sha256,
            other.source_revision,
            other.input_tree_sha256,
            other.outcome,
            other.report,
            other.candidate_tree,
        )


@dataclass(frozen=True)
class AttemptCompletion:
    start: AttemptStartRecord
    receipt: AttemptTerminalReceipt

    def __post_init__(self) -> None:
        if not isinstance(self.start, AttemptStartRecord):
            raise ValueError("completion start must be AttemptStartRecord")
        if not isinstance(self.receipt, AttemptTerminalReceipt):
            raise ValueError("completion receipt must be AttemptTerminalReceipt")
        if self.receipt.start_sha256 != self.start.digest:
            raise ValueError("terminal receipt does not bind the start")
        if self.receipt.attempt_id != self.start.attempt_id:
            raise ValueError("terminal receipt attempt_id does not bind the start")
        if self.receipt.attempt_sha256 != self.start.attempt_sha256:
            raise ValueError("terminal receipt attempt digest does not bind the start")
        if self.receipt.input_tree_sha256 != self.start.input_tree.sha256:
            raise ValueError("terminal receipt input tree does not bind the start")
        if _timestamp_value(
            self.receipt.completed_at, "completed_at"
        ) <= _timestamp_value(self.start.started_at, "started_at"):
            raise ValueError("terminal completion time must follow start time")


@dataclass(frozen=True)
class AttemptBeginResult:
    start: AttemptStartRecord
    execute: bool
    completion: AttemptCompletion | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.start, AttemptStartRecord):
            raise ValueError("begin start must be AttemptStartRecord")
        if not isinstance(self.execute, bool):
            raise ValueError("execute must be boolean")
        if self.execute and self.completion is not None:
            raise ValueError("fresh execution cannot already have completion")
        if self.completion is not None and self.completion.start != self.start:
            raise ValueError("completion does not bind begin start")

    @property
    def pending_reconciliation(self) -> bool:
        return not self.execute and self.completion is None


@dataclass(frozen=True)
class PreparedAttempt:
    begin: AttemptBeginResult
    workspace: Path | None

    def __post_init__(self) -> None:
        if not isinstance(self.begin, AttemptBeginResult):
            raise ValueError("prepared begin must be AttemptBeginResult")
        if self.begin.execute and self.workspace is None:
            raise ValueError("fresh prepared attempt must expose its workspace")
        if not self.begin.execute and self.workspace is not None:
            raise ValueError("replay or pending attempt must not expose a workspace")


__all__ = [
    "AttemptBeginResult",
    "AttemptBindingMismatch",
    "AttemptCompletion",
    "AttemptLifecycleError",
    "AttemptReplay",
    "AttemptStartRecord",
    "AttemptStateError",
    "AttemptTerminalReceipt",
    "AttemptWorkspaceError",
    "PreparedAttempt",
]
