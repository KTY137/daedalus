from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus/runtimes/recovery.py"
SOURCE = TARGET.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    rows = [
        node
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def test_public_recovery_signature_has_no_provider_or_retry_callback() -> None:
    function = _function("reconcile_runtime_provider_unknown")
    assert function.args.vararg is None
    assert function.args.kwarg is None
    names = [item.arg for item in function.args.args]
    names.extend(item.arg for item in function.args.kwonlyargs)
    assert names == [
        "entrypoint_id",
        "authorization",
        "execution",
        "start_receipt",
        "observation",
        "observation_keyring",
        "expected_provider_id",
        "expected_source_revision",
        "reconciled_at",
    ]
    assert not any(
        token in name
        for name in names
        for token in ("invoke", "provider_callback", "retry", "executor", "writer")
    )


def test_runtime_binding_is_verified_before_generic_reconciliation() -> None:
    function = _function("reconcile_runtime_provider_unknown")
    calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
    by_name: dict[str, list[int]] = {}
    for call in calls:
        by_name.setdefault(_call_name(call), []).append(call.lineno)
    assert len(by_name["_validate_runtime_binding"]) == 1
    assert len(by_name["reconcile_unknown_effect"]) == 1
    assert by_name["_validate_runtime_binding"][0] < by_name[
        "reconcile_unknown_effect"
    ][0]


def test_exact_runtime_lease_execution_and_revision_fences_remain() -> None:
    required = (
        '"request_entrypoint":',
        '"lease_entrypoint":',
        '"spec_runtime":',
        '"lease_runtime":',
        '"lease_sha256":',
        '"execution_id":',
        '"idempotency_key":',
        '"execution_request_sha256":',
        '"source_revision":',
        "if spec.wiring is not Wiring.CENTRAL:",
        "inspect_runtime_effect_execution(authorization, execution)",
    )
    for fence in required:
        assert fence in SOURCE


def test_authenticated_runtime_replay_must_be_pending_and_exact() -> None:
    function = _function("_validate_runtime_binding")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert "inspect_runtime_effect_execution(authorization, execution)" in text
    assert "type(replay) is not RuntimeEffectExecutionReplaySnapshot" in text
    assert "replay.execution.start_receipt != start_receipt" in text
    assert "not replay.pending_reconciliation" in text
    assert "already terminal" in text


def test_adapter_has_no_provider_process_network_or_promotion_authority() -> None:
    imported: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported.intersection(
        {"os", "shutil", "socket", "sqlite3", "subprocess", "tempfile"}
    )
    calls = {_call_name(node) for node in ast.walk(TREE) if isinstance(node, ast.Call)}
    assert not calls.intersection(
        {
            "invoke",
            "run_runtime_provider",
            "begin_effect",
            "finish_effect",
            "issue_effect_lease",
            "issue_runtime_bound_effect_lease",
            "promote_candidates",
            "Popen",
            "connect",
        }
    )
    assert calls.intersection(
        {"inspect_runtime_effect_execution", "reconcile_unknown_effect"}
    ) == {"inspect_runtime_effect_execution", "reconcile_unknown_effect"}


def test_replay_failures_are_wrapped_in_recovery_domain() -> None:
    function = _function("_validate_runtime_binding")
    handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 1
    text = ast.get_source_segment(SOURCE, handlers[0]) or ""
    assert "RuntimeEffectReplayProjectionError" in text
    assert "failed authenticated replay" in text


def test_exported_adapter_grants_no_automatic_reexecution() -> None:
    assert '"reconcile_runtime_provider_unknown"' in SOURCE
    assert "automatic" not in SOURCE.lower()
    assert "provider" not in {
        _call_name(node)
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call)
    }
