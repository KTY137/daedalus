"""Behavior-preserving audit adapter for live promotion worktree effects.

The adapter records the exact inputs and outcomes of integration worktree
allocation, cleanup, and branch reaping. It delegates every effect to the
retained manager and never suppresses or translates its exceptions. The audit
is in-memory until the surrounding promotion boundary binds its immutable
snapshot into a persisted execution report.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from daedalus.spine.envelope import canonical_json, canonical_sha

_MAX_ERROR_PREFIX = 1024
_MAX_RESULT_BYTES = 1024 * 1024


def _text(value: object) -> str:
    if isinstance(value, os.PathLike):
        return os.fspath(value)
    return str(value)


def _error_record(exc: BaseException) -> "ManagerAuditError":
    raw = str(exc)
    encoded = raw.encode("utf-8", errors="replace")
    error_type = f"{type(exc).__module__}.{type(exc).__qualname__}"
    return ManagerAuditError(
        error_type=error_type,
        message_prefix=raw[:_MAX_ERROR_PREFIX],
        message_sha256=hashlib.sha256(encoded).hexdigest(),
    )


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _result_record(value: Any) -> Any:
    """Retain ordinary JSON results; otherwise retain an explicit opaque digest."""
    try:
        rendered = canonical_json(value)
        if len(rendered.encode("ascii")) > _MAX_RESULT_BYTES:
            raise ValueError("manager result exceeds audit limit")
        parsed = json.loads(rendered)
        if canonical_json(parsed) != rendered:
            raise ValueError("manager result is not canonical")
        return _freeze_json(parsed)
    except (TypeError, ValueError, json.JSONDecodeError):
        raw = repr(value)
        encoded = raw.encode("utf-8", errors="replace")
        return MappingProxyType(
            {
                "opaque": True,
                "type": f"{type(value).__module__}.{type(value).__qualname__}",
                "repr_prefix": raw[:_MAX_ERROR_PREFIX],
                "repr_sha256": hashlib.sha256(encoded).hexdigest(),
            }
        )


@dataclass(frozen=True)
class ManagerAuditError:
    error_type: str
    message_prefix: str
    message_sha256: str

    def to_dict(self) -> dict[str, str]:
        return {
            "error_type": self.error_type,
            "message_prefix": self.message_prefix,
            "message_sha256": self.message_sha256,
        }


@dataclass(frozen=True)
class WorktreeAllocationAudit:
    base_revision: str
    branch: str
    status: str
    worktree_path: str | None = None
    error: ManagerAuditError | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("allocation audit status must be succeeded or failed")
        if self.status == "succeeded":
            if self.worktree_path is None or self.error is not None:
                raise ValueError("successful allocation audit has invalid outcome")
        elif self.worktree_path is not None or self.error is None:
            raise ValueError("failed allocation audit has invalid outcome")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_revision": self.base_revision,
            "branch": self.branch,
            "status": self.status,
            "worktree_path": self.worktree_path,
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True)
class WorktreeCleanupAudit:
    worktree_path: str
    status: str
    error: ManagerAuditError | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("cleanup audit status must be succeeded or failed")
        if (self.status == "succeeded") != (self.error is None):
            raise ValueError("cleanup audit error does not match status")

    def to_dict(self) -> dict[str, Any]:
        return {
            "worktree_path": self.worktree_path,
            "status": self.status,
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True)
class BranchReapAudit:
    status: str
    result: Any = None
    error: ManagerAuditError | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "failed"}:
            raise ValueError("reap audit status must be succeeded or failed")
        if self.status == "succeeded":
            if self.error is not None:
                raise ValueError("successful reap audit cannot contain an error")
        elif self.error is None:
            raise ValueError("failed reap audit requires an error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "result": _thaw_json(self.result),
            "error": None if self.error is None else self.error.to_dict(),
        }


@dataclass(frozen=True)
class PromotionManagerAuditSnapshot:
    allocations: tuple[WorktreeAllocationAudit, ...]
    cleanups: tuple[WorktreeCleanupAudit, ...]
    reaps: tuple[BranchReapAudit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-promotion-manager-audit/1",
            "allocations": [value.to_dict() for value in self.allocations],
            "cleanups": [value.to_dict() for value in self.cleanups],
            "reaps": [value.to_dict() for value in self.reaps],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @property
    def single_allocation(self) -> WorktreeAllocationAudit | None:
        return self.allocations[0] if len(self.allocations) == 1 else None

    def reaper_action_for(self, branch: str) -> str | None:
        if len(self.reaps) != 1 or self.reaps[0].status != "succeeded":
            return None
        result = _thaw_json(self.reaps[0].result)
        if not isinstance(result, list):
            return None
        matches = [
            row
            for row in result
            if isinstance(row, Mapping) and row.get("branch") == branch
        ]
        if len(matches) != 1 or not isinstance(matches[0].get("action"), str):
            return None
        return str(matches[0]["action"])


class AuditedWorktreeManager:
    """Delegate manager effects while retaining an immutable audit snapshot."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self._lock = threading.RLock()
        self._allocations: list[WorktreeAllocationAudit] = []
        self._cleanups: list[WorktreeCleanupAudit] = []
        self._reaps: list[BranchReapAudit] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def create_worktree(self, base_commit: str, branch_name: str) -> Any:
        base = _text(base_commit)
        branch = _text(branch_name)
        try:
            result = self._delegate.create_worktree(base_commit, branch_name)
        except BaseException as exc:
            with self._lock:
                self._allocations.append(
                    WorktreeAllocationAudit(
                        base_revision=base,
                        branch=branch,
                        status="failed",
                        error=_error_record(exc),
                    )
                )
            raise
        with self._lock:
            self._allocations.append(
                WorktreeAllocationAudit(
                    base_revision=base,
                    branch=branch,
                    status="succeeded",
                    worktree_path=_text(result),
                )
            )
        return result

    def cleanup_worktree(self, worktree: str | Path) -> Any:
        target = _text(worktree)
        try:
            result = self._delegate.cleanup_worktree(worktree)
        except BaseException as exc:
            with self._lock:
                self._cleanups.append(
                    WorktreeCleanupAudit(
                        worktree_path=target,
                        status="failed",
                        error=_error_record(exc),
                    )
                )
            raise
        with self._lock:
            self._cleanups.append(
                WorktreeCleanupAudit(
                    worktree_path=target,
                    status="succeeded",
                )
            )
        return result

    def reap_branches(self) -> Any:
        try:
            result = self._delegate.reap_branches()
        except BaseException as exc:
            with self._lock:
                self._reaps.append(
                    BranchReapAudit(
                        status="failed",
                        error=_error_record(exc),
                    )
                )
            raise
        retained = _result_record(result)
        with self._lock:
            self._reaps.append(
                BranchReapAudit(
                    status="succeeded",
                    result=retained,
                )
            )
        return result

    def snapshot(self) -> PromotionManagerAuditSnapshot:
        with self._lock:
            return PromotionManagerAuditSnapshot(
                allocations=tuple(self._allocations),
                cleanups=tuple(self._cleanups),
                reaps=tuple(self._reaps),
            )


__all__ = [
    "AuditedWorktreeManager",
    "BranchReapAudit",
    "ManagerAuditError",
    "PromotionManagerAuditSnapshot",
    "WorktreeAllocationAudit",
    "WorktreeCleanupAudit",
]
