from __future__ import annotations

import ast
import inspect
import textwrap
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


def test_symlinked_parent_component_cannot_redirect_creation_into_primary(
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

    with pytest.raises(AttemptWorkspaceError, match="directory|created"):
        IsolatedAttemptCoordinator(
            primary_checkout=primary,
            workspace_parent=requested,
            source_store=store,
            ledger=ledger,
        )

    assert requested.read_text(encoding="utf-8") == "not a workspace\n"


def test_source_orders_nonmutating_preflight_before_mkdir_and_rechecks_after() -> None:
    source = textwrap.dedent(
        inspect.getsource(workspace_impl.IsolatedAttemptCoordinator.__init__)
    )
    tree = ast.parse(source)
    calls = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    prospective = next(
        value for value in calls if "raw_parent.resolve(strict=False)" in value
    )
    mkdir = next(value for value in calls if "raw_parent.mkdir" in value)
    assert source.index(prospective) < source.index(mkdir)
    assert source.count("_require_disjoint_workspace_parent(") == 2
    assert source.index("_require_disjoint_workspace_parent(") < source.index(mkdir)
    assert source.rindex("_require_disjoint_workspace_parent(") > source.index(mkdir)
