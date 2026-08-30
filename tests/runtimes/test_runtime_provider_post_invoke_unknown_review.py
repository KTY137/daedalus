from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BROKER = ROOT / "daedalus/runtimes/broker.py"
SOURCE = BROKER.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _function(name: str) -> ast.FunctionDef:
    rows = [
        node
        for node in TREE.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _class(name: str) -> ast.ClassDef:
    rows = [
        node
        for node in TREE.body
        if isinstance(node, ast.ClassDef) and node.name == name
    ]
    assert len(rows) == 1
    return rows[0]


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _output_evidence_handler() -> ast.ExceptHandler:
    function = _function("run_runtime_provider")
    for node in function.body:
        if not isinstance(node, ast.Try):
            continue
        segment = ast.get_source_segment(SOURCE, node) or ""
        if "_normalize_output_digests(raw_digests)" in segment:
            assert len(node.handlers) == 1
            return node.handlers[0]
    raise AssertionError("output-evidence handler is missing")


def test_output_evidence_failure_has_no_terminal_writer_call() -> None:
    handler = _output_evidence_handler()
    calls = {
        _call_name(node)
        for node in ast.walk(handler)
        if isinstance(node, ast.Call)
    }
    assert "RuntimeProviderReconciliationRequired" in calls
    assert not calls.intersection(
        {
            "finish_effect",
            "_finish_or_raise_state",
            "_cancel_for_trust_loss",
            "begin_effect",
            "grant",
            "reconcile_unknown_effect",
        }
    )


def test_unknown_outcome_exception_binds_only_safe_recovery_material() -> None:
    node = _class("RuntimeProviderReconciliationRequired")
    fields = {
        target.attr
        for item in ast.walk(node)
        if isinstance(item, ast.Assign)
        for target in item.targets
        if isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    }
    assert fields == {
        "entrypoint_id",
        "runtime_id",
        "start_receipt",
        "phase",
        "cause_sha256",
    }
    class_text = ast.get_source_segment(SOURCE, node) or ""
    assert "self.value" not in class_text
    assert "self.provider_value" not in class_text
    assert "str(" not in class_text
    assert "repr(" not in class_text


def test_exception_cause_is_class_digest_not_retained_message() -> None:
    handler = _output_evidence_handler()
    text = ast.get_source_segment(SOURCE, handler) or ""
    assert 'cause_sha256=_exception_detail("output-evidence", exc)' in text
    assert "from exc" in text
    assert "str(exc)" not in text
    assert "repr(exc)" not in text


def test_exact_replay_returns_before_sealed_provider_or_evidence_operation() -> None:
    function = _function("run_runtime_provider")
    lines: dict[str, list[int]] = {}
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            lines.setdefault(_call_name(node), []).append(node.lineno)
    replay_ifs = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.If)
        and "not start.execute" in (ast.get_source_segment(SOURCE, node.test) or "")
    ]
    assert len(replay_ifs) == 1
    returns = [node.lineno for node in ast.walk(replay_ifs[0]) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert returns[0] < min(lines["_execute_sealed_operation"])
    assert returns[0] < min(lines["_normalize_output_digests"])


def test_old_post_provider_failed_terminal_branch_is_absent() -> None:
    handler = _output_evidence_handler()
    text = ast.get_source_segment(SOURCE, handler) or ""
    assert 'outcome="failed"' not in text
    assert 'detail_sha256=_exception_detail("output-evidence", exc)' not in text
    assert "authenticated reconciliation is required" in SOURCE


def test_new_exception_is_public_but_grants_no_recovery_authority() -> None:
    assert '"RuntimeProviderReconciliationRequired"' in SOURCE
    node = _class("RuntimeProviderReconciliationRequired")
    methods = {
        child.name
        for child in node.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__init__"}
    assert not methods.intersection(
        {"execute", "finish", "reconcile", "retry", "invoke", "promote"}
    )
