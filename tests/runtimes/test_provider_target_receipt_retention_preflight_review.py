from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "daedalus" / "runtimes" / "provider_target_receipt_retention_preflight.py"


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _qualified_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _qualified_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_preflight_has_no_writer_process_network_or_provider_authority() -> None:
    tree = _tree()
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)

    forbidden_imports = {
        "sqlite3",
        "subprocess",
        "socket",
        "urllib",
        "requests",
        "httpx",
        "daedalus.runtimes.provider_target_receipt_ledger",
        "daedalus.kernel.effect_lease_ledger",
    }
    assert imported_modules.isdisjoint(forbidden_imports)

    forbidden_calls = {
        "open",
        "Path.write_bytes",
        "Path.write_text",
        "Path.unlink",
        "os.replace",
        "os.rename",
        "subprocess.run",
        "subprocess.Popen",
        "begin_effect",
        "grant",
        "finish",
        "retain",
        "put_bytes",
        "record_intent",
        "mark_completed",
        "run_runtime_provider",
        "promote_candidates",
    }
    calls = {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for name in [_qualified_name(node.func)]
        if name is not None
    }
    assert calls.isdisjoint(forbidden_calls)


def test_authority_authenticates_before_repository_observation() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_preflight",
    )
    positions: dict[str, list[int]] = {}
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        name = _qualified_name(node.func)
        if name is not None:
            positions.setdefault(name, []).append(node.lineno)

    assert len(positions["authorize_provider_target_receipt_retention_operation"]) == 1
    assert len(positions["verify_repository_head_revision_receipt"]) == 1
    assert len(positions["scan_provider_target_receipt_retention"]) == 1
    authority_line = positions[
        "authorize_provider_target_receipt_retention_operation"
    ][0]
    head_line = positions["verify_repository_head_revision_receipt"][0]
    inventory_line = positions["scan_provider_target_receipt_retention"][0]
    assert authority_line < head_line < inventory_line


def test_guard_decision_compares_exact_contract_allow_and_evidence() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_preflight",
    )
    comparisons = {
        ast.unparse(node)
        for node in ast.walk(function)
        if isinstance(node, ast.Compare)
    }
    assert "type(decision) is not GuardDecision" in comparisons
    assert "decision.contract != RETENTION_GUARD_CONTRACT" in comparisons
    assert "decision.allowed is not True" in comparisons
    assert "decision.evidence != expected_evidence" in comparisons


def test_preflight_receipt_permanently_refuses_effect_and_gate_claims() -> None:
    tree = _tree()
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ProviderTargetReceiptRetentionPreflightReceipt"
    ]
    assert len(classes) == 1
    methods = {
        node.name: node
        for node in classes[0].body
        if isinstance(node, ast.FunctionDef)
    }
    to_dict = methods["to_dict"]
    returns = [node for node in ast.walk(to_dict) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    payload = returns[0].value
    assert isinstance(payload, ast.Dict)
    constants = {
        key.value: value.value
        for key, value in zip(payload.keys, payload.values)
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
        and isinstance(value, ast.Constant)
    }
    assert constants["repository_head_reverified"] is True
    assert constants["retention_inventory_rebuilt"] is True
    assert constants["retention_authority_authenticated"] is True
    assert constants["guard_decision_allowed"] is True
    for field in (
        "provider_execution_allowed",
        "persisted_effect_lease_verified",
        "retention_effect_started",
        "retention_write_performed",
        "canonical_entrypoint_registered",
        "gate_transition_authorized",
        "closed",
    ):
        assert constants[field] is False


def test_public_api_accepts_no_ledger_callback_or_writer() -> None:
    function = _function(
        _tree(),
        "verify_provider_target_receipt_retention_preflight",
    )
    arguments = {
        argument.arg
        for argument in (
            *function.args.posonlyargs,
            *function.args.args,
            *function.args.kwonlyargs,
        )
    }
    forbidden = {
        "ledger",
        "spine",
        "source_store",
        "callback",
        "invoke",
        "writer",
        "begin_effect",
        "promotion",
        "owner_approval",
    }
    assert arguments.isdisjoint(forbidden)
    assert function.args.vararg is None
    assert function.args.kwarg is None
