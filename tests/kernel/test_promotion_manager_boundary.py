from __future__ import annotations

import contextvars
from pathlib import Path

import pytest

import daedalus.kairos.promotion_manager_boundary as boundary
from daedalus.kairos.promotion_manager_audit import AuditedWorktreeManager


BRANCH = "daedalus/integration/promotion-1"
REVISION = "a" * 40
PRIMARY = "b" * 64


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.repo_path = root
        self.worktree_root = root / ".worktrees"
        self.reap_result: object = []
        self.reap_error: BaseException | None = None

    def create_worktree(self, _base: str, branch: str) -> Path:
        return self.worktree_root / branch.replace("/", "-")

    def cleanup_worktree(self, _worktree: Path) -> None:
        return None

    def reap_branches(self):
        if self.reap_error is not None:
            raise self.reap_error
        return self.reap_result


class CaptureLedger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def begin(self, *args, **kwargs):
        return (args, kwargs)

    def complete(self, start, **kwargs):
        call = {"start": start, **kwargs}
        self.calls.append(call)
        return call


def state(manager: AuditedWorktreeManager, ledger: CaptureLedger):
    active = contextvars.ContextVar("test_active_manager", default=None)
    active.set(manager)
    return boundary._BoundaryState(
        manager_constructor=lambda *_args, **_kwargs: manager,
        ledger_constructor=lambda *_args, **_kwargs: ledger,
        parent_promote_candidates=lambda *_args, **_kwargs: None,
        active_manager=active,
    )


def complete(
    manager: AuditedWorktreeManager,
    ledger: CaptureLedger,
    *,
    outcome: str,
    report: dict[str, object],
    branch: str | None,
    revision: str | None,
):
    wrapped = boundary._AuditedExecutionLedger(ledger, state=state(manager, ledger))
    return wrapped.complete(
        object(),
        receipt_id="execution-receipt-1",
        outcome=outcome,
        report=report,
        primary_checkout_after_sha256=PRIMARY,
        integration_branch=branch,
        integration_revision=revision,
    )


def lifecycle(tmp_path, *, action: str = "retained"):
    delegate = FakeManager(tmp_path)
    delegate.reap_result = [{"branch": BRANCH, "action": action}]
    manager = AuditedWorktreeManager(delegate)
    worktree = manager.create_worktree("c" * 40, BRANCH)
    manager.cleanup_worktree(worktree)
    manager.reap_branches()
    return manager, delegate


def success_report() -> dict[str, object]:
    return {
        "promoted": [{"task_id": "task-1", "promoted": True}],
        "refused": [],
        "not_gated": [],
        "integration_branch": BRANCH,
        "integration_revision": REVISION,
        "authorization": {},
    }


def refused_report() -> dict[str, object]:
    return {
        "promoted": [],
        "refused": [{"task_id": "task-1", "reason": "policy"}],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": {},
    }


def test_success_requires_live_allocated_branch_and_retained_reaper_action(
    tmp_path,
    monkeypatch,
) -> None:
    manager, _delegate = lifecycle(tmp_path, action="retained")
    ledger = CaptureLedger()
    monkeypatch.setattr(
        boundary,
        "resolve_live_target_revision",
        lambda root, branch: REVISION if root == tmp_path.resolve() and branch == BRANCH else None,
    )

    result = complete(
        manager,
        ledger,
        outcome="succeeded",
        report=success_report(),
        branch=BRANCH,
        revision=REVISION,
    )

    assert result["outcome"] == "succeeded"
    assert result["integration_branch"] == BRANCH
    assert result["integration_revision"] == REVISION
    report = result["report"]
    assert report["manager_audit"]["schema"] == "daedalus-promotion-manager-audit/1"
    assert len(report["manager_audit_sha256"]) == 64


