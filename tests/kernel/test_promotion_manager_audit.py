from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.kairos.promotion_manager_audit import AuditedWorktreeManager


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.repo_path = root
        self.worktree_root = root / ".worktrees"
        self.create_error: BaseException | None = None
        self.cleanup_error: BaseException | None = None
        self.reap_error: BaseException | None = None
        self.reap_result: object = []

    def create_worktree(self, base: str, branch: str) -> Path:
        if self.create_error is not None:
            raise self.create_error
        return self.worktree_root / branch.replace("/", "-")

    def cleanup_worktree(self, worktree: Path) -> None:
        if self.cleanup_error is not None:
            raise self.cleanup_error

    def reap_branches(self):
        if self.reap_error is not None:
            raise self.reap_error
        return self.reap_result


def test_successful_manager_lifecycle_is_exact_and_immutable(tmp_path) -> None:
    delegate = FakeManager(tmp_path)
    delegate.reap_result = [
        {"branch": "daedalus/integration/promotion-1", "action": "retained"}
    ]
    manager = AuditedWorktreeManager(delegate)

    worktree = manager.create_worktree(
        "a" * 40,
        "daedalus/integration/promotion-1",
    )
    manager.cleanup_worktree(worktree)
    returned = manager.reap_branches()
    snapshot = manager.snapshot()

    assert snapshot.single_allocation is not None
    assert snapshot.single_allocation.base_revision == "a" * 40
    assert snapshot.single_allocation.branch == "daedalus/integration/promotion-1"
    assert snapshot.single_allocation.worktree_path == str(worktree)
    assert snapshot.cleanups[0].worktree_path == str(worktree)
    assert snapshot.reaper_action_for("daedalus/integration/promotion-1") == "retained"
    assert len(snapshot.digest) == 64
    assert snapshot.to_dict()["schema"] == "daedalus-promotion-manager-audit/1"

    returned[0]["action"] = "deleted"
    assert snapshot.reaper_action_for("daedalus/integration/promotion-1") == "retained"
    assert manager.repository_path == tmp_path.resolve()
    assert manager.worktree_root == delegate.worktree_root


def test_allocation_failure_is_recorded_and_rethrown(tmp_path) -> None:
    delegate = FakeManager(tmp_path)
    delegate.create_error = RuntimeError("allocation exploded")
    manager = AuditedWorktreeManager(delegate)

    with pytest.raises(RuntimeError, match="allocation exploded"):
        manager.create_worktree("a" * 40, "daedalus/integration/promotion-1")

    allocation = manager.snapshot().single_allocation
    assert allocation is not None
    assert allocation.status == "failed"
    assert allocation.worktree_path is None
    assert allocation.error is not None
    assert allocation.error.error_type.endswith("RuntimeError")
    assert allocation.error.message_prefix == "allocation exploded"
    assert len(allocation.error.message_sha256) == 64


def test_cleanup_and_reaper_failures_are_recorded_without_translation(tmp_path) -> None:
    delegate = FakeManager(tmp_path)
    delegate.cleanup_error = OSError("cleanup refused")
    delegate.reap_error = RuntimeError("reaper refused")
    manager = AuditedWorktreeManager(delegate)
    worktree = manager.create_worktree(
        "a" * 40,
        "daedalus/integration/promotion-1",
    )

    with pytest.raises(OSError, match="cleanup refused"):
        manager.cleanup_worktree(worktree)
    with pytest.raises(RuntimeError, match="reaper refused"):
        manager.reap_branches()

    snapshot = manager.snapshot()
    assert snapshot.cleanups[0].status == "failed"
    assert snapshot.cleanups[0].error is not None
    assert snapshot.reaps[0].status == "failed"
    assert snapshot.reaps[0].error is not None
    assert snapshot.reaper_action_for("daedalus/integration/promotion-1") is None


def test_non_json_reaper_result_is_explicitly_opaque(tmp_path) -> None:
    delegate = FakeManager(tmp_path)
    delegate.reap_result = object()
    manager = AuditedWorktreeManager(delegate)
    manager.reap_branches()

    result = manager.snapshot().to_dict()["reaps"][0]["result"]
    assert result["opaque"] is True
    assert result["type"] == "builtins.object"
    assert len(result["repr_sha256"]) == 64
