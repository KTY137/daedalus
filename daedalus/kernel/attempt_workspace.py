# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Checkout-external workspace preparation for isolated Attempts."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from daedalus.kernel.source_trees import SourceTreeStore, StoredSourceTree
from daedalus.schemas import AttemptContract
from daedalus.spine.envelope import canonical_json, canonical_sha

from .attempt_contracts import (
    _is_same_or_within,
    _workspace_relative_path,
    AttemptBindingMismatch,
    AttemptWorkspaceError,
    PreparedAttempt,
)
from .attempt_ledger import AttemptLedger


def _assert_disjoint(candidate: Path, protected: Path, label: str) -> None:
    if _is_same_or_within(candidate, protected) or _is_same_or_within(
        protected, candidate
    ):
        raise AttemptWorkspaceError(f"{label} must be disjoint")


def _workspace_root_identity(path: Path) -> str:
    """Bind the resolved path and concrete directory object retained there.

    Directory timestamps are intentionally excluded: creating an Attempt child
    legitimately changes parent metadata and must not invalidate the retained
    root. Device and inode/file identifier remain stable for the same directory
    object across ordinary child creation on the supported platforms.
    """
    try:
        metadata = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise AttemptWorkspaceError(
            "workspace parent identity cannot be inspected"
        ) from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise AttemptWorkspaceError("workspace parent must be a directory")
    normalized = os.path.normcase(str(path.resolve(strict=True))).replace("\\", "/")
    return canonical_sha(
        {
            "schema": "daedalus-attempt-workspace-root/1",
            "path": normalized,
            "st_dev": int(metadata.st_dev),
            "st_ino": int(metadata.st_ino),
        }
    )


def _resolve_workspace_parent(
    raw_parent: Path,
    *,
    primary: Path,
    cas_root: Path,
) -> Path:
    """Admit one pre-provisioned external workspace root without mutating it.

    Creating a caller-selected root after a prospective topology check leaves a
    TOCTOU window: an ancestor can be replaced before ``mkdir`` and the child
    can be created inside a protected tree before a post-create check notices.
    Gate 0 therefore requires the workspace root to be provisioned by the
    deployment boundary. This coordinator only validates and retains identity.
    """
    try:
        if raw_parent.is_symlink():
            raise AttemptWorkspaceError("workspace parent must not be a symlink")
        prospective = raw_parent.resolve(strict=False)
    except AttemptWorkspaceError:
        raise
    except OSError as exc:
        raise AttemptWorkspaceError(
            "workspace parent topology cannot be inspected"
        ) from exc

    _assert_disjoint(
        prospective,
        primary,
        "workspace parent and primary checkout",
    )
    _assert_disjoint(
        prospective,
        cas_root,
        "workspace parent and source-tree store",
    )

    try:
        parent = raw_parent.resolve(strict=True)
    except OSError as exc:
        raise AttemptWorkspaceError(
            "workspace parent must already exist"
        ) from exc
    if raw_parent.is_symlink():
        raise AttemptWorkspaceError("workspace parent must not be a symlink")
    if not parent.is_dir():
        raise AttemptWorkspaceError("workspace parent must be a directory")

    _assert_disjoint(
        parent,
        primary,
        "workspace parent and primary checkout",
    )
    _assert_disjoint(
        parent,
        cas_root,
        "workspace parent and source-tree store",
    )
    return parent


