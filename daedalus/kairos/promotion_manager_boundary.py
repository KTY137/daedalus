"""Install audited manager and execution-ledger adapters around promotion.

This module is intentionally a strangler adapter over the exact retained live
promotion implementation. It does not perform Git effects itself. It records
manager outcomes, requires an exact surviving branch identity after mutation,
and binds the immutable audit snapshot into the existing promotion execution
report before the canonical ledger terminalizes the attempt.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

from daedalus.kernel.promotion import resolve_live_target_revision
from daedalus.kairos.promotion_manager_audit import (
    AuditedWorktreeManager,
    PromotionManagerAuditSnapshot,
)


class PromotionManagerAuditPending(RuntimeError):
    """A mutation entered but the surviving manager identity is not proven."""


class PromotionManagerAuditFault(RuntimeError):
    """A fully identified manager fault that can be terminally accounted."""

    def __init__(
        self,
        message: str,
        *,
        integration_branch: str | None,
        integration_revision: str | None,
    ) -> None:
        super().__init__(message)
        self.integration_branch = integration_branch
        self.integration_revision = integration_revision


@dataclass
class _BoundaryState:
    manager_constructor: Callable[..., Any]
    ledger_constructor: Callable[..., Any]
    parent_promote_candidates: Callable[..., Any]
    active_manager: contextvars.ContextVar[AuditedWorktreeManager | None]

    def manager_factory(self, *args: Any, **kwargs: Any) -> AuditedWorktreeManager:
        manager = AuditedWorktreeManager(
            self.manager_constructor(*args, **kwargs)
        )
        self.active_manager.set(manager)
        return manager

    def ledger_factory(self, *args: Any, **kwargs: Any) -> "_AuditedExecutionLedger":
        return _AuditedExecutionLedger(
            self.ledger_constructor(*args, **kwargs),
            state=self,
        )

    def promote_candidates(self, *args: Any, **kwargs: Any) -> Any:
        token = self.active_manager.set(None)
        try:
            return self.parent_promote_candidates(*args, **kwargs)
        finally:
            self.active_manager.reset(token)


def _audit_failure_message(snapshot: PromotionManagerAuditSnapshot) -> str:
    parts: list[str] = []
    if len(snapshot.allocations) != 1:
        parts.append(f"allocations={len(snapshot.allocations)}")
    elif snapshot.allocations[0].status != "succeeded":
        parts.append("allocation=failed")
    if len(snapshot.cleanups) != 1:
        parts.append(f"cleanups={len(snapshot.cleanups)}")
    elif snapshot.cleanups[0].status != "succeeded":
        parts.append("cleanup=failed")
    if len(snapshot.reaps) != 1:
        parts.append(f"reaps={len(snapshot.reaps)}")
    elif snapshot.reaps[0].status != "succeeded":
        parts.append("reap=failed")
    return ", ".join(parts) or "manager outcome contradicts promotion report"


def _resolve_branch(
    manager: AuditedWorktreeManager,
    branch: str,
) -> str | None:
    try:
        return resolve_live_target_revision(manager.repository_path, branch)
    except Exception:
        return None


def _proves_absent(
    snapshot: PromotionManagerAuditSnapshot,
    branch: str,
) -> bool:
    allocation = snapshot.single_allocation
    if allocation is None or allocation.status != "succeeded":
        return False
    if len(snapshot.cleanups) != 1 or snapshot.cleanups[0].status != "succeeded":
        return False
    if allocation.worktree_path != snapshot.cleanups[0].worktree_path:
        return False
    return snapshot.reaper_action_for(branch) in {"deleted", "absent"}


def _exact_fault_identity(
    manager: AuditedWorktreeManager,
    snapshot: PromotionManagerAuditSnapshot,
) -> tuple[str | None, str | None]:
    allocation = snapshot.single_allocation
    if allocation is None:
        raise PromotionManagerAuditPending(
            "promotion mutation entered without one auditable allocation"
        )
    branch = allocation.branch
    revision = _resolve_branch(manager, branch)
    if revision is not None:
        return branch, revision
    if _proves_absent(snapshot, branch):
        return None, None
    raise PromotionManagerAuditPending(
        "promotion manager cannot prove the surviving integration identity"
    )


def _validate_common_manager_lifecycle(
    snapshot: PromotionManagerAuditSnapshot,
) -> tuple[str, str]:
    allocation = snapshot.single_allocation
    if allocation is None or allocation.status != "succeeded":
        raise PromotionManagerAuditPending(
            "promotion has no single successful worktree allocation"
        )
    if allocation.worktree_path is None:
        raise PromotionManagerAuditPending(
            "successful manager allocation retained no worktree path"
        )
    if len(snapshot.cleanups) != 1:
        raise PromotionManagerAuditFault(
            _audit_failure_message(snapshot),
            integration_branch=allocation.branch,
            integration_revision=None,
        )
    cleanup = snapshot.cleanups[0]
    if cleanup.worktree_path != allocation.worktree_path:
        raise PromotionManagerAuditFault(
            "promotion cleanup targeted a different worktree",
            integration_branch=allocation.branch,
            integration_revision=None,
        )
    if len(snapshot.reaps) != 1:
        raise PromotionManagerAuditFault(
            _audit_failure_message(snapshot),
            integration_branch=allocation.branch,
            integration_revision=None,
        )
    return allocation.branch, allocation.worktree_path


def _raise_exact_fault(
    manager: AuditedWorktreeManager,
    snapshot: PromotionManagerAuditSnapshot,
    message: str,
) -> None:
    branch, revision = _exact_fault_identity(manager, snapshot)
    raise PromotionManagerAuditFault(
        message,
        integration_branch=branch,
        integration_revision=revision,
    )


def _assess_completion(
    *,
    manager: AuditedWorktreeManager,
    snapshot: PromotionManagerAuditSnapshot,
    outcome: str,
    report: MutableMapping[str, Any],
    integration_branch: str | None,
    integration_revision: str | None,
) -> tuple[str, str | None, str | None]:
    mutation_entered = report.get("mutation_entered") is True
    if not snapshot.allocations and outcome == "refused" and not mutation_entered:
        return outcome, integration_branch, integration_revision

    allocation = snapshot.single_allocation
    if allocation is None:
        raise PromotionManagerAuditPending(
            "post-mutation completion has no single allocation audit"
        )
    if allocation.status != "succeeded":
        branch, revision = _exact_fault_identity(manager, snapshot)
        if outcome != "faulted":
            raise PromotionManagerAuditFault(
                "promotion worktree allocation failed after mutation entry",
                integration_branch=branch,
                integration_revision=revision,
            )
        return "faulted", branch, revision

    branch, _worktree = _validate_common_manager_lifecycle(snapshot)
    cleanup = snapshot.cleanups[0]
    reap = snapshot.reaps[0]
    if cleanup.status != "succeeded" or reap.status != "succeeded":
        if outcome != "faulted":
            _raise_exact_fault(
                manager,
                snapshot,
                _audit_failure_message(snapshot),
            )
        exact_branch, exact_revision = _exact_fault_identity(manager, snapshot)
        return "faulted", exact_branch, exact_revision

    reported_branch = report.get("integration_branch")
    if reported_branch is not None and reported_branch != branch:
        _raise_exact_fault(
            manager,
            snapshot,
            "promotion report branch differs from manager allocation",
        )

    action = snapshot.reaper_action_for(branch)
    if outcome == "succeeded":
        current_revision = _resolve_branch(manager, branch)
        if current_revision is None:
            raise PromotionManagerAuditPending(
                "successful promotion branch cannot be resolved after mutation"
            )
        if integration_branch != branch or reported_branch != branch:
            raise PromotionManagerAuditFault(
                "successful promotion did not retain the allocated branch",
                integration_branch=branch,
                integration_revision=current_revision,
            )
        if (
            integration_revision != current_revision
            or report.get("integration_revision") != current_revision
        ):
            raise PromotionManagerAuditFault(
                "successful promotion revision differs from live allocated branch",
                integration_branch=branch,
                integration_revision=current_revision,
            )
        if action != "retained":
            raise PromotionManagerAuditFault(
                f"successful promotion branch has reaper action {action!r}",
                integration_branch=branch,
                integration_revision=current_revision,
            )
        return "succeeded", branch, current_revision

    if outcome == "refused":
        if integration_branch is not None or integration_revision is not None:
            _raise_exact_fault(
                manager,
                snapshot,
                "refused promotion retained integration identity",
            )
        if action in {"deleted", "absent"}:
            return "refused", None, None
        current_revision = _resolve_branch(manager, branch)
        if current_revision is not None:
            raise PromotionManagerAuditFault(
                f"refused promotion left branch with reaper action {action!r}",
                integration_branch=branch,
                integration_revision=current_revision,
            )
        raise PromotionManagerAuditPending(
            "refused promotion did not prove branch deletion"
        )

    if outcome == "faulted":
        exact_branch, exact_revision = _exact_fault_identity(manager, snapshot)
        return "faulted", exact_branch, exact_revision

    raise PromotionManagerAuditPending(f"unknown promotion outcome {outcome!r}")


class _AuditedExecutionLedger:
    def __init__(self, delegate: object, *, state: _BoundaryState) -> None:
        self._delegate = delegate
        self._state = state

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def begin(self, *args: Any, **kwargs: Any) -> Any:
        return self._delegate.begin(*args, **kwargs)

    def complete(
        self,
        start: Any,
        *,
        receipt_id: str,
        outcome: str,
        report: Mapping[str, Any],
        primary_checkout_after_sha256: str,
        integration_branch: str | None = None,
        integration_revision: str | None = None,
    ) -> Any:
        manager = self._state.active_manager.get()
        if manager is None:
            return self._delegate.complete(
                start,
                receipt_id=receipt_id,
                outcome=outcome,
                report=report,
                primary_checkout_after_sha256=primary_checkout_after_sha256,
                integration_branch=integration_branch,
                integration_revision=integration_revision,
            )

        snapshot = manager.snapshot()
        enriched = dict(report)
        enriched["manager_audit"] = snapshot.to_dict()
        enriched["manager_audit_sha256"] = snapshot.digest
        assessed_outcome, assessed_branch, assessed_revision = _assess_completion(
            manager=manager,
            snapshot=snapshot,
            outcome=outcome,
            report=enriched,
            integration_branch=integration_branch,
            integration_revision=integration_revision,
        )
        return self._delegate.complete(
            start,
            receipt_id=receipt_id,
            outcome=assessed_outcome,
            report=enriched,
            primary_checkout_after_sha256=primary_checkout_after_sha256,
            integration_branch=assessed_branch,
            integration_revision=assessed_revision,
        )


def install_promotion_manager_boundary(namespace: MutableMapping[str, Any]) -> None:
    """Replace only constructor seams in one executed gated-writes namespace."""
    parent = namespace.get("promote_candidates")
    manager_constructor = namespace.get("GitWorktreeManager")
    ledger_constructor = namespace.get("PromotionExecutionLedger")
    if not callable(parent) or not callable(manager_constructor) or not callable(
        ledger_constructor
    ):
        raise RuntimeError("promotion manager boundary installation target is invalid")

    state = _BoundaryState(
        manager_constructor=manager_constructor,
        ledger_constructor=ledger_constructor,
        parent_promote_candidates=parent,
        active_manager=contextvars.ContextVar(
            "daedalus_active_promotion_manager_audit",
            default=None,
        ),
    )
    namespace["_promotion_manager_boundary_state"] = state
    namespace["_REAL_GIT_WORKTREE_MANAGER"] = manager_constructor
    namespace["_REAL_PROMOTION_EXECUTION_LEDGER"] = ledger_constructor
    namespace["_ACCOUNTED_PROMOTE_CANDIDATES"] = parent
    namespace["GitWorktreeManager"] = state.manager_factory
    namespace["PromotionExecutionLedger"] = state.ledger_factory
    namespace["promote_candidates"] = state.promote_candidates


__all__ = [
    "PromotionManagerAuditFault",
    "PromotionManagerAuditPending",
    "install_promotion_manager_boundary",
]
