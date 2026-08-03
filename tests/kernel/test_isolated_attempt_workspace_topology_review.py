from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import daedalus.kernel.attempt_workspace as workspace_impl
from daedalus.kernel import SourceTreeStore
from daedalus.kernel.attempts import (
    AttemptLedger,
    AttemptWorkspaceError,
    IsolatedAttemptCoordinator,
)


def _roots(tmp_path: Path):
    primary = tmp_path / "primary"
    primary.mkdir()
    (primary / "tracked.py").write_text("value = 1\n", encoding="utf-8")
    store = SourceTreeStore(tmp_path / "cas")
    ledger = AttemptLedger(tmp_path / "state" / "spine.sqlite3", store)
    return primary, store, ledger


def _tree_paths(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(
            str(path.relative_to(root)).replace("\\", "/")
            for path in root.rglob("*")
        )
    )


def test_absent_workspace_inside_primary_is_refused_without_creating_it(
    tmp_path: Path,
) -> None:
    primary, store, ledger = _roots(tmp_path)
    before = _tree_paths(primary)
    requested = primary / "new-workspaces" / "nested"

    with pytest.raises(AttemptWorkspaceError, match="primary checkout"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )

    assert not requested.exists()
    assert not (primary / "new-workspaces").exists()
    assert _tree_paths(primary) == before


def test_absent_workspace_inside_cas_is_refused_without_creating_it(
    tmp_path: Path,
) -> None:
    primary, store, ledger = _roots(tmp_path)
    before = _tree_paths(store.root)
    requested = store.root / "new-workspaces" / "nested"

    with pytest.raises(AttemptWorkspaceError, match="source-tree store"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )

    assert not requested.exists()
    assert not (store.root / "new-workspaces").exists()
    assert _tree_paths(store.root) == before


def test_absent_external_workspace_is_refused_without_creation(tmp_path: Path) -> None:
    primary, store, ledger = _roots(tmp_path)
    requested = tmp_path / "external-workspaces"
    with pytest.raises(AttemptWorkspaceError, match="already exist"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )
    assert not requested.exists()


def test_symlinked_parent_component_cannot_redirect_admission_into_primary(
    tmp_path: Path,
) -> None:
    primary, store, ledger = _roots(tmp_path)
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(primary, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlink creation is unavailable")
    requested = redirect / "escaped-workspaces"
    before = _tree_paths(primary)

    with pytest.raises(AttemptWorkspaceError, match="primary checkout"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )

    assert not (primary / "escaped-workspaces").exists()
    assert _tree_paths(primary) == before


def test_existing_file_is_a_normalized_workspace_refusal(tmp_path: Path) -> None:
    primary, store, ledger = _roots(tmp_path)
    requested = tmp_path / "not-a-directory"
    requested.write_text("not a workspace\n", encoding="utf-8")

    with pytest.raises(AttemptWorkspaceError, match="directory"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )

    assert requested.read_text(encoding="utf-8") == "not a workspace\n"


def test_parent_replacement_after_admission_is_refused_before_materialization(
    tmp_path: Path,
) -> None:
    primary, store, ledger = _roots(tmp_path)
    workspace = tmp_path / "external-workspaces"
    workspace.mkdir()
    coordinator = IsolatedAttemptCoordinator(
        primary_checkout=primary,
        workspace_parent=workspace,
        source_store=store,
        ledger=ledger,
    )
    backup = tmp_path / "external-workspaces-original"
    workspace.rename(backup)
    try:
        workspace.symlink_to(primary, target_is_directory=True)
    except (OSError, NotImplementedError):
        backup.rename(workspace)
        pytest.skip("directory symlink creation is unavailable")

    with pytest.raises(AttemptWorkspaceError, match="primary checkout|identity changed"):
        coordinator._require_stable_workspace_parent()
    assert _tree_paths(primary) == ("tracked.py",)


def test_source_never_creates_workspace_parent_and_revalidates_before_write() -> None:
    init_source = inspect.getsource(workspace_impl.IsolatedAttemptCoordinator.__init__)
    prepare_source = inspect.getsource(workspace_impl.IsolatedAttemptCoordinator.prepare)
    assert ".mkdir(" not in init_source
    assert "raw_parent.resolve(strict=False)" in init_source
    assert init_source.count("_require_disjoint_workspace_parent(") == 2
    assert prepare_source.count("self._require_stable_workspace_parent()") == 2
    assert prepare_source.index("self._require_stable_workspace_parent()") < prepare_source.index(
        "self.ledger.begin"
    )
    assert prepare_source.rindex("self._require_stable_workspace_parent()") < prepare_source.index(
        "self.source_store.materialize_tree"
    )
