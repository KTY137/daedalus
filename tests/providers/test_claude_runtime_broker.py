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
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    ClaudeProviderWorkspaceMismatch,
    ClaudeWorkspaceGrant,
)
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_sha


ENTRYPOINT = "provider.claude"
RUNTIME = "claude_code_cli"
REVISION = "a" * 40
REQUEST_SHA = "d" * 64
OUTPUT = {
    "agent": "reviewer",
    "prompt_sha256": "b" * 64,
    "report_sha256": "c" * 64,
    "report": {
        "status": "needs_review",
        "summary": "bounded review",
        "files_changed": [],
        "tests_run": [],
        "risks": [],
        "todos": [],
        "handoff": {},
    },
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


def _execution(**changes) -> EffectExecutionRequest:
    values = dict(
        execution_id="claude-execution-1",
        idempotency_key="claude-idempotency-1",
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


def _start_receipt() -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "1" * 64,
        "execution_id": "claude-execution-1",
        "idempotency_key": "claude-idempotency-1",
        "execution_request_sha256": "2" * 64,
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
        self.finish_calls: list[dict[str, object]] = []

    def grant(self) -> None:
        self.grant_calls += 1

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        self.begin_calls += 1
        assert execution == _execution()
        return EffectStartResult(
            receipt=_start_receipt(),
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
    *,
    attempt_id: str = "attempt-claude-1",
    request_sha256: str = REQUEST_SHA,
    execution: EffectExecutionRequest | None = None,
) -> ClaudeWorkspaceGrant:
    selected = execution or _execution()
    return ClaudeWorkspaceGrant(
        attempt_id=attempt_id,
        source_revision=REVISION,
        request_sha256=request_sha256,
        execution_sha256=selected.digest,
        worktree=str(worktree),
    )


def _agent() -> dict[str, object]:
    return {
        "name": "reviewer",
        "call_name": "Mary",
        "model_tier": "sonnet",
        "must_read": [],
    }


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
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="exact granted"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=_execution(),
            workspace_grant=_grant(other),
        )
    assert auth.grant_calls == 0

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="different attempt"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=_execution(),
            workspace_grant=_grant(tmp_path, attempt_id="attempt-other"),
        )
    assert auth.grant_calls == 0

    with pytest.raises(ClaudeProviderWorkspaceMismatch, match="lease request"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=_execution(),
            workspace_grant=_grant(tmp_path, request_sha256="e" * 64),
        )
    assert auth.grant_calls == 0


def test_execution_scope_must_honestly_cover_agentic_workspace_and_spend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    monkeypatch.setattr(claude_provider, "_invoke_claude_cli", lambda **kwargs: OUTPUT)

    narrowed = _execution(writable_paths=("src",))
    with pytest.raises(ClaudeProviderScopeMismatch, match="worktree root"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=["src/a.py"],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=narrowed,
            workspace_grant=_grant(tmp_path, execution=narrowed),
        )

    no_spend = _execution(max_cost_microusd=0)
    with pytest.raises(ClaudeProviderScopeMismatch, match="spend ceiling"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=[],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=no_spend,
            workspace_grant=_grant(tmp_path, execution=no_spend),
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

    with pytest.raises(ClaudeProviderScopeMismatch, match="escapes"):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root=str(tmp_path),
            paths=["../primary/secret.py"],
            agent=_agent(),
            runtime_authorization=auth,  # type: ignore[arg-type]
            effect_execution=_execution(),
            workspace_grant=_grant(tmp_path),
        )
    assert called == []
    assert auth.grant_calls == 0


def test_brokered_provider_invokes_once_and_releases_only_after_terminal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization()
    calls: list[dict[str, object]] = []

    def invoke(**kwargs):
        calls.append(kwargs)
        return OUTPUT

    monkeypatch.setattr(claude_provider, "_invoke_claude_cli", invoke)
    result = ClaudeCLIProvider().run(
        objective="review exact diff",
        repo_root=str(tmp_path),
        paths=["src/a.py", "src/a.py"],
        agent=_agent(),
        runtime_authorization=auth,  # type: ignore[arg-type]
        effect_execution=_execution(),
        workspace_grant=_grant(tmp_path),
    )

    assert len(calls) == 1
    assert calls[0]["paths"] == ["src/a.py"]
    assert auth.grant_calls == 1
    assert auth.begin_calls == 1
    assert auth.verify_calls == 2
    assert len(auth.finish_calls) == 1
    assert auth.finish_calls[0]["outcome"] == "completed"
    expected_output = canonical_sha(
        {
            "provider": "claude_cli",
            "agent": "reviewer",
            "report": OUTPUT["report"],
        }
    )
    assert auth.finish_calls[0]["output_digests"] == (expected_output,)
    assert result["provider"] == "claude_cli"
    assert result["report"] == OUTPUT["report"]
    assert result["runtime_receipt"]["executed"] is True
    assert result["runtime_receipt"]["terminal_receipt_sha256"] is not None


def test_exact_replay_is_inert_and_does_not_extract_output_again(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    auth = FakeAuthorization(replay=True)
    calls: list[str] = []
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
        effect_execution=_execution(),
        workspace_grant=_grant(tmp_path),
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
            effect_execution=_execution(),
            workspace_grant=_grant(tmp_path),
        )
    assert called == []
    assert auth.grant_calls == 0