def test_refusal_terminalizes_only_when_reaper_proves_branch_absent(
    tmp_path,
    monkeypatch,
) -> None:
    manager, _delegate = lifecycle(tmp_path, action="deleted")
    ledger = CaptureLedger()

    def absent(_root, _branch):
        raise RuntimeError("branch absent")

    monkeypatch.setattr(boundary, "resolve_live_target_revision", absent)
    result = complete(
        manager,
        ledger,
        outcome="refused",
        report=refused_report(),
        branch=None,
        revision=None,
    )
    assert result["outcome"] == "refused"
    assert result["integration_branch"] is None
    assert result["integration_revision"] is None


def test_refusal_with_surviving_pending_branch_becomes_exact_fault(
    tmp_path,
    monkeypatch,
) -> None:
    manager, _delegate = lifecycle(tmp_path, action="pending")
    ledger = CaptureLedger()
    monkeypatch.setattr(
        boundary,
        "resolve_live_target_revision",
        lambda _root, _branch: REVISION,
    )

    with pytest.raises(boundary.PromotionManagerAuditFault) as captured:
        complete(
            manager,
            ledger,
            outcome="refused",
            report=refused_report(),
            branch=None,
            revision=None,
        )
    assert captured.value.integration_branch == BRANCH
    assert captured.value.integration_revision == REVISION
    assert not ledger.calls


def test_swallowed_reaper_failure_becomes_exact_fault(tmp_path, monkeypatch) -> None:
    delegate = FakeManager(tmp_path)
    delegate.reap_error = RuntimeError("reaper exploded")
    manager = AuditedWorktreeManager(delegate)
    worktree = manager.create_worktree("c" * 40, BRANCH)
    manager.cleanup_worktree(worktree)
    with pytest.raises(RuntimeError, match="reaper exploded"):
        manager.reap_branches()
    ledger = CaptureLedger()
    monkeypatch.setattr(
        boundary,
        "resolve_live_target_revision",
        lambda _root, _branch: REVISION,
    )

    with pytest.raises(boundary.PromotionManagerAuditFault) as captured:
        complete(
            manager,
            ledger,
            outcome="succeeded",
            report=success_report(),
            branch=BRANCH,
            revision=REVISION,
        )
    assert captured.value.integration_branch == BRANCH
    assert captured.value.integration_revision == REVISION


def test_unknown_post_mutation_identity_stays_pending(tmp_path, monkeypatch) -> None:
    delegate = FakeManager(tmp_path)
    manager = AuditedWorktreeManager(delegate)
    ledger = CaptureLedger()

    def unresolved(_root, _branch):
        raise RuntimeError("cannot resolve")

    monkeypatch.setattr(boundary, "resolve_live_target_revision", unresolved)
    report = refused_report()
    report["mutation_entered"] = True

    with pytest.raises(boundary.PromotionManagerAuditPending):
        complete(
            manager,
            ledger,
            outcome="faulted",
            report=report,
            branch=None,
            revision=None,
        )
    assert not ledger.calls


def test_fault_receipt_rebinds_to_current_manager_branch_revision(
    tmp_path,
    monkeypatch,
) -> None:
    manager, _delegate = lifecycle(tmp_path, action="retained")
    ledger = CaptureLedger()
    monkeypatch.setattr(
        boundary,
        "resolve_live_target_revision",
        lambda _root, _branch: REVISION,
    )
    report = refused_report()
    report["mutation_entered"] = True
    report["fault"] = {"type": "RuntimeError", "message": "boom"}

    result = complete(
        manager,
        ledger,
        outcome="faulted",
        report=report,
        branch=None,
        revision=None,
    )
    assert result["outcome"] == "faulted"
    assert result["integration_branch"] == BRANCH
    assert result["integration_revision"] == REVISION


def test_pre_mutation_refusal_does_not_require_manager_allocation(tmp_path) -> None:
    manager = AuditedWorktreeManager(FakeManager(tmp_path))
    ledger = CaptureLedger()
    report = refused_report()
    report["mutation_entered"] = False

    result = complete(
        manager,
        ledger,
        outcome="refused",
        report=report,
        branch=None,
        revision=None,
    )
    assert result["outcome"] == "refused"
    assert result["report"]["manager_audit"]["allocations"] == []