class IsolatedAttemptCoordinator:
    """Materialize exact inputs under one checkout-external workspace parent."""

    def __init__(
        self,
        *,
        primary_checkout: str | os.PathLike[str],
        workspace_parent: str | os.PathLike[str],
        source_store: SourceTreeStore,
        ledger: AttemptLedger,
    ) -> None:
        if not isinstance(source_store, SourceTreeStore):
            raise AttemptWorkspaceError("source_store must be SourceTreeStore")
        if not isinstance(ledger, AttemptLedger):
            raise AttemptWorkspaceError("ledger must be AttemptLedger")
        if ledger.source_store is not source_store:
            raise AttemptWorkspaceError(
                "coordinator and ledger must share the exact SourceTreeStore"
            )
        primary_path = Path(primary_checkout)
        try:
            if primary_path.is_symlink():
                raise AttemptWorkspaceError("primary checkout must not be a symlink")
            primary = primary_path.resolve(strict=True)
        except AttemptWorkspaceError:
            raise
        except OSError as exc:
            raise AttemptWorkspaceError(
                "primary checkout cannot be resolved"
            ) from exc
        if not primary.is_dir():
            raise AttemptWorkspaceError("primary checkout must be a directory")

        try:
            cas_root = source_store.root.resolve(strict=True)
        except OSError as exc:
            raise AttemptWorkspaceError(
                "source-tree store root cannot be resolved"
            ) from exc
        if not cas_root.is_dir():
            raise AttemptWorkspaceError(
                "source-tree store root must be a directory"
            )

        parent = _resolve_workspace_parent(
            Path(workspace_parent),
            primary=primary,
            cas_root=cas_root,
        )

        self.primary_checkout = primary
        self.workspace_parent = parent
        self.workspace_parent_sha256 = _workspace_root_identity(parent)
        self._cas_root = cas_root
        self.source_store = source_store
        self.ledger = ledger

    def _require_stable_workspace_parent(self) -> None:
        """Revalidate retained root identity before each materialization seam."""
        parent = self.workspace_parent
        try:
            if parent.is_symlink():
                raise AttemptWorkspaceError(
                    "workspace parent must not be a symlink"
                )
            current = parent.resolve(strict=True)
        except AttemptWorkspaceError:
            raise
        except OSError as exc:
            raise AttemptWorkspaceError(
                "workspace parent is no longer available"
            ) from exc
        if not current.is_dir():
            raise AttemptWorkspaceError("workspace parent must be a directory")
        _assert_disjoint(
            current,
            self.primary_checkout,
            "workspace parent and primary checkout",
        )
        _assert_disjoint(
            current,
            self._cas_root,
            "workspace parent and source-tree store",
        )
        if (
            current != parent
            or _workspace_root_identity(current) != self.workspace_parent_sha256
        ):
            raise AttemptWorkspaceError(
                "workspace parent identity changed after admission"
            )

    def prepare(
        self,
        attempt: AttemptContract,
        input_tree: StoredSourceTree,
        *,
        start_id: str,
        started_at: str | None = None,
    ) -> PreparedAttempt:
        """Persist and materialize one fresh attempt.

        ``started_at`` remains a compatibility-only predecessor argument. The
        coordinator does not forward it; the trusted lifecycle clock owns time.
        """
        del started_at
        self._require_stable_workspace_parent()
        if not isinstance(attempt, AttemptContract):
            raise AttemptBindingMismatch("attempt must be AttemptContract")
        if not isinstance(input_tree, StoredSourceTree):
            raise AttemptBindingMismatch("input_tree must be StoredSourceTree")
        loaded = self.source_store.load_tree(input_tree.ref)
        if loaded != input_tree.manifest:
            raise AttemptBindingMismatch(
                "input tree manifest differs from the CAS object"
            )
        if loaded.source_revision != attempt.base_revision:
            raise AttemptBindingMismatch(
                "input source tree revision must equal attempt base revision"
            )
        relative = _workspace_relative_path(attempt)
        begin = self.ledger.begin(
            attempt,
            input_tree,
            start_id=start_id,
            workspace_parent_sha256=self.workspace_parent_sha256,
            workspace_relative_path=relative,
        )
        if not begin.execute:
            return PreparedAttempt(begin=begin, workspace=None)
        self._require_stable_workspace_parent()
        workspace = self.workspace_parent.joinpath(*relative.split("/"))
        try:
            materialized = self.source_store.materialize_tree(
                input_tree.ref,
                workspace,
            )
            if materialized != input_tree.manifest:
                raise AttemptBindingMismatch(
                    "materialized input manifest differs from requested input"
                )
        except Exception as exc:
            report_payload = {
                "schema": "daedalus-attempt-materialization-fault/1",
                "attempt_sha256": attempt.digest,
                "input_tree_sha256": input_tree.ref.sha256,
                "error_type": type(exc).__name__,
            }
            report = self.source_store.put_bytes(
                canonical_json(report_payload).encode("ascii")
            )
            self.ledger.complete(
                begin.start,
                receipt_id=f"terminal-{attempt.attempt_id}",
                outcome="faulted",
                report=report,
                candidate_tree=None,
            )
            raise AttemptWorkspaceError(
                "attempt input materialization failed and was terminalized"
            ) from exc
        return PreparedAttempt(begin=begin, workspace=workspace)


__all__ = ["IsolatedAttemptCoordinator"]
