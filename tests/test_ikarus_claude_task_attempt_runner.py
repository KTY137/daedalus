"""RoleHarness -> live TaskAttempt -> sealed Claude runner regressions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.ikarus_claude_task_attempt_authority as authority
import daedalus.ikarus_claude_task_attempt_runner as runner_adapter
from daedalus.ikarus_claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from daedalus.providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from daedalus.runtimes.provider_invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider_runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)


ROOT = Path(__file__).resolve().parents[1]
COMPOSITION_FIXTURE = ROOT / "tests/test_ikarus_claude_composition.py"


def _load_composition_fixture():
    name = "daedalus_test_ikarus_task_attempt_runner_fixture"
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


def _inputs(subjects, **overrides):
    mission, _, request, evidence, tools, effect_request, execution, members = subjects
    values = {
        "mission": mission,
        "request": request,
        "runtime_evidence": evidence,
        "tool_scope": tools,
        "effect_request": effect_request,
        "execution": execution,
        **members,
        "at": fixture.fixture.fixture.NOW,
    }
    values.update(overrides)
    return runner_adapter.ClaudeTaskAttemptInvocationInputs(**values)


def _terminal_provider_result(subjects, body):
    return {
        "provider": "claude_cli",
        "runtime_id": CLAUDE_RUNTIME_ID,
        "attempt_id": subjects[1].attempt_id,
        "phase": "terminal",
        "terminal_receipt_sha256": "f" * 64,
        "runtime_receipt": {
            "executed": True,
            "invocation_sha256": body["invocation_sha256"],
            "start_receipt_sha256": "a" * 64,
            "terminal_receipt_sha256": "f" * 64,
        },
        "report": {"status": "done", "summary": "bounded"},
    }


def test_handoff_runner_factory_seals_before_returning_provider_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    handoff = _handoff(subjects, tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    events = []

    def fake_bind(*args, **kwargs):
        events.append("bind")
        return expected

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fake_bind)
    body = fixture._provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )

    def fake_ask_claude(*args, **kwargs):
        events.append("provider")
        return _terminal_provider_result(subjects, body)

    monkeypatch.setattr(authority, "ask_claude", fake_ask_claude)

    def resolve_inputs(item, authenticated_handoff):
        events.append("resolve")
        assert item == {"id": subjects[1].task_id}
        assert authenticated_handoff is handoff
        return _inputs(subjects)

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        resolve_inputs
    )
    provider_runner = factory({"id": subjects[1].task_id}, handoff)

    # Canonical authority composition happens in the RoleHarness factory seam,
    # before provider-controlled runner execution can start.
    assert events == ["resolve", "bind"]

    result = provider_runner(object())

    assert events == ["resolve", "bind", "provider"]
    assert result["mission_id"] == subjects[0].mission_id
    assert result["work_item_id"] == subjects[1].task_id
    assert result["attempt_id"] == subjects[1].attempt_id


def test_handoff_runner_factory_refuses_nonexact_input_set_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run for a non-exact input set")

    monkeypatch.setattr(authority, "ask_claude", fail_if_called)
    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        lambda item, handoff: {"not": "canonical"}
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="exact ClaudeTaskAttemptInvocationInputs",
    ):
        factory(object(), _handoff(subjects, tmp_path))

    assert called is False


def test_handoff_runner_factory_refuses_foreign_workspace_before_runner_exists(
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
    provider_called = False

    def fake_bind(*args, **kwargs):
        raise AssertionError("foreign workspace must fail before canonical binding")

    def fail_if_called(*args, **kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("foreign workspace must not reach Claude")

    monkeypatch.setattr(authority, "bind_provider_runtime_invocation", fake_bind)
    monkeypatch.setattr(authority, "ask_claude", fail_if_called)
    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        lambda item, handoff: _inputs(subjects, workspace_grant=foreign)
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="workspace attempt",
    ):
        factory(object(), _handoff(subjects, tmp_path))

    assert provider_called is False


def test_handoff_runner_factory_requires_exact_authenticated_handoff(
    tmp_path: Path,
) -> None:
    subjects = fixture._subjects(tmp_path)
    resolved = False

    def resolve_inputs(item, handoff):
        nonlocal resolved
        resolved = True
        return _inputs(subjects)

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        resolve_inputs
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="exact authenticated",
    ):
        factory(object(), object())

    assert resolved is False
