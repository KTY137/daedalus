"""RoleHarness -> live TaskAttempt -> sealed Claude runner regressions."""
from __future__ import annotations

from dataclasses import replace
import importlib.util
import sys
from pathlib import Path

import pytest

import daedalus.orchestration.ikarus.claude_composition as composition
import daedalus.orchestration.ikarus.claude_task_attempt_authority as authority
import daedalus.orchestration.ikarus.claude_task_attempt_runner as runner_adapter
from daedalus.orchestration.ikarus.claude_attempt_handoff import ClaudeTaskAttemptRunnerHandoff
from daedalus.orchestration.ikarus.runtime_role import (
    AUTHENTICATED_HANDOFF_EXECUTION_MODE,
    SOURCE_ONLY_EXECUTION_MODE,
    RuntimeRoleBinding,
    RuntimeRoleRegistry,
)
from daedalus.orchestration.ikarus.supervisor import PlannedItem
from daedalus.providers.claude_cli import (
    RUNTIME_ID as CLAUDE_RUNTIME_ID,
    ClaudeWorkspaceGrant,
)
from daedalus.runtimes.provider.invocation_payload import ProviderInvocationPayload
from daedalus.runtimes.provider.runtime_executable_binding import (
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


def _runtime_binding():
    binding = RuntimeRoleBinding(
        role="assistant",
        runtime_id=CLAUDE_RUNTIME_ID,
        adapter_id="claude.oneshot-adapter",
        adapter_version="test-1",
        source_revision=fixture.CLAUDE_SOURCE_REVISION,
        origin="tests://ikarus-claude-composition",
        execution_mode=AUTHENTICATED_HANDOFF_EXECUTION_MODE,
    )
    snapshot = RuntimeRoleRegistry((binding,)).snapshot("assistant", CLAUDE_RUNTIME_ID)
    assert snapshot is not None
    return snapshot


def _source_only_runtime_binding():
    binding = RuntimeRoleBinding(
        role="assistant",
        runtime_id=CLAUDE_RUNTIME_ID,
        adapter_id="claude.oneshot-adapter",
        adapter_version="test-1",
        source_revision=fixture.CLAUDE_SOURCE_REVISION,
        origin="tests://ikarus-claude-composition",
        execution_mode=SOURCE_ONLY_EXECUTION_MODE,
        refusal_reason="declaration only; authenticated handoff is not admitted",
    )
    snapshot = RuntimeRoleRegistry((binding,)).snapshot("assistant", CLAUDE_RUNTIME_ID)
    assert snapshot is not None
    return snapshot


def _live_subjects(tmp_path: Path):
    return fixture._subjects(
        tmp_path,
        execution_mode=AUTHENTICATED_HANDOFF_EXECUTION_MODE,
    )


def test_handoff_runner_factory_refuses_source_only_runtime_before_resolver():
    resolved = False

    def resolve_inputs(item, handoff):
        nonlocal resolved
        resolved = True
        raise AssertionError("source-only runtime must never resolve provider inputs")

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="authenticated-handoff runtime binding",
    ):
        runner_adapter.make_task_attempt_claude_handoff_runner_factory(
            _source_only_runtime_binding(),
            resolve_inputs,
        )

    assert resolved is False


def _item(subjects, **overrides):
    values = {
        "objective": "dispatch the exact planned Claude runtime",
        "role": "assistant",
        "paths": tuple(subjects[1].writable_paths),
        "runtime_id": CLAUDE_RUNTIME_ID,
    }
    values.update(overrides)
    return PlannedItem(**values)


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
    subjects = _live_subjects(tmp_path)
    handoff = _handoff(subjects, tmp_path)
    planned_item = _item(subjects)
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
        assert item is planned_item
        assert authenticated_handoff is handoff
        return _inputs(subjects)

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        resolve_inputs,
    )
    provider_runner = factory(planned_item, handoff)

    # Canonical authority composition happens in the RoleHarness factory seam,
    # before provider-controlled runner execution can start.
    assert events == ["resolve", "bind"]

    result = provider_runner(object())

    assert events == ["resolve", "bind", "provider"]
    assert result["mission_id"] == subjects[0].mission_id
    assert result["work_item_id"] == subjects[1].task_id
    assert result["attempt_id"] == subjects[1].attempt_id


