"""Bind canonical Attempt lifecycle evidence to the mission-bound Claude handoff.

The productive path has two deliberately different evidence shapes:

* ``TaskAttempt`` owns the real pre-effect lifecycle.  A
  :class:`ClaudeTaskAttemptBinding` freezes that owner's Mission/WorkItem/
  Attempt/source/task identity and authenticates the exact isolated
  ``RunnerContext.worktree`` before a provider runner may use it.  It is inert
  evidence, not a second Attempt authority or ledger.
* ``PreparedAttempt`` is the older kernel handoff used by the already sealed
  Claude composition tests.  Its durable Event-Store checks remain fail-closed
  while the productive supervisor path is cut over to the sole ``TaskAttempt``
  owner.

No authority is issued here and no state is reconstructed from chat, queue, or
status JSON.  A replayed/completed/pending Attempt, a stale prepared handle, a
recombined workspace, or a TaskAttempt/context identity substitution therefore
cannot trigger a Claude provider run through these entrypoints.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .ikarus_claude_composition import execute_mission_bound_claude_invocation
from .ikarus_oneshot import OneShotRequest, OneShotRuntimeEvidenceBinding
from .ikarus_tool_scope import IkarusToolScopeProjection
from .kernel.attempts import (
    AttemptBeginResult,
    AttemptLedger,
    AttemptStartRecord,
    PreparedAttempt,
)
from .kernel.contracts import EffectLeaseRequest
from .kernel.effects import EffectExecutionRequest
from .kernel.runtime_effects import RuntimeBoundEffectAuthorization
from .providers.claude_cli import ClaudeWorkspaceGrant
from .runtimes.provider_executable_object_registry import ProviderExecutableObjectRegistry
from .runtimes.provider_executable_pre_admission import (
    ProviderExecutablePreAdmissionReceipt,
)
from .runtimes.provider_invocation_abi import ProviderInvocationABIContract
from .runtimes.provider_invocation_authority import (
    ProviderInvocationObservationAuthority,
)
from .runtimes.provider_invocation_payload import ProviderInvocationPayload
from .runtimes.provider_observation import ProviderObservationBindingLedger
from .schemas import AttemptContract, MissionContract
from .spine.attempt import RunnerContext, TaskAttempt, TaskSpec


class IkarusClaudeAttemptHandoffRefused(RuntimeError):
    """Attempt lifecycle evidence does not authorize one Claude dispatch."""


@dataclass(frozen=True)
class ClaudeTaskAttemptBinding:
    """Inert identity frozen from the one ``TaskAttempt`` effect owner.

    This is intentionally *not* an ``AttemptContract``.  It cannot grant a
    runtime, workspace, tool, spend, network, or provider capability.  Its job
    is narrower: carry the identity that already exists on ``TaskAttempt`` into
    the runner boundary and later prove that terminal ``AttemptContract``
    evidence describes that same lifecycle rather than a second Attempt.
    """

    mission_id: str
    work_item_id: str
    attempt_id: str
    source_revision: str
    task_sha256: str
    target_paths: tuple[str, ...]


def _snapshot_mission(mission: MissionContract) -> MissionContract:
    if type(mission) is not MissionContract:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt Claude binding requires an exact MissionContract"
        )
    try:
        supplied_digest = str(mission.digest)
        snapshot = MissionContract.from_dict(mission.to_dict())
    except (AttributeError, TypeError, ValueError) as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "MissionContract could not be snapshotted for TaskAttempt binding"
        ) from exc
    if snapshot.digest != supplied_digest:
        raise IkarusClaudeAttemptHandoffRefused(
            "MissionContract changed while TaskAttempt binding was captured"
        )
    return snapshot


def bind_task_attempt_claude_identity(
    task_attempt: TaskAttempt,
    mission: MissionContract,
) -> ClaudeTaskAttemptBinding:
    """Freeze the sole pre-effect Attempt identity already owned by TaskAttempt.

    ``TaskAttempt`` assigns ``attempt_id`` before ``run()`` and uses the same
    value for its branch/effect identity.  The Claude path may consume that
    identity, but must not call a second ``AttemptLedger.begin`` to manufacture
    another lifecycle.  This function therefore only corroborates and freezes
    facts that already exist on the owner.
    """

    if type(task_attempt) is not TaskAttempt:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude binding requires the exact canonical TaskAttempt owner"
        )
    snapshot = _snapshot_mission(mission)
    task = getattr(task_attempt, "task", None)
    if type(task) is not TaskSpec:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt does not carry an exact canonical TaskSpec"
        )

    mission_id = str(getattr(task_attempt, "mission_id", ""))
    attempt_id = str(getattr(task_attempt, "attempt_id", ""))
    branch = str(getattr(task_attempt, "branch", ""))
    effect_key = str(getattr(task_attempt, "effect_key", ""))
    work_item_id = str(task.task_id)
    source_revision = str(task.base_revision or "")

    if mission_id != snapshot.mission_id:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt mission_id does not match the canonical MissionContract"
        )
    if work_item_id not in snapshot.work_item_ids:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt task_id is not a canonical MissionContract work item"
        )
    if not source_revision or source_revision != snapshot.source_revision:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt source revision does not match the canonical mission"
        )
    if not attempt_id or attempt_id != branch or attempt_id != effect_key:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt attempt/branch/effect identity is not one exact value"
        )

    return ClaudeTaskAttemptBinding(
        mission_id=snapshot.mission_id,
        work_item_id=work_item_id,
        attempt_id=attempt_id,
        source_revision=source_revision,
        task_sha256=task.digest,
        target_paths=tuple(task.target_paths),
    )


def require_task_attempt_runner_context(
    binding: ClaudeTaskAttemptBinding,
    context: RunnerContext,
) -> Path:
    """Authenticate the actual TaskAttempt runner/worktree before provider use.

    ``RunnerContext.branch`` is currently the transport spelling for the
    TaskAttempt-owned attempt identity.  This seam gives it one explicit
    meaning for Ikarus and refuses any task/source/path substitution before a
    provider runner can treat the materialized worktree as its workspace.
    """

    if type(binding) is not ClaudeTaskAttemptBinding:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude runner requires an exact TaskAttempt binding"
        )
    if type(context) is not RunnerContext:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude runner requires the exact canonical RunnerContext"
        )
    task = context.task
    if type(task) is not TaskSpec:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude runner context does not carry an exact TaskSpec"
        )

    mismatches = tuple(
        label
        for label, actual, expected in (
            ("attempt id", str(context.branch), binding.attempt_id),
            ("source revision", str(context.base_revision), binding.source_revision),
            ("work item", str(task.task_id), binding.work_item_id),
            ("task digest", task.digest, binding.task_sha256),
            ("target paths", tuple(task.target_paths), binding.target_paths),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt runner context differs from the pre-effect Claude binding: "
            + ", ".join(mismatches)
        )

    try:
        workspace = Path(context.worktree).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt runner workspace could not be resolved"
        ) from exc
    if not workspace.is_dir():
        raise IkarusClaudeAttemptHandoffRefused(
            "TaskAttempt runner workspace is not a directory"
        )
    return workspace


def require_task_attempt_terminal_contract(
    binding: ClaudeTaskAttemptBinding,
    attempt: AttemptContract,
) -> AttemptContract:
    """Prove terminal canonical evidence belongs to the pre-effect owner.

    The terminal contract may add runtime, policy, gate and receipt evidence;
    it may not replace Mission, WorkItem, Attempt, source, task or write-scope
    identity.  This is the same-lifecycle check needed before Work Pulse can
    display terminal evidence for a TaskAttempt-backed provider run.
    """

    if type(binding) is not ClaudeTaskAttemptBinding:
        raise IkarusClaudeAttemptHandoffRefused(
            "terminal verification requires an exact TaskAttempt binding"
        )
    if type(attempt) is not AttemptContract:
        raise IkarusClaudeAttemptHandoffRefused(
            "terminal verification requires an exact AttemptContract"
        )
    mismatches = tuple(
        label
        for label, actual, expected in (
            ("mission id", attempt.mission_id, binding.mission_id),
            ("work item", attempt.task_id, binding.work_item_id),
            ("attempt id", attempt.attempt_id, binding.attempt_id),
            ("source revision", attempt.base_revision, binding.source_revision),
            ("task digest", attempt.task_sha256, binding.task_sha256),
            ("writable paths", tuple(attempt.writable_paths), binding.target_paths),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeAttemptHandoffRefused(
            "terminal AttemptContract differs from the pre-effect TaskAttempt binding: "
            + ", ".join(mismatches)
        )
    return attempt


def require_fresh_persisted_attempt_start(
    begin: AttemptBeginResult,
    attempt: AttemptContract,
) -> AttemptStartRecord:
    """Authenticate the canonical Attempt-ledger start before any provider call.

    ``AttemptLedger.begin`` returns ``execute=True`` only for the transaction
    that durably won the single-start race.  Existing starts return
    ``execute=False`` (with a terminal completion for replay, or without one for
    reconciliation).  Only the fresh winner may cross this producer boundary.
    """

    if type(begin) is not AttemptBeginResult:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptBeginResult"
        )
    if type(attempt) is not AttemptContract:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptContract"
        )
    if begin.execute is not True or begin.completion is not None:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires the fresh durable Attempt-start winner"
        )
    start = begin.start
    if type(start) is not AttemptStartRecord:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptStartRecord"
        )

    mismatches = tuple(
        label
        for label, actual, expected in (
            ("attempt id", start.attempt_id, attempt.attempt_id),
            ("attempt digest", start.attempt_sha256, attempt.digest),
            ("source revision", start.source_revision, attempt.base_revision),
        )
        if actual != expected
    )
    if mismatches:
        raise IkarusClaudeAttemptHandoffRefused(
            "persisted Attempt start does not bind the Claude Attempt authority: "
            + ", ".join(mismatches)
        )
    return start


def require_live_pending_attempt(
    attempt_ledger: AttemptLedger,
    start: AttemptStartRecord,
) -> AttemptStartRecord:
    """Re-read canonical lifecycle state immediately before provider dispatch.

    ``PreparedAttempt`` is an immutable handoff value.  A caller can retain it
    after another path has already completed the Attempt, so trusting only its
    embedded ``AttemptBeginResult`` would turn a stale snapshot into execution
    authority.  The canonical Event-Store is therefore consulted again at the
    last producer boundary.  The exact persisted start must still be pending.
    """

    if not isinstance(attempt_ledger, AttemptLedger):
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires the canonical AttemptLedger"
        )
    if type(start) is not AttemptStartRecord:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact AttemptStartRecord"
        )
    try:
        matching = tuple(
            candidate
            for candidate in attempt_ledger.pending()
            if candidate.attempt_id == start.attempt_id
        )
    except Exception as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "canonical Attempt lifecycle could not be re-read before Claude dispatch"
        ) from exc
    if len(matching) != 1:
        raise IkarusClaudeAttemptHandoffRefused(
            "prepared Attempt is no longer the live pending Attempt"
        )
    candidate = matching[0]
    try:
        same_start = candidate is start or candidate == start
    except (AttributeError, TypeError, ValueError):
        same_start = False
    if not same_start:
        raise IkarusClaudeAttemptHandoffRefused(
            "live pending Attempt start differs from the prepared Attempt start"
        )
    return start


def require_fresh_prepared_attempt_workspace(
    prepared: PreparedAttempt,
    attempt: AttemptContract,
    workspace_grant: ClaudeWorkspaceGrant,
) -> AttemptStartRecord:
    """Bind the durable start to the exact coordinator-prepared Claude workspace.

    ``PreparedAttempt`` is the kernel handoff produced only after the start was
    persisted and the source tree materialized.  Claude's structural workspace
    grant must name that same resolved directory; a separately supplied path is
    not allowed to ride on an otherwise valid Attempt start.
    """

    if type(prepared) is not PreparedAttempt:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact PreparedAttempt"
        )
    if type(workspace_grant) is not ClaudeWorkspaceGrant:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude handoff requires an exact ClaudeWorkspaceGrant"
        )

    start = require_fresh_persisted_attempt_start(prepared.begin, attempt)
    if prepared.workspace is None:
        raise IkarusClaudeAttemptHandoffRefused(
            "fresh Claude handoff requires the prepared Attempt workspace"
        )
    if workspace_grant.attempt_id != attempt.attempt_id:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant belongs to a different Attempt"
        )
    if workspace_grant.source_revision != attempt.base_revision:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant belongs to a different source revision"
        )

    try:
        prepared_workspace = Path(prepared.workspace).expanduser().resolve(strict=True)
        granted_workspace = Path(workspace_grant.worktree).expanduser().resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise IkarusClaudeAttemptHandoffRefused(
            "prepared Claude workspace could not be resolved"
        ) from exc
    if not prepared_workspace.is_dir() or prepared_workspace != granted_workspace:
        raise IkarusClaudeAttemptHandoffRefused(
            "Claude workspace grant does not bind the prepared Attempt workspace"
        )
    return start


def execute_started_mission_bound_claude_invocation(
    prepared: PreparedAttempt,
    mission: MissionContract,
    attempt: AttemptContract,
    request: OneShotRequest,
    runtime_evidence: OneShotRuntimeEvidenceBinding,
    tool_scope: IkarusToolScopeProjection,
    effect_request: EffectLeaseRequest,
    execution: EffectExecutionRequest,
    *,
    attempt_ledger: AttemptLedger,
    runtime_authorization: RuntimeBoundEffectAuthorization,
    workspace_grant: ClaudeWorkspaceGrant,
    invocation_authority: ProviderInvocationObservationAuthority,
    invocation_payload: ProviderInvocationPayload,
    invocation_abi: ProviderInvocationABIContract,
    observation_binding_ledger: ProviderObservationBindingLedger,
    executable_registry: ProviderExecutableObjectRegistry,
    pre_admission: ProviderExecutablePreAdmissionReceipt,
    at: datetime,
) -> dict[str, Any]:
    """Dispatch Claude only from a live, durable, prepared canonical Attempt.

    Lifecycle/workspace authentication and a live Event-Store re-read happen
    before the existing atomic authority composition seam is entered.  The
    downstream function still re-authenticates Mission, WorkItem, Attempt,
    runtime, Effect, workspace, ABI, executable and observation authority; this
    wrapper contributes only durable lifecycle facts and exact prepared-workspace
    identity.
    """

    start = require_fresh_prepared_attempt_workspace(
        prepared,
        attempt,
        workspace_grant,
    )
    require_live_pending_attempt(attempt_ledger, start)
    return execute_mission_bound_claude_invocation(
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        runtime_authorization=runtime_authorization,
        workspace_grant=workspace_grant,
        invocation_authority=invocation_authority,
        invocation_payload=invocation_payload,
        invocation_abi=invocation_abi,
        observation_binding_ledger=observation_binding_ledger,
        executable_registry=executable_registry,
        pre_admission=pre_admission,
        at=at,
    )


__all__ = [
    "ClaudeTaskAttemptBinding",
    "IkarusClaudeAttemptHandoffRefused",
    "bind_task_attempt_claude_identity",
    "execute_started_mission_bound_claude_invocation",
    "require_fresh_persisted_attempt_start",
    "require_fresh_prepared_attempt_workspace",
    "require_live_pending_attempt",
    "require_task_attempt_runner_context",
    "require_task_attempt_terminal_contract",
]
