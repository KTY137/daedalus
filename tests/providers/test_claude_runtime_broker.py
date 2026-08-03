from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.claude_bridge as bridge
import daedalus.providers.claude_cli as claude_provider
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.providers.claude_cli import (
    ClaudeCLIProvider,
    ClaudeInvocationBindingMismatch,
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    ClaudeProviderWorkspaceMismatch,
    ClaudeWorkspaceGrant,
    claude_idempotency_key,
    claude_invocation_sha256,
)
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_sha


ENTRYPOINT = "provider.claude"
RUNTIME = "claude_code_cli"
REVISION = "a" * 40
REQUEST_SHA = "d" * 64
REPORT = {
    "status": "needs_review",
    "summary": "bounded review",
    "files_changed": [],
    "tests_run": [],
    "risks": [],
    "todos": [],
    "handoff": {},
}
OUTPUT = {
    "agent": "reviewer",
    "prompt_sha256": "b" * 64,
    "report_sha256": canonical_sha(REPORT),
    "report": REPORT,
}


def _spec(*, wiring: Wiring = Wiring.CENTRAL) -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.CLAUDE,
        target="daedalus.providers.claude_cli:ClaudeCLIProvider.run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.NETWORK_EGRESS,
            Effect.SPEND,
        ),
        guard_contracts=(
            "budget.process_guard",
            "provider.write_policy",
            "runtime.adapter_profile",
        ),
        wiring=wiring,
        runtime_id=RUNTIME,
    )


def _agent() -> dict[str, object]:
    return {
        "name": "reviewer",
        "call_name": "Mary",
        "model_tier": "sonnet",
        "must_read": [],
    }


def _invocation_sha(
    worktree: Path,
    *,
    objective: str = "review",
    paths: list[str] | None = None,
    agent: dict[str, object] | None = None,
    model: str = "sonnet",
    timeout_s: int = 300,
) -> str:
    return claude_invocation_sha256(
        objective=objective,
        worktree=str(worktree),
        paths=list(paths or []),
        agent=agent or _agent(),
        model=model,
        timeout_s=timeout_s,
        attempt_id="attempt-claude-1",
        source_revision=REVISION,
        request_sha256=REQUEST_SHA,
    )


def _execution(
    worktree: Path,
    *,
    objective: str = "review",
    paths: list[str] | None = None,
    agent: dict[str, object] | None = None,
    model: str = "sonnet",
    timeout_s: int = 300,
    **changes,
) -> EffectExecutionRequest:
    invocation_sha = _invocation_sha(
        worktree,
        objective=objective,
        paths=paths,
        agent=agent,
        model=model,
        timeout_s=timeout_s,
    )
    values = dict(
        execution_id="claude-execution-1",
        idempotency_key=claude_idempotency_key(invocation_sha),
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        writable_paths=(".",),
        egress_endpoints=("https://api.anthropic.com",),
        tools=("claude",),
        max_cost_microusd=1000,
        kill_switch_ref="mission-kill",
        kill_switch_generation=3,
    )
    values.update(changes)
    return EffectExecutionRequest(**values)


def _start_receipt(execution: EffectExecutionRequest) -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "1" * 64,
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
        "boundary_receipt_sha256": "3" * 64,
        "started_at": "2026-08-03T04:00:00+00:00",
    }
    return LeasedEffectStartReceipt(receipt_sha256=canonical_sha(body), **body)


class FakeAuthorization:
    def __init__(self, *, replay: bool = False, wiring: Wiring = Wiring.CENTRAL) -> None:
        self.request = SimpleNamespace(
            entrypoint_id=ENTRYPOINT,
            attempt_id="attempt-claude-1",
            digest=REQUEST_SHA,
            provenance=SimpleNamespace(source_revision=REVISION),
        )
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(entrypoint_id=ENTRYPOINT),
            runtime_id=RUNTIME,
        )
        spec = _spec(wiring=wiring)
        self.registry = {spec.id: spec}
        self.replay = replay
        self.grant_calls = 0
        self.begin_calls = 0
        self.verify_calls = 0
        self.received_executions: list[EffectExecutionRequest] = []
        self.finish_calls: list[dict[str, object]] = []

    def grant(self) -> None:
        self.grant_calls += 1

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        self.begin_calls += 1
        self.received_executions.append(execution)
        return EffectStartResult(
            receipt=_start_receipt(execution),
            execute=not self.replay,
        )

    def verify(self, *, now) -> object:
        self.verify_calls += 1
        assert now.tzinfo is not None
        return object()

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        outputs = tuple(output_digests)
        self.finish_calls.append(
            {
                "outcome": outcome,
                "output_digests": outputs,
                "detail_sha256": detail_sha256,
            }
        )
        finished_at = "2026-08-03T04:00:01+00:00"
        body = {
            "lease_sha256": start_receipt.lease_sha256,
            "execution_id": start_receipt.execution_id,
            "start_receipt_sha256": start_receipt.receipt_sha256,
            "outcome": outcome.upper(),
            "output_digests": list(outputs),
            "detail_sha256": detail_sha256,
            "finished_at": finished_at,
        }
        return EffectTerminalReceipt(
            lease_sha256=start_receipt.lease_sha256,
            execution_id=start_receipt.execution_id,
            start_receipt_sha256=start_receipt.receipt_sha256,
            outcome=outcome.upper(),
            output_digests=outputs,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            receipt_sha256=canonical_sha(body),
        )