def test_handoff_runner_uses_only_sealed_invocation_after_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Late runner-context substitution cannot retarget the sealed provider call."""

    subjects = _live_subjects(tmp_path)
    handoff = _handoff(subjects, tmp_path)
    body = fixture._provider_body(subjects, tmp_path)
    expected = object.__new__(ProviderRuntimeExecutableBindingReceipt)
    observed = {}

    monkeypatch.setattr(
        authority,
        "bind_provider_runtime_invocation",
        lambda *args, **kwargs: expected,
    )
    monkeypatch.setattr(
        ProviderInvocationPayload,
        "to_dict",
        lambda self: {"body": dict(body)},
    )

    # PORT NOTE: main's ask_claude takes the nine authority members as separate
    # keyword arguments (and refuses any partial set), where the originating
    # lane took one `sealed_bundle`. The double mirrors the real signature.
    def fake_ask_claude(
        objective,
        worktree,
        paths,
        *,
        model,
        timeout_s,
        **members,
    ):
        observed.update(
            objective=objective,
            worktree=worktree,
            paths=list(paths),
            model=model,
            timeout_s=timeout_s,
            members=members,
        )
        return _terminal_provider_result(subjects, body)

    monkeypatch.setattr(authority, "ask_claude", fake_ask_claude)
    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        lambda item, authenticated_handoff: _inputs(subjects),
    )
    provider_runner = factory(_item(subjects), handoff)

    late_context = type(
        "LateSubstitutedRunnerContext",
        (),
        {
            "worktree": tmp_path / "foreign-worktree",
            "branch": "attempt-foreign",
            "base_revision": "f" * 40,
            "task": object(),
        },
    )()
    result = provider_runner(late_context)

    assert observed["objective"] == body["objective"]
    assert observed["worktree"] == body["worktree"]
    assert observed["paths"] == body["paths"]
    assert observed["model"] == body["model"]
    assert observed["timeout_s"] == body["timeout_s"]
    # The complete authority member set must reach the provider seam; main's
    # bridge refuses a partial set, so an empty/short mapping is a real failure.
    assert set(observed["members"]) == set(composition._SEALED_BUNDLE_MEMBERS)
    assert all(value is not None for value in observed["members"].values())
    assert result["attempt_id"] == handoff.attempt_id


def test_handoff_runner_factory_refuses_nonexact_input_set_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _live_subjects(tmp_path)
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run for a non-exact input set")

    monkeypatch.setattr(authority, "ask_claude", fail_if_called)
    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        lambda item, handoff: {"not": "canonical"},
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="exact ClaudeTaskAttemptInvocationInputs",
    ):
        factory(_item(subjects), _handoff(subjects, tmp_path))

    assert called is False


def test_handoff_runner_factory_refuses_foreign_workspace_before_runner_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subjects = _live_subjects(tmp_path)
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
        _runtime_binding(),
        lambda item, handoff: _inputs(subjects, workspace_grant=foreign),
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="workspace attempt",
    ):
        factory(_item(subjects), _handoff(subjects, tmp_path))

    assert provider_called is False


def test_handoff_runner_factory_requires_exact_authenticated_handoff(
    tmp_path: Path,
) -> None:
    subjects = _live_subjects(tmp_path)
    resolved = False

    def resolve_inputs(item, handoff):
        nonlocal resolved
        resolved = True
        return _inputs(subjects)

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        resolve_inputs,
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="exact authenticated",
    ):
        factory(_item(subjects), object())

    assert resolved is False


def test_handoff_runner_factory_refuses_plan_runtime_substitution_before_resolver(
    tmp_path: Path,
) -> None:
    subjects = _live_subjects(tmp_path)
    resolved = False

    def resolve_inputs(item, handoff):
        nonlocal resolved
        resolved = True
        return _inputs(subjects)

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        resolve_inputs,
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="planned runtime-role binding",
    ):
        factory(
            _item(subjects, runtime_id="claude-substituted"),
            _handoff(subjects, tmp_path),
        )

    assert resolved is False


def test_handoff_runner_factory_refuses_resolved_runtime_binding_substitution(
    tmp_path: Path,
) -> None:
    subjects = _live_subjects(tmp_path)
    foreign_request = replace(subjects[2], runtime_binding_sha256="f" * 64)
    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        _runtime_binding(),
        lambda item, handoff: _inputs(subjects, request=foreign_request),
    )

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="request runtime binding",
    ):
        factory(_item(subjects), _handoff(subjects, tmp_path))


def test_handoff_runner_factory_snapshots_planned_runtime_binding(
    tmp_path: Path,
) -> None:
    subjects = _live_subjects(tmp_path)
    runtime_binding = _runtime_binding()
    resolved = False

    def resolve_inputs(item, handoff):
        nonlocal resolved
        resolved = True
        return {"not": "canonical"}

    factory = runner_adapter.make_task_attempt_claude_handoff_runner_factory(
        runtime_binding,
        resolve_inputs,
    )
    object.__setattr__(runtime_binding, "runtime_id", "mutated-after-factory")

    with pytest.raises(
        authority.IkarusClaudeTaskAttemptAuthorityRefused,
        match="exact ClaudeTaskAttemptInvocationInputs",
    ):
        factory(_item(subjects), _handoff(subjects, tmp_path))

    assert resolved is True
