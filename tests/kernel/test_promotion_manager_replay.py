from __future__ import annotations

import contextvars
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.kairos.promotion_manager_boundary as manager_boundary
from daedalus.kairos.promotion_manager_audit import AuditedWorktreeManager
from daedalus.kairos.promotion_manager_replay import (
    PromotionManagerReplayError,
    _ReplayAuditedExecutionLedger,
    validate_persisted_manager_completion,
)
from daedalus.spine.envelope import canonical_sha


BRANCH = "daedalus/integration/promotion-1"
REVISION = "a" * 40
PRIMARY = "b" * 64


@dataclass(frozen=True)
class FakeReceipt:
    outcome: str
    integration_branch: str | None
    integration_revision: str | None


@dataclass(frozen=True)
class FakeCompletion:
    receipt: FakeReceipt
    report: dict[str, object]

    def report_dict(self) -> dict[str, object]:
        return dict(self.report)


@dataclass(frozen=True)
class FakeBeginResult:
    execute: bool
    completion: FakeCompletion | None


class CaptureLedger:
    def __init__(self, begin_result: FakeBeginResult | None = None) -> None:
        self.begin_result = begin_result
        self.calls: list[dict[str, object]] = []

    def begin(self, *_args, **_kwargs):
        assert self.begin_result is not None
        return self.begin_result

    def complete(self, start, **kwargs):
        value = {"start": start, **kwargs}
        self.calls.append(value)
        return value


class FakeManager:
    def __init__(self, root: Path) -> None:
        self.repo_path = root
        self.worktree_root = root / ".worktrees"
        self.reap_result: object = []

    def create_worktree(self, _base: str, branch: str) -> Path:
        return self.worktree_root / branch.replace("/", "-")

    def cleanup_worktree(self, _worktree: Path) -> None:
        return None

    def reap_branches(self):
        return self.reap_result


def audit(action: str = "retained") -> dict[str, object]:
    worktree = "/tmp/integration-promotion-1"
    return {
        "schema": "daedalus-promotion-manager-audit/1",
        "allocations": [
            {
                "base_revision": "c" * 40,
                "branch": BRANCH,
                "status": "succeeded",
                "worktree_path": worktree,
                "error": None,
            }
        ],
        "cleanups": [
            {
                "worktree_path": worktree,
                "status": "succeeded",
                "error": None,
            }
        ],
        "reaps": [
            {
                "status": "succeeded",
                "result": [{"branch": BRANCH, "action": action}],
                "error": None,
            }
        ],
    }


def completion(
    *,
    outcome: str = "succeeded",
    action: str = "retained",
    branch: str | None = BRANCH,
    revision: str | None = REVISION,
) -> FakeCompletion:
    manager_audit = audit(action)
    report = {
        "mutation_entered": True,
        "integration_branch": branch,
        "integration_revision": revision,
        "manager_audit": manager_audit,
        "manager_audit_sha256": canonical_sha(manager_audit),
    }
    if outcome == "faulted":
        report["fault"] = {"type": "RuntimeError", "message": "boom"}
    return FakeCompletion(
        receipt=FakeReceipt(outcome, branch, revision),
        report=report,
    )


def active_state(manager: AuditedWorktreeManager):
    active = contextvars.ContextVar("test_replay_manager", default=None)
    active.set(manager)
    return SimpleNamespace(active_manager=active)


def test_valid_success_reconstructs_exact_manager_evidence() -> None:
    validate_persisted_manager_completion(completion())


def test_valid_refusal_requires_explicit_deleted_action() -> None:
    validate_persisted_manager_completion(
        completion(
            outcome="refused",
            action="deleted",
            branch=None,
            revision=None,
        )
    )
    with pytest.raises(PromotionManagerReplayError, match="deletion proof"):
        validate_persisted_manager_completion(
            completion(
                outcome="refused",
                action="pending",
                branch=None,
                revision=None,
            )
        )


def test_digest_mismatch_refuses_persisted_completion() -> None:
    value = completion()
    value.report["manager_audit_sha256"] = "0" * 64
    with pytest.raises(PromotionManagerReplayError, match="digest mismatch"):
        validate_persisted_manager_completion(value)


