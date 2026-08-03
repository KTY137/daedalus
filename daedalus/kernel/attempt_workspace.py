"""Checkout-external workspace preparation for isolated Attempts."""
from __future__ import annotations

import os
from pathlib import Path

from daedalus.kernel.source_trees import SourceTreeStore, StoredSourceTree
from daedalus.schemas import AttemptContract
from daedalus.spine.envelope import canonical_json

from .attempt_contracts import (
    _is_same_or_within,
    _path_identity,
    _workspace_relative_path,
    AttemptBindingMismatch,
    AttemptWorkspaceError,
    PreparedAttempt,
)
from .attempt_ledger import AttemptLedger


def _require_disjoint_workspace_parent(
    parent: Path,
    *,
    primary_checkout: Path,
    cas_root: Path,
) -> None:
    """Refuse a workspace root that overlaps either protected authority root."""

    for left, right, label in (
        (parent, primary_checkout, "workspace parent and primary checkout"),
        (parent, cas_root, "workspace parent and source-tree store"),
    ):
        if _is_same_or_within(left, right) or _is_same_or_within(right, left):
            raise AttemptWorkspaceError(f"{label} must be disjoint")


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
        primary = Path(primary_checkout)
        if primary.is_symlink():
            raise AttemptWorkspaceError("primary checkout must not be a symlink")
        primary = primary.resolve(strict=True)
        if not primary.is_dir():
            raise AttemptWorkspaceError("primary checkout must be a directory")

        raw_parent = Path(workspace_parent)
        if raw_parent.is_symlink():
            raise AttemptWorkspaceError("workspace parent must not be a symlink")

        # Admission is deliberately non-mutating. Workspace roots are an
        # operator/runtime responsibility and must already exist. Creating a
        # caller-chosen path here would allow a refused path below the primary
        # checkout or CAS to mutate the protected tree before refusal, and a
        # parent-component replacement between preflight and mkdir would reopen
        # the same bug.
        prospective_parent = raw_parent.resolve(strict=False)
        cas_root = source_store.root.resolve(strict=True)
        _require_disjoint_workspace_parent(
            prospective_parent,
            primary_checkout=primary,
            cas_root=cas_root,
        )
        try:
            parent = raw_parent.resolve(strict=True)
        except OSError as exc:
            raise AttemptWorkspaceError(
                "workspace parent must already exist"
            ) from exc
        if not parent.is_dir():
            raise AttemptWorkspaceError("workspace parent must be a directory")
        _require_disjoint_workspace_parent(
            parent,
            primary_checkout=primary,
            cas_root=cas_root,
        )

        self.primary_checkout = primary
        self.workspace_parent = parent
        self.workspace_parent_sha256 = _path_identity(parent)
        self._cas_root = cas_root
        self.source_store = source_store
        self.ledger = ledger

    def _require_stable_workspace_parent(self) -> None:
        """Revalidate the retained path before every materialization boundary."""

        parent = self.workspace_parent
        if parent.is_symlink():
            raise AttemptWorkspaceError("workspace parent must not be a symlink")
        try:
            current = parent.resolve(strict=True)
        except OSError as exc:
            raise AttemptWorkspaceError(
                "workspace parent is no longer available"
            ) from exc
        if not current.is_dir():
            raise AttemptWorkspaceError("workspace parent must be a directory")
        _require_disjoint_workspace_parent(
            current,
            primary_checkout=self.primary_checkout,
            cas_root=self._cas_root,
        )
        if current != parent or _path_identity(current) != self.workspace_parent_sha256:
            raise AttemptWorkspaceError(
                "workspace parent identity changed after coordinator admission"
            )

    def prepare(
        self,
        attempt: AttemptContract,
        input_tree: StoredSourceTree,
        *,
        start_id: str,
        started_at: str,
    ) -> PreparedAttempt:
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
            started_at=started_at,
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
                completed_at=started_at,
            )
            raise AttemptWorkspaceError(
                "attempt input materialization failed and was terminalized"
            ) from exc
        return PreparedAttempt(begin=begin, workspace=workspace)


__all__ = ["IsolatedAttemptCoordinator"]
