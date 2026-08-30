# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_execution.py"


def _source() -> str:
    return TARGET.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(TARGET))


def _calls(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for item in ast.walk(node):
        if not isinstance(item, ast.Call):
            continue
        current = item.func
        parts: list[str] = []
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
            names.add(".".join(reversed(parts)))
    return names


def _method(tree: ast.Module, class_name: str, method_name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == method_name:
                    return child
    raise AssertionError(f"missing {class_name}.{method_name}")


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _segment(node: ast.AST) -> str:
    segment = ast.get_source_segment(_source(), node)
    assert segment is not None
    return segment


def test_execution_accounting_does_not_create_a_second_owner_receipt_authority() -> None:
    tree = _tree()
    class_names = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    assert "PromotionReceipt" not in class_names
    assert "OwnerApproval" not in class_names
    assert {
        "PromotionExecutionStart",
        "PromotionExecutionReceipt",
        "PromotionExecutionLedger",
    } <= class_names


def test_module_has_no_git_provider_worktree_or_promotion_side_effect() -> None:
    tree = _tree()
    imported: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_import_prefixes = (
        "subprocess",
        "daedalus.kairos",
        "daedalus.providers",
        "daedalus.adapters",
        "daedalus.kernel.approvals",
    )
    assert not any(
        name == prefix or name.startswith(prefix + ".")
        for name in imported
        for prefix in forbidden_import_prefixes
    )
    calls = _calls(tree)
    assert "sqlite3.connect" not in calls
    assert "subprocess.run" not in calls
    assert "os.replace" not in calls
    assert "Path.write_bytes" not in calls
    assert "Path.write_text" not in calls


def test_begin_commits_canonical_event_store_intent() -> None:
    tree = _tree()
    begin = _method(tree, "PromotionExecutionLedger", "begin")
    source = _segment(begin)
    assert ".record_intent(" in source
    assert ".mark_completed(" not in source
    assert "_authorization_payload(authorization)" in source
    assert "primary_checkout_before_sha256" in source
    assert "effect_key=_effect_key(start.promotion_id)" in source


def test_complete_rebinds_start_and_appends_one_terminal_event() -> None:
    tree = _tree()
    complete = _method(tree, "PromotionExecutionLedger", "complete")
    source = _segment(complete)
    assert ".mark_completed(" in source
    assert ".record_intent(" not in source
    assert "persisted_start != start" in source
    assert "primary_checkout_after_sha256" in source
    assert "report_sha" in source
    assert "IntentAlreadyResolved" in source


def test_shared_event_store_and_gate0_durability_are_mandatory() -> None:
    source = _source()
    assert "open_gate0_spine_writer" in source
    assert "enforce_gate0_durability" in source
    assert "SpineLedger" in source
    assert "idx_promotion_execution_effect_key" in source
    assert "WHERE kind = 'promotion.execution'" in source
    assert "CREATE TABLE" not in source


def test_report_validation_binds_authorization_integration_and_primary_checkout() -> None:
    tree = _tree()
    validator = _function(tree, "_validate_report")
    source = _segment(validator)
    for required in (
        'canonical.get("authorization") != expected_authorization',
        'canonical.get("integration_branch") != integration_branch',
        'canonical.get("integration_revision") != integration_revision',
        "primary_checkout_before_sha256",
        'outcome == "succeeded"',
        'outcome == "refused"',
        'outcome == "faulted"',
    ):
        assert required in source


def test_json_boundary_is_strict_frozen_bounded_and_uncoerced() -> None:
    tree = _tree()
    source = _source()
    assert "_MAX_REPORT_BYTES = 4 * 1024 * 1024" in source
    freezer = _segment(_function(tree, "_freeze_json"))
    assert "math.isfinite" in freezer
    assert "non-string object key" in freezer
    assert "non-JSON value" in freezer
    canonicalizer = _segment(_function(tree, "_canonical_object"))
    assert "_freeze_json(value, label)" in canonicalizer
    assert "parse_constant=" in canonicalizer
    assert "parsed != decoded" in canonicalizer
    completion = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "PromotionExecutionCompletion"
    )
    assert '_freeze_json(canonical, "promotion execution report")' in _segment(
        completion
    )


def test_retained_report_is_revalidated_on_every_read() -> None:
    decode = _method(_tree(), "PromotionExecutionLedger", "_decode_completion")
    segment = _segment(decode)
    assert "promotion completion precedes persisted start" in segment
    assert "_validate_report(" in segment
    assert "persisted promotion report contradicts terminal receipt" in segment


def test_no_gate_or_owner_claim_is_embedded_in_production_contract() -> None:
    source = _source().lower()
    assert "closed=true" not in source
    assert "gate 0 is closed" not in source
    assert "issue_owner_approval" not in source
    assert "promote_candidates(" not in source
    assert "merge_pull_request" not in source
