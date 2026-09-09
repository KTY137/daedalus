"""Live TaskAttempt -> sealed Claude authority ownership regressions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.ikarus_claude_task_attempt_authority as authority
from daedalus.ikarus_claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from daedalus.providers.claude_cli import ClaudeWorkspaceGrant
from daedalus.runtimes.provider_runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)
from daedalus.runtimes.provider_runtime_invocation_binding import (
    ProviderRuntimeInvocationBindingMismatch,
)


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_FIXTURE = ROOT / "tests/test_ikarus_claude_composition.py"


def _load_composition_fixture():
    name = "daedalus_test_ikarus_task_attempt_authority_fixture"
    spec = importlib.util.spec_from_file_location(name, COMPOSITION_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_composition_fixture()


def _handoff(subjects, tmp_path: Path, **overrides) -> ClaudeTaskAttemptRunnerHandoff:
    mission, attempt = subjects[:2]
    values = {
        "mission_id": mission.mission_id,
        "work_item_id": attempt.task_id,
        "attempt_id": attempt.attempt_id,
        "source_revision": attempt.base_revision,
        "task_sha256": attempt.task_sha256,
        "target_paths": tuple(attempt.writable_paths),
        "worktree": tmp_path.resolve(),
    }
    values.update(overrides)
    return ClaudeTaskAttemptRunnerHandoff(**values)


def _bind(subjects, tmp_path: Path, handoff=None, **overrides):
    mission, _, request, evidence, tools, effect_request, execution, members = subjects
    kwargs = {**members, "at": fixture.fixture.fixture.NOW}
    kwargs.update(overrides)
    return authority.bind_task_attempt_claude_provider_authorities(
        handoff or _handoff(subjects, tmp_path),
        mission,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        **kwargs,
    )


def test_live_task_attempt_owner_authenticates_existing_provider_authorities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    calls = []

    def fake_bind(entrypoint_id, **kwargs):
        calls.append((entrypoint_id, kwargs))
        return expected

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fake_bind)

    receipt = _bind(subjects, tmp_path)

    assert receipt is expected
    assert len(calls) == 1
    entrypoint_id, call = calls[0]
    assert entrypoint_id == subjects[5].entrypoint_id
    assert call["authorization"] is subjects[7]["runtime_authorization"]
    assert call["execution"] is subjects[6]
    assert call["at"] == fixture.fixture.fixture.NOW


def test_live_task_attempt_refuses_foreign_workspace_before_provider_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    workspace = subjects[7]["workspace_grant"]
    foreign = ClaudeWorkspaceGrant(
        attempt_id="attempt-foreign",
        source_revision=workspace.source_revision,
        request_sha256=workspace.request_sha256,
        execution_sha256=workspace.execution_sha256,
        worktree=workspace.worktree,
    )
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("foreign workspace must not reach provider binding")

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="workspace attempt",
    ):
        _bind(subjects, tmp_path, workspace_grant=foreign)
    assert called is False


def test_live_task_attempt_refuses_effect_scope_outside_owner_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    narrow_owner = _handoff(subjects, tmp_path, target_paths=())
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("over-broad effect scope must not reach provider binding")

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="Effect Lease writable scope exceeds TaskAttempt owner scope",
    ):
        _bind(subjects, tmp_path, handoff=narrow_owner)
    assert called is False


def test_live_task_attempt_refuses_foreign_mission_before_provider_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    foreign_owner = _handoff(subjects, tmp_path, mission_id="mission-foreign")
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("foreign mission must not reach provider binding")

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fail_if_called)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="different Mission",
    ):
        _bind(subjects, tmp_path, handoff=foreign_owner)
    assert called is False


def test_live_task_attempt_translates_provider_authority_mismatch_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)

    def refuse(*args, **kwargs):
        raise ProviderRuntimeInvocationBindingMismatch("foreign sealed subject")

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", refuse)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="did not authenticate",
    ):
        _bind(subjects, tmp_path)


def test_live_task_attempt_refuses_nonexact_provider_binding_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: object(),
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="non-exact executable receipt",
    ):
        _bind(subjects, tmp_path)
