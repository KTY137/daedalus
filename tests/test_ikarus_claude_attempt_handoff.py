"""Regressions for the durable Attempt -> Claude producer boundary."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.ikarus_claude_attempt_handoff as handoff
from daedalus.kernel.attempts import (
    AttemptBeginResult,
    AttemptLedger,
    AttemptStartRecord,
    PreparedAttempt,
)
from daedalus.schemas import AttemptContract
from daedalus.spine.attempt import RunnerContext, TaskAttempt, TaskSpec


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_FIXTURE = ROOT / "tests/test_ikarus_claude_composition.py"


def _load_composition_fixture():
    name = "daedalus_test_ikarus_claude_attempt_handoff_fixture"
    spec = importlib.util.spec_from_file_location(name, COMPOSITION_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_composition_fixture()


class _AttemptLedgerProbe(AttemptLedger):
    """Type-compatible read probe without opening a second Event-Store in unit tests."""

    def __init__(self, pending_starts):
        self._pending_starts = tuple(pending_starts)

    def pending(self):
        return self._pending_starts


def _begin_for(attempt, *, execute: bool = True, attempt_sha256: str | None = None):
    start = object.__new__(AttemptStartRecord)
    object.__setattr__(start, "attempt_id", attempt.attempt_id)
    object.__setattr__(
        start,
        "attempt_sha256",
        attempt.digest if attempt_sha256 is None else attempt_sha256,
    )
    object.__setattr__(start, "source_revision", attempt.base_revision)
    return AttemptBeginResult(start=start, execute=execute)


def _dispatch_args(tmp_path: Path):
    subjects = fixture._subjects(tmp_path)
    (
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        members,
    ) = subjects
    return (
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        members,
    )


def _prepared_for(subjects, *, execute: bool = True, workspace: Path | None = None):
    attempt = subjects[1]
    grant = subjects[7]["workspace_grant"]
    begin = _begin_for(attempt, execute=execute)
    if execute:
        selected_workspace = Path(grant.worktree) if workspace is None else workspace
    else:
        selected_workspace = None
    return PreparedAttempt(begin=begin, workspace=selected_workspace)


def _execute(prepared, subjects, *, attempt_ledger=None):
    (
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        members,
    ) = subjects
    if attempt_ledger is None:
        if isinstance(prepared, PreparedAttempt):
            start = prepared.begin.start
        else:
            start = prepared.start
        attempt_ledger = _AttemptLedgerProbe((start,))
    return handoff.execute_started_mission_bound_claude_invocation(
        prepared,
        mission,
        attempt,
        request,
        runtime_evidence,
        tool_scope,
        effect_request,
        execution,
        attempt_ledger=attempt_ledger,
        runtime_authorization=members["runtime_authorization"],
        workspace_grant=members["workspace_grant"],
        invocation_authority=members["invocation_authority"],
        invocation_payload=members["invocation_payload"],
        invocation_abi=members["invocation_abi"],
        observation_binding_ledger=members["observation_binding_ledger"],
        executable_registry=members["executable_registry"],
        pre_admission=members["pre_admission"],
        at=fixture.fixture.fixture.NOW,
    )


def _task_attempt_owner(subjects):
    mission, terminal_attempt = subjects[:2]
    task = TaskSpec(
        task_id=terminal_attempt.task_id,
        instruction=terminal_attempt.instruction,
        base_revision=terminal_attempt.base_revision,
        target_paths=("workspace/out.txt",),
    )
    owner = object.__new__(TaskAttempt)
    object.__setattr__(owner, "task", task)
    object.__setattr__(owner, "mission_id", mission.mission_id)
    object.__setattr__(owner, "attempt_id", terminal_attempt.attempt_id)
    object.__setattr__(owner, "branch", terminal_attempt.attempt_id)
    object.__setattr__(owner, "effect_key", terminal_attempt.attempt_id)
    return owner, task


def _terminal_for_binding(binding, **overrides):
    values = {
        "mission_id": binding.mission_id,
        "task_id": binding.work_item_id,
        "attempt_id": binding.attempt_id,
        "base_revision": binding.source_revision,
        "task_sha256": binding.task_sha256,
        "writable_paths": binding.target_paths,
    }
    values.update(overrides)
    contract = object.__new__(AttemptContract)
    for field, value in values.items():
        object.__setattr__(contract, field, value)
    return contract


def test_task_attempt_owner_exposes_one_pre_effect_claude_identity(tmp_path):
    subjects = _dispatch_args(tmp_path)
    owner, task = _task_attempt_owner(subjects)

    binding = handoff.bind_task_attempt_claude_identity(owner, subjects[0])

    assert type(binding) is handoff.ClaudeTaskAttemptBinding
    assert binding.mission_id == subjects[0].mission_id
    assert binding.work_item_id == task.task_id
    assert binding.attempt_id == owner.attempt_id
    assert binding.source_revision == task.base_revision
    assert binding.task_sha256 == task.digest
    assert binding.target_paths == task.target_paths


def test_task_attempt_runner_context_authenticates_exact_isolated_workspace(tmp_path):
    subjects = _dispatch_args(tmp_path)
    owner, task = _task_attempt_owner(subjects)
    binding = handoff.bind_task_attempt_claude_identity(owner, subjects[0])
    worktree = tmp_path / "task-attempt-worktree"
    worktree.mkdir()
    context = RunnerContext(
        worktree=worktree,
        branch=binding.attempt_id,
        base_revision=binding.source_revision,
        task=task,
        is_cancelled=lambda: False,
    )

    runner_handoff = handoff.require_task_attempt_runner_context(binding, context)
    assert type(runner_handoff) is handoff.ClaudeTaskAttemptRunnerHandoff
    assert runner_handoff.mission_id == binding.mission_id
    assert runner_handoff.work_item_id == binding.work_item_id
    assert runner_handoff.attempt_id == binding.attempt_id
    assert runner_handoff.source_revision == binding.source_revision
    assert runner_handoff.task_sha256 == binding.task_sha256
    assert runner_handoff.target_paths == binding.target_paths
    assert runner_handoff.worktree == worktree.resolve()

    # Provider-facing callback evidence is deliberately a copy. Even hostile
    # mutation through object.__setattr__ cannot rewrite the supervisor-owned
    # binding that terminal verification later consumes.
    object.__setattr__(runner_handoff, "attempt_id", "attempt-mutated")
    assert binding.attempt_id == owner.attempt_id

    substituted = RunnerContext(
        worktree=worktree,
        branch="attempt-foreign",
        base_revision=binding.source_revision,
        task=task,
        is_cancelled=lambda: False,
    )
    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="attempt id",
    ):
        handoff.require_task_attempt_runner_context(binding, substituted)


def test_task_attempt_runner_rejects_task_substitution_before_provider_use(tmp_path):
    subjects = _dispatch_args(tmp_path)
    owner, task = _task_attempt_owner(subjects)
    binding = handoff.bind_task_attempt_claude_identity(owner, subjects[0])
    worktree = tmp_path / "task-attempt-worktree"
    worktree.mkdir()
    foreign_task = TaskSpec(
        task_id=task.task_id,
        instruction=task.instruction + " substituted",
        base_revision=task.base_revision,
        target_paths=task.target_paths,
    )
    context = RunnerContext(
        worktree=worktree,
        branch=binding.attempt_id,
        base_revision=binding.source_revision,
        task=foreign_task,
        is_cancelled=lambda: False,
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="task digest",
    ):
        handoff.require_task_attempt_runner_context(binding, context)


def test_task_attempt_owner_must_have_one_attempt_branch_effect_identity(tmp_path):
    subjects = _dispatch_args(tmp_path)
    owner, _ = _task_attempt_owner(subjects)
    object.__setattr__(owner, "effect_key", "attempt-foreign")

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="attempt/branch/effect identity",
    ):
        handoff.bind_task_attempt_claude_identity(owner, subjects[0])


def test_terminal_attempt_contract_must_corroborate_pre_effect_owner(tmp_path):
    subjects = _dispatch_args(tmp_path)
    owner, _ = _task_attempt_owner(subjects)
    binding = handoff.bind_task_attempt_claude_identity(owner, subjects[0])
    terminal = _terminal_for_binding(binding)

    assert handoff.require_task_attempt_terminal_contract(binding, terminal) is terminal

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="attempt id",
    ):
        handoff.require_task_attempt_terminal_contract(
            binding,
            _terminal_for_binding(binding, attempt_id="attempt-foreign"),
        )
    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="task digest",
    ):
        handoff.require_task_attempt_terminal_contract(
            binding,
            _terminal_for_binding(binding, task_sha256="f" * 64),
        )
    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="writable paths",
    ):
        handoff.require_task_attempt_terminal_contract(
            binding,
            _terminal_for_binding(binding, writable_paths=("foreign/path",)),
        )


def test_fresh_prepared_attempt_reaches_existing_atomic_handoff(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    attempt = subjects[1]
    prepared = _prepared_for(subjects)
    calls = []

    def fake_execute(*args, **kwargs):
        calls.append((args, kwargs))
        return {"provider": "claude_cli", "attempt_id": attempt.attempt_id}

    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        fake_execute,
    )

    result = _execute(prepared, subjects)

    assert result["provider"] == "claude_cli"
    assert result["attempt_id"] == attempt.attempt_id
    assert len(calls) == 1
    assert calls[0][0][0] is subjects[0]
    assert calls[0][0][1] is attempt


def test_existing_or_pending_attempt_cannot_start_new_provider_run(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    prepared = _prepared_for(subjects, execute=False)
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="fresh durable Attempt-start winner",
    ):
        _execute(prepared, subjects)

    assert calls == []


def test_stale_prepared_attempt_cannot_dispatch_after_lifecycle_resolution(
    tmp_path,
    monkeypatch,
):
    subjects = _dispatch_args(tmp_path)
    prepared = _prepared_for(subjects)
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="no longer the live pending Attempt",
    ):
        _execute(
            prepared,
            subjects,
            attempt_ledger=_AttemptLedgerProbe(()),
        )

    assert calls == []


def test_live_ledger_start_must_equal_prepared_start(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    prepared = _prepared_for(subjects)
    different_start = _begin_for(subjects[1]).start
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="differs from the prepared Attempt start",
    ):
        _execute(
            prepared,
            subjects,
            attempt_ledger=_AttemptLedgerProbe((different_start,)),
        )

    assert calls == []


def test_noncanonical_attempt_ledger_fails_before_provider(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    prepared = _prepared_for(subjects)
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="canonical AttemptLedger",
    ):
        _execute(prepared, subjects, attempt_ledger=object())

    assert calls == []


def test_persisted_start_for_other_attempt_digest_fails_before_provider(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    begin = _begin_for(subjects[1], attempt_sha256="f" * 64)
    prepared = PreparedAttempt(
        begin=begin,
        workspace=Path(subjects[7]["workspace_grant"].worktree),
    )
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="attempt digest",
    ):
        _execute(prepared, subjects)

    assert calls == []


def test_recombined_workspace_fails_before_provider(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    other_workspace = tmp_path / "other-workspace"
    other_workspace.mkdir()
    prepared = _prepared_for(subjects, workspace=other_workspace)
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="does not bind the prepared Attempt workspace",
    ):
        _execute(prepared, subjects)

    assert calls == []


def test_bare_attempt_begin_is_no_longer_a_dispatch_boundary(tmp_path, monkeypatch):
    subjects = _dispatch_args(tmp_path)
    begin = _begin_for(subjects[1])
    calls = []
    monkeypatch.setattr(
        handoff,
        "execute_mission_bound_claude_invocation",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(
        handoff.IkarusClaudeAttemptHandoffRefused,
        match="exact PreparedAttempt",
    ):
        _execute(begin, subjects)

    assert calls == []
