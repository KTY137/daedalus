from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
)


def test_same_path_directory_replacement_changes_retained_root_identity(
    tmp_path: Path,
) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    workspace = tmp_path / "workspaces"
    workspace.mkdir()
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=workspace,
        source_store=store,
        ledger=ledger,
    )
    retained = coordinator.workspace_parent_sha256

    backup = tmp_path / "workspaces-original"
    workspace.rename(backup)
    workspace.mkdir()

    with pytest.raises(AttemptWorkspaceError, match="identity changed"):
        coordinator._require_stable_workspace_parent()
    assert coordinator.workspace_parent_sha256 == retained
    assert workspace.resolve() == coordinator.workspace_parent
