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
