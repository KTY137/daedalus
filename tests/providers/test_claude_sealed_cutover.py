"""Regression guard for the Claude production cutover to the sealed broker."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

import daedalus.providers.claude_cli as claude_provider
from daedalus.providers.claude_cli import (
    ClaudeCLIProvider,
    ClaudeProviderAuthorizationRequired,
    ClaudeProviderScopeMismatch,
    claude_idempotency_key,
    claude_invocation_sha256,
)


SEALED_FIELDS = {
    "invocation_authority",
    "invocation_payload",
    "invocation_abi",
    "executable_registry",
    "pre_admission",
    "observation_binding_ledger",
}


def _provider_tree() -> ast.Module:
    source = Path(claude_provider.__file__).read_text(encoding="utf-8")
    return ast.parse(source)


def _invocation(tmp_path: Path, **changes: object) -> str:
    values: dict[str, object] = {
        "objective": "review exact diff",
        "worktree": str(tmp_path),
        "paths": ["src/ikarus.py"],
        "agent": {"name": "reviewer", "model_tier": "sonnet"},
        "model": "sonnet",
        "timeout_s": 300,
        "attempt_id": "attempt-claude-1",
        "source_revision": "a" * 40,
        "request_sha256": "b" * 64,
    }
    values.update(changes)
    return claude_invocation_sha256(**values)  # type: ignore[arg-type]


def test_claude_provider_exposes_only_complete_sealed_runtime_contract() -> None:
    parameters = inspect.signature(ClaudeCLIProvider.run).parameters

    assert SEALED_FIELDS <= set(parameters)
    assert "observation_authority" not in parameters
    for name in SEALED_FIELDS:
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_claude_provider_has_no_callback_broker_or_private_subprocess_call() -> None:
    tree = _provider_tree()
    imported_names: set[str] = set()
    calls: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.append(node.func.id)

    assert "run_runtime_provider" not in imported_names
    assert "_invoke_claude_cli" not in imported_names
    assert "run_runtime_provider" not in calls
    assert "_invoke_claude_cli" not in calls
    assert calls.count("run_sealed_runtime_provider") == 1


def test_missing_sealed_bundle_refuses_before_runtime_objects_are_touched() -> None:
    provider = ClaudeCLIProvider()

    with pytest.raises(
        ClaudeProviderAuthorizationRequired,
        match="complete sealed invocation bundle",
    ):
        provider.run(
            objective="review",
            repo_root="unused",
            paths=[],
            agent={"model_tier": "sonnet"},
            runtime_authorization=object(),  # type: ignore[arg-type]
            effect_execution=object(),  # type: ignore[arg-type]
            workspace_grant=object(),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("missing", sorted(SEALED_FIELDS))
def test_partial_sealed_bundle_is_fail_closed(missing: str) -> None:
    sealed = {name: object() for name in SEALED_FIELDS}
    sealed[missing] = None

    with pytest.raises(
        ClaudeProviderAuthorizationRequired,
        match="complete sealed invocation bundle",
    ):
        ClaudeCLIProvider().run(
            objective="review",
            repo_root="unused",
            paths=[],
            agent={"model_tier": "sonnet"},
            runtime_authorization=object(),  # type: ignore[arg-type]
            effect_execution=object(),  # type: ignore[arg-type]
            workspace_grant=object(),  # type: ignore[arg-type]
            **sealed,
        )


@pytest.mark.parametrize(
    "path",
    ["../primary/secret.py", "/etc/passwd", "C:/repo/file.py", "bad\x00path"],
)
def test_claude_path_scope_refuses_escape_or_ambiguous_paths(path: str) -> None:
    with pytest.raises(ClaudeProviderScopeMismatch):
        claude_provider._normalize_paths([path])


def test_claude_path_scope_is_canonical_and_deduplicated() -> None:
    assert claude_provider._normalize_paths(
        ["src\\ikarus.py", "src/ikarus.py", ".", "tests/test_ikarus.py"]
    ) == ["src/ikarus.py", "tests/test_ikarus.py"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("objective", "change implementation"),
        ("paths", ["src/other.py"]),
        ("agent", {"name": "implementer", "model_tier": "sonnet"}),
        ("model", "opus"),
        ("timeout_s", 301),
        ("attempt_id", "attempt-claude-2"),
        ("source_revision", "c" * 40),
        ("request_sha256", "d" * 64),
    ],
)
def test_claude_invocation_identity_changes_with_execution_semantics(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    baseline = _invocation(tmp_path)
    changed = _invocation(tmp_path, **{field: value})

    assert changed != baseline
    assert claude_idempotency_key(changed) != claude_idempotency_key(baseline)


def test_claude_invocation_identity_canonicalizes_worktree_and_paths(
    tmp_path: Path,
) -> None:
    first = _invocation(tmp_path, paths=["src\\ikarus.py", "src/ikarus.py"])
    second = _invocation(tmp_path, paths=["src/ikarus.py"])

    assert first == second
    assert claude_idempotency_key(first) == f"claude-{first}"