def _grant(
    worktree: Path,
    execution: EffectExecutionRequest,
    *,
    attempt_id: str = "attempt-claude-1",
    request_sha256: str = REQUEST_SHA,
    source_revision: str = REVISION,
) -> ClaudeWorkspaceGrant:
    return ClaudeWorkspaceGrant(
        attempt_id=attempt_id,
        source_revision=source_revision,
        request_sha256=request_sha256,
        execution_sha256=execution.digest,
        worktree=str(worktree),
    )


def test_public_provider_refuses_missing_authority_before_private_invocation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: called.append("invoked") or OUTPUT,
    )

    with pytest.raises(ClaudeProviderAuthorizationRequired):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
        )

    assert called == []


def test_exact_workspace_request_attempt_and_revision_are_required_before_grant(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    monkeypatch.setattr(claude_provider, "_invoke_claude_cli", lambda **kwargs: OUTPUT)
    execution = _execution(tmp_path)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="exact granted"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(other, execution),
        )
    assert auth.grant_calls == 0

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="different attempt"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(tmp_path, execution, attempt_id="attempt-other"),
        )
    assert auth.grant_calls == 0

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="source revision"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(
                tmp_path,
                execution,
                source_revision="f" * 40,
            ),
        )
    assert auth.grant_calls == 0

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="lease request"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(
                tmp_path,
                execution,
                request_sha256="e" * 64,
            ),
        )
    assert auth.grant_calls == 0


def test_execution_scope_must_honestly_cover_agentic_workspace_and_spend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    monkeypatch.setattr(claude_provider, "_invoke_claude_cli", lambda **kwargs: OUTPUT)

    narrowed = _execution(tmp_path, paths=["src/a.py"], writable_paths=("src",))
    with pytest.raises(ClaudeProviderScopeMismatch, match="worktree root"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=["src/a.py"],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=narrowed,
            workspace_grant=_grant(tmp_path, narrowed),
        )

    no_spend = _execution(tmp_path, max_cost_microusd=0)
    with pytest.raises(ClaudeProviderScopeMismatch, match="spend ceiling"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=no_spend,
            workspace_grant=_grant(tmp_path, no_spend),
        )
    assert auth.grant_calls == 0


def test_path_traversal_refuses_before_broker_or_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    called: list[str] = []
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: called.append("invoked") or OUTPUT,
    )
    execution = _execution(tmp_path)

    with pytest.raises(ClaudeProviderScopeMismatch, match="escapes"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=["../primary/secret.py"],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(tmp_path, execution),
        )
    assert called == []
    assert auth.grant_calls == 0


@pytest.mark.parametrize(
    ("changed_field", "value"),
    [
        ("objective", "different objective"),
        ("paths", ["different.py"]),
        ("model", "opus"),
        ("timeout_s", 301),
    ],
)
def test_invocation_change_cannot_reuse_execution_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    changed_field: str,
    value,
) -> None:
    auth = FakeAuthorization()
    called: list[str] = []
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: called.append("invoked") or OUTPUT,
    )
    objective = "review"
    paths: list[str] = []
    model = "sonnet"
    timeout_s = 300
    execution = _execution(
        tmp_path,
        objective=objective,
        paths=paths,
        model=model,
        timeout_s=timeout_s,
    )
    call = {
        "objective": objective,
        "paths": paths,
        "model": model,
        "timeout_s": timeout_s,
    }
    call[changed_field] = value

    with pytest.raises(ClaudeInvocationBindingMismatch, match="exact invocation"):
        ClaudeCLIProvider().run(
            objective=call["objective"],
            repo_root=str(tmp_path),
            paths=call["paths"],
            agent=_agent(),
            model=call["model"],
            timeout_s=call["timeout_s"],
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(tmp_path, execution),
        )
    assert called == []
    assert auth.grant_calls == 0


