"""Lease-gated execution of the existing isolated attempt machinery.

This module is the Gate-0 strangler boundary for candidate-producing attempts.
It does not replace :mod:`daedalus.spine.attempt`; it binds that implementation
to one authenticated EffectLease, one AttemptContract and one persisted
execution identity. The legacy ``run_attempt`` import remains available for
callers that have not migrated and therefore remains a Gate-0 blocker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from daedalus.kernel.contracts import EffectLease, EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.schemas import AttemptContract, PolicyDecision, _repo_path
from daedalus.spine.attempt import (
    AttemptResult,
    RunnerContext,
    STATE_CANCELLED,
    STATE_CLEAN,
    STATE_GATES_FAILED,
    STATE_NO_CHANGE,
    TaskSpec,
    run_attempt,
)
from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    EntrypointSpec,
    GuardDecision,
)
from daedalus.spine.envelope import canonical_sha

LEASED_ATTEMPT_ENTRYPOINT = "kernel.leased_attempt"
_ATTEMPT_EFFECTS = tuple(
    sorted(
        (
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.REPOSITORY_MUTATION.value,
        )
    )
)
_COMPLETED_STATES = frozenset({STATE_CLEAN, STATE_GATES_FAILED, STATE_NO_CHANGE})


class LeasedAttemptError(RuntimeError):
    """Base class for an attempt refused by the lease integration boundary."""


class LeasedAttemptBindingError(LeasedAttemptError):
    """The task, contract, lease or returned result are not the same attempt."""


@dataclass(frozen=True)
class LeasedAttemptResult:
    """One persisted effect start and, when executed, its terminal receipt."""

    start_receipt: LeasedEffectStartReceipt
    terminal_receipt: EffectTerminalReceipt | None
    attempt: AttemptResult | None
    execute: bool
    error: str | None = None

    @property
    def replayed(self) -> bool:
        return not self.execute


def _normalized_paths(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                _repo_path(value, f"path[{index}]")
                for index, value in enumerate(values)
            }
        )
    )


def _bind_inputs(
    task: TaskSpec,
    attempt: AttemptContract,
    request: EffectLeaseRequest,
    policy: PolicyDecision,
    lease: EffectLease,
) -> None:
    mismatches: list[str] = []
    if task.task_id != attempt.task_id:
        mismatches.append("task_id")
    if task.digest != attempt.task_sha256:
        mismatches.append("task_sha256")
    if task.base_revision != attempt.base_revision:
        mismatches.append("base_revision")
    if _normalized_paths(task.target_paths) != attempt.writable_paths:
        mismatches.append("writable_paths")
    if attempt.read_only:
        mismatches.append("read_only")
    if request.entrypoint_id != LEASED_ATTEMPT_ENTRYPOINT:
        mismatches.append("entrypoint_id")
    if request.mission_id != attempt.mission_id:
        mismatches.append("mission_id")
    if request.attempt_id != attempt.attempt_id:
        mismatches.append("attempt_id")
    if request.provenance.source_revision != attempt.base_revision:
        mismatches.append("request_source_revision")
    if request.runtime_manifest_sha256 != attempt.runtime_manifest_sha256:
        mismatches.append("runtime_manifest_sha256")
    if request.runtime_conformance_sha256 is None:
        mismatches.append("runtime_conformance_sha256")
    if attempt.policy_decision_sha256 != policy.digest:
        mismatches.append("policy_decision_sha256")
    if tuple(request.requested_effects) != _ATTEMPT_EFFECTS:
        mismatches.append("requested_effects")
    if policy.subject_id != request.request_id:
        mismatches.append("policy_subject_id")
    if policy.subject_sha256 != request.digest:
        mismatches.append("policy_subject_sha256")
    if policy.effect_scope != request.effect_scope:
        mismatches.append("policy_effect_scope")
    if lease.request_id != request.request_id or lease.request_sha256 != request.digest:
        mismatches.append("lease_request")
    if lease.policy_decision_sha256 != policy.digest:
        mismatches.append("lease_policy_decision")
    if lease.entrypoint_id != request.entrypoint_id:
        mismatches.append("lease_entrypoint")
    if lease.runtime_manifest_sha256 != request.runtime_manifest_sha256:
        mismatches.append("lease_runtime_manifest")
    if lease.runtime_conformance_sha256 != request.runtime_conformance_sha256:
        mismatches.append("lease_runtime_conformance")
    if mismatches:
        raise LeasedAttemptBindingError(
            "leased attempt input binding mismatch: " + ", ".join(sorted(mismatches))
        )


def _candidate_locator_bound(result: AttemptResult) -> bool:
    artifact = result.artifact
    locator = result.artifact_locator
    return bool(
        artifact is not None
        and not artifact.is_empty
        and isinstance(locator, Mapping)
        and locator.get("uri") == f"sha256:{artifact.diff_sha256}"
        and isinstance(locator.get("locator_uri"), str)
        and str(locator["locator_uri"]).startswith("artifact-locator:sha256:")
    )


def _validate_result(
    result: AttemptResult,
    task: TaskSpec,
    attempt: AttemptContract,
) -> None:
    mismatches: list[str] = []
    if result.task_id != task.task_id:
        mismatches.append("result.task_id")
    if result.base_revision != attempt.base_revision:
        mismatches.append("result.base_revision")
    if result.artifact is not None:
        if result.artifact.task_id != task.task_id:
            mismatches.append("artifact.task_id")
        if result.artifact.base_revision != attempt.base_revision:
            mismatches.append("artifact.base_revision")
        changed = _normalized_paths(result.artifact.changed_paths)
        allowed = set(attempt.writable_paths)
        if any(path not in allowed for path in changed):
            mismatches.append("artifact.changed_paths")
    if result.state == STATE_CLEAN:
        if result.artifact is None or result.artifact.is_empty:
            mismatches.append("clean_without_artifact")
        if result.gates is None or not result.gates.passed:
            mismatches.append("clean_without_passing_gate")
        if not _candidate_locator_bound(result):
            mismatches.append("clean_without_bound_cas_locator")
        if result.persist_error:
            mismatches.append("clean_with_persist_error")
    if result.ledger_error:
        mismatches.append("attempt_ledger_error")
    if mismatches:
        raise LeasedAttemptBindingError(
            "leased attempt result binding mismatch: " + ", ".join(sorted(mismatches))
        )


def _terminal_outcome(result: AttemptResult) -> str:
    if result.state == STATE_CANCELLED:
        return "CANCELLED"
    if result.state in _COMPLETED_STATES:
        return "COMPLETED"
    return "FAILED"


def _output_digests(result: AttemptResult) -> tuple[str, ...]:
    values: set[str] = set()
    if result.artifact is not None:
        values.add(result.artifact.diff_sha256)
    if result.gates is not None:
        values.add(result.gates.output_sha256)
    return tuple(sorted(values))


def _failure_detail(error: str) -> str:
    return canonical_sha({"leased_attempt_error": error})


def run_leased_attempt(
    task: TaskSpec,
    *,
    attempt: AttemptContract,
    lease_request: EffectLeaseRequest,
    policy_decision: PolicyDecision,
    lease: EffectLease,
    effect_ledger: EffectLeaseLedger,
    keyring: Mapping[str, bytes | str],
    guard_decisions: Iterable[GuardDecision],
    current_kill_switch_generation: int,
    runner: Callable[[RunnerContext], Any],
    artifact_dir: str | Path,
    repo_root: str | Path | None = None,
    gate: Callable[[RunnerContext], Any] | None = None,
    ledger: Any = None,
    ledger_path: str | Path | None = None,
    cancel: Any = None,
    worktree_manager: Any = None,
    keep_worktree: bool = False,
    reap: bool = True,
    execution_id: str | None = None,
    idempotency_key: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    registry: Mapping[str, EntrypointSpec] | Sequence[EntrypointSpec] = REGISTRY_BY_ID,
) -> LeasedAttemptResult:
    """Run one exact isolated attempt at most once.

    The start receipt is committed before ``run_attempt`` is called. An exact
    replay returns the persisted receipt with ``execute=False`` and never calls
    the runner again. A clean attempt is accepted only when candidate bytes are
    durably persisted in the CAS and the locator binds the exact patch digest.
    """

    if not isinstance(task, TaskSpec):
        raise TypeError("task must be a TaskSpec")
    if not isinstance(attempt, AttemptContract):
        raise TypeError("attempt must be an AttemptContract")
    if not callable(runner):
        raise ValueError("leased attempt requires an explicit runner")
    if artifact_dir is None:
        raise ValueError("leased attempt requires a candidate artifact CAS root")

    _bind_inputs(task, attempt, lease_request, policy_decision, lease)

    execution = EffectExecutionRequest(
        execution_id=execution_id or f"{attempt.attempt_id}:run",
        idempotency_key=idempotency_key or f"{attempt.attempt_id}:candidate",
        requested_effects=_ATTEMPT_EFFECTS,
        writable_paths=attempt.writable_paths,
        tools=lease.effect_scope.tools,
        max_cost_microusd=0,
        kill_switch_ref=lease.effect_scope.kill_switch_ref,
        kill_switch_generation=current_kill_switch_generation,
    )
    start: EffectStartResult = effect_ledger.begin(
        lease,
        execution,
        request=lease_request,
        policy_decision=policy_decision,
        keyring=keyring,
        guard_decisions=guard_decisions,
        current_kill_switch_generation=current_kill_switch_generation,
        started_at=started_at,
        registry=registry,
    )
    if not start.execute:
        return LeasedAttemptResult(
            start_receipt=start.receipt,
            terminal_receipt=effect_ledger.terminal_receipt(start.receipt),
            attempt=None,
            execute=False,
        )

    try:
        result = run_attempt(
            task,
            runner=runner,
            repo_root=repo_root,
            gate=gate,
            ledger=ledger,
            ledger_path=ledger_path,
            cancel=cancel,
            worktree_manager=worktree_manager,
            keep_worktree=keep_worktree,
            reap=reap,
            artifact_dir=artifact_dir,
        )
        _validate_result(result, task, attempt)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        terminal = effect_ledger.finish(
            start.receipt,
            outcome="FAILED",
            detail_sha256=_failure_detail(error),
            finished_at=finished_at,
        )
        return LeasedAttemptResult(
            start_receipt=start.receipt,
            terminal_receipt=terminal,
            attempt=None,
            execute=True,
            error=error,
        )

    detail_sha256 = canonical_sha(result.to_dict())
    terminal = effect_ledger.finish(
        start.receipt,
        outcome=_terminal_outcome(result),
        output_digests=_output_digests(result),
        detail_sha256=detail_sha256,
        finished_at=finished_at,
    )
    return LeasedAttemptResult(
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        attempt=result,
        execute=True,
        error=None,
    )