def test_coherently_rehashed_semantic_tamper_still_refuses() -> None:
    value = completion()
    manager_audit = value.report["manager_audit"]
    manager_audit["reaps"][0]["result"][0]["action"] = "deleted"
    value.report["manager_audit_sha256"] = canonical_sha(manager_audit)
    with pytest.raises(PromotionManagerReplayError, match="not retained"):
        validate_persisted_manager_completion(value)


def test_success_branch_substitution_refuses_even_with_valid_digest() -> None:
    value = completion()
    value.report["integration_branch"] = "daedalus/integration/other"
    with pytest.raises(PromotionManagerReplayError, match="branch differ"):
        validate_persisted_manager_completion(value)


def test_pre_mutation_refusal_without_audit_remains_compatible() -> None:
    value = FakeCompletion(
        receipt=FakeReceipt("refused", None, None),
        report={
            "mutation_entered": False,
            "integration_branch": None,
            "integration_revision": None,
        },
    )
    validate_persisted_manager_completion(value)


def test_invalid_replay_is_returned_as_pending_reconciliation() -> None:
    invalid = completion()
    invalid.report["manager_audit_sha256"] = "0" * 64
    delegate = CaptureLedger(FakeBeginResult(execute=False, completion=invalid))
    wrapped = _ReplayAuditedExecutionLedger(
        delegate,
        state=SimpleNamespace(active_manager=contextvars.ContextVar("unused", default=None)),
    )

    result = wrapped.begin(object())
    assert result.execute is False
    assert result.completion is None


def test_valid_replay_remains_terminal() -> None:
    terminal = completion()
    delegate = CaptureLedger(FakeBeginResult(execute=False, completion=terminal))
    wrapped = _ReplayAuditedExecutionLedger(
        delegate,
        state=SimpleNamespace(active_manager=contextvars.ContextVar("unused", default=None)),
    )
    assert wrapped.begin(object()).completion is terminal


def test_refused_surviving_branch_terminalizes_as_exact_fault(
    tmp_path,
    monkeypatch,
) -> None:
    delegate_manager = FakeManager(tmp_path)
    delegate_manager.reap_result = [{"branch": BRANCH, "action": "pending"}]
    manager = AuditedWorktreeManager(delegate_manager)
    worktree = manager.create_worktree("c" * 40, BRANCH)
    manager.cleanup_worktree(worktree)
    manager.reap_branches()
    monkeypatch.setattr(
        manager_boundary,
        "resolve_live_target_revision",
        lambda _root, _branch: REVISION,
    )

    ledger = CaptureLedger()
    wrapped = _ReplayAuditedExecutionLedger(ledger, state=active_state(manager))
    report = {
        "mutation_entered": True,
        "promoted": [],
        "refused": [{"task_id": "task-1", "reason": "policy"}],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": {},
    }
    result = wrapped.complete(
        object(),
        receipt_id="execution-receipt-1",
        outcome="refused",
        report=report,
        primary_checkout_after_sha256=PRIMARY,
        integration_branch=None,
        integration_revision=None,
    )

    assert result["outcome"] == "faulted"
    assert result["integration_branch"] == BRANCH
    assert result["integration_revision"] == REVISION
    assert result["report"]["integration_branch"] == BRANCH
    assert result["report"]["integration_revision"] == REVISION
    assert result["report"]["fault"]["type"].endswith(
        "PromotionManagerAuditFault"
    )


def test_unresolvable_exact_fault_remains_pending(tmp_path, monkeypatch) -> None:
    delegate_manager = FakeManager(tmp_path)
    delegate_manager.reap_result = [{"branch": BRANCH, "action": "pending"}]
    manager = AuditedWorktreeManager(delegate_manager)
    worktree = manager.create_worktree("c" * 40, BRANCH)
    manager.cleanup_worktree(worktree)
    manager.reap_branches()

    def unresolved(_root, _branch):
        raise RuntimeError("cannot resolve")

    monkeypatch.setattr(manager_boundary, "resolve_live_target_revision", unresolved)
    ledger = CaptureLedger()
    wrapped = _ReplayAuditedExecutionLedger(ledger, state=active_state(manager))
    report = {
        "mutation_entered": True,
        "promoted": [],
        "refused": [{"task_id": "task-1", "reason": "policy"}],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": {},
    }

    with pytest.raises(manager_boundary.PromotionManagerAuditPending):
        wrapped.complete(
            object(),
            receipt_id="execution-receipt-1",
            outcome="refused",
            report=report,
            primary_checkout_after_sha256=PRIMARY,
        )
    assert not ledger.calls