def test_brokered_provider_invokes_once_and_releases_only_after_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    calls: list[dict[str, object]] = []
    objective = "review exact diff"
    paths = ["src/a.py", "src/a.py"]
    normalized_paths = ["src/a.py"]
    execution = _execution(tmp_path, objective=objective, paths=normalized_paths)
    invocation_sha = _invocation_sha(
        tmp_path,
        objective=objective,
        paths=normalized_paths,
    )

    def invoke(**kwargs):
        calls.append(kwargs)
        return OUTPUT

    monkeypatch.setattr(claude_provider, "_invoke_claude_cli", invoke)
    result = ClaudeCLIProvider().run(
        objective=objective,
        repo_root=str(tmp_path),
        paths=paths,
        agent=_agent(),
        runtime_authorization=auth,  # type: ignore[arg-type]
        effect_execution=execution,
        workspace_grant=_grant(tmp_path, execution),
    )

    assert len(calls) == 1
    assert calls[0]["paths"] == normalized_paths
    assert auth.received_executions == [execution]
    assert auth.grant_calls == 1
    assert auth.begin_calls == 1
    assert auth.verify_calls == 2
    assert len(auth.finish_calls) == 1
    assert auth.finish_calls[0]["outcome"] == "completed"
    expected_output = canonical_sha(
        {
            "provider": "claude_cli",
            "agent": "reviewer",
            "invocation_sha256": invocation_sha,
            "prompt_sha256": OUTPUT["prompt_sha256"],
            "report_sha256": OUTPUT["report_sha256"],
            "report": OUTPUT["report"],
        }
    )
    assert auth.finish_calls[0]["output_digests"] == (expected_output,)
    assert result["provider"] == "claude_cli"
    assert result["report"] == OUTPUT["report"]
    assert result["runtime_receipt"]["executed"] is True
    assert result["runtime_receipt"]["invocation_sha256"] == invocation_sha
    assert result["runtime_receipt"]["terminal_receipt_sha256"] is not None


def test_report_digest_mismatch_fails_terminal_and_withholds_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    execution = _execution(tmp_path)
    malformed = {**OUTPUT, "report_sha256": "f" * 64}
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: malformed,
    )

    with pytest.raises(ValueError, match="report digest"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(tmp_path, execution),
        )
    assert auth.finish_calls[0]["outcome"] == "failed"


def test_exact_replay_is_inert_and_does_not_extract_output_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization(replay=True)
    calls: list[str] = []
    execution = _execution(tmp_path)
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: calls.append("invoked") or OUTPUT,
    )

    result = ClaudeCLIProvider().run(
        objective="review",
        repo_root=str(tmp_path),
        paths=[],
        agent=_agent(),
        runtime_authorization=auth,  # type: ignore[arg-type]
        effect_execution=execution,
        workspace_grant=_grant(tmp_path, execution),
    )

    assert calls == []
    assert result["replay"] is True
    assert result["runtime_receipt"]["executed"] is False
    assert auth.finish_calls == []


def test_legacy_bridge_name_is_fail_closed_without_runtime_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    called: list[str] = []
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: called.append("subprocess"),
    )

    with pytest.raises(ClaudeProviderAuthorizationRequired):
        bridge.ask_claude("review", str(tmp_path), [])

    assert called == []


def test_subprocess_effect_is_private_and_has_one_provider_caller() -> None:
    bridge_path = Path(bridge.__file__).resolve()
    provider_path = Path(claude_provider.__file__).resolve()
    bridge_tree = ast.parse(bridge_path.read_text(encoding="utf-8"))
    provider_tree = ast.parse(provider_path.read_text(encoding="utf-8"))

    subprocess_owners: list[str] = []
    for node in ast.walk(bridge_tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Attribute)
                and isinstance(child.func.value, ast.Name)
                and child.func.value.id == "subprocess"
                and child.func.attr == "run"
            ):
                subprocess_owners.append(node.name)
    assert subprocess_owners == ["_invoke_claude_cli"]

    private_calls = 0
    for node in ast.walk(provider_tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_invoke_claude_cli"
        ):
            private_calls += 1
    assert private_calls == 1


def test_noncentral_registry_still_refuses_provider_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization(wiring=Wiring.INVENTORY_ONLY)
    called: list[str] = []
    execution = _execution(tmp_path)
    monkeypatch.setattr(
        claude_provider,
        "_invoke_claude_cli",
        lambda **kwargs: called.append("invoked") or OUTPUT,
    )

    with pytest.raises(Exception, match="not centrally wired"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=execution,
            workspace_grant=_grant(tmp_path, execution),
        )
    assert called == []
    assert auth.grant_calls == 0
