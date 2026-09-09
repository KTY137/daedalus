"""Live TaskAttempt -> sealed Claude authority ownership regressions."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.orchestration.ikarus.claude_composition as composition
import daedalus.orchestration.ikarus.claude_task_attempt_authority as authority
from daedalus.orchestration.ikarus.claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from daedalus.providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from daedalus.runtimes.provider.invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider.runtime_executable_binding import (
    ProviderRuntimeExecutableBindingReceipt,
)
from daedalus.runtimes.provider.runtime_invocation_binding import (
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


def _compose(subjects, tmp_path: Path, handoff=None, **overrides):
    mission, _, request, evidence, tools, effect_request, execution, members = subjects
    kwargs = {**members, "at": fixture.fixture.fixture.NOW}
    kwargs.update(overrides)
    return authority.compose_task_attempt_bound_claude_invocation(
        handoff or _handoff(subjects, tmp_path),
        mission,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        **kwargs,
    )


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


def test_live_task_attempt_dispatches_without_terminal_attempt_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: expected,
    )
    invocation = _compose(subjects, tmp_path)
    body = fixture._provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    calls = []

    # PORT NOTE: main's ask_claude takes the nine authority members as separate
    # keyword arguments (and refuses any partial set), where the originating
    # lane took one `sealed_bundle`. The double mirrors the real signature.
    def fake_ask_claude(
        objective,
        repo_root,
        paths,
        model="sonnet",
        timeout_s=300,
        **members,
    ):
        calls.append(
            {
                "objective": objective,
                "repo_root": repo_root,
                "paths": paths,
                "model": model,
                "timeout_s": timeout_s,
                "members": members,
            }
        )
        return _terminal_provider_result(subjects, body)

    monkeypatch.setattr(authority, "ask_claude", fake_ask_claude)

    result = authority.dispatch_task_attempt_bound_claude_invocation(invocation)

    assert len(calls) == 1
    assert calls[0]["repo_root"] == str(tmp_path)
    # Identity, not equality: the exact member objects held by the sealed
    # bundle must be the ones that reach the provider seam.
    assert set(calls[0]["members"]) == set(composition._SEALED_BUNDLE_MEMBERS)
    assert all(
        calls[0]["members"][name] is getattr(invocation.sealed_bundle, name)
        for name in composition._SEALED_BUNDLE_MEMBERS
    )
    assert result["mission_id"] == subjects[0].mission_id
    assert result["work_item_id"] == subjects[1].task_id
    assert result["attempt_id"] == subjects[1].attempt_id
    assert result["phase"] == "terminal"


def test_live_task_attempt_refuses_payload_path_escape_before_provider_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: expected,
    )
    invocation = _compose(subjects, tmp_path)
    body = fixture._provider_body(subjects, tmp_path)
    body["paths"] = ["../escape.py"]
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("path escape must not reach Claude")

    monkeypatch.setattr(authority, "ask_claude", fail_if_called)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="payload path exceeds TaskAttempt owner scope",
    ):
        authority.dispatch_task_attempt_bound_claude_invocation(invocation)
    assert called is False


def test_live_task_attempt_refuses_foreign_provider_attempt_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: expected,
    )
    invocation = _compose(subjects, tmp_path)
    body = fixture._provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    result = _terminal_provider_result(subjects, body)
    result["attempt_id"] = "attempt-foreign"
    monkeypatch.setattr(authority, "ask_claude", lambda *args, **kwargs: result)

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="does not name the live TaskAttempt",
    ):
        authority.dispatch_task_attempt_bound_claude_invocation(invocation)


def test_live_task_attempt_execute_is_atomic_compose_then_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = fixture._subjects(tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: expected,
    )
    body = fixture._provider_body(subjects, tmp_path)
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )
    monkeypatch.setattr(
        authority,
        "ask_claude",
        lambda *args, **kwargs: _terminal_provider_result(subjects, body),
    )
    mission, _, request, evidence, tools, effect_request, execution, members = subjects

    result = authority.execute_task_attempt_bound_claude_invocation(
        _handoff(subjects, tmp_path),
        mission,
        request,
        evidence,
        tools,
        effect_request,
        execution,
        **members,
        at=fixture.fixture.fixture.NOW,
    )

    assert result["mission_id"] == mission.mission_id
    assert result["work_item_id"] == subjects[1].task_id
    assert result["attempt_id"] == subjects[1].attempt_id
