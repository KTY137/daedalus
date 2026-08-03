from __future__ import annotations

import ast
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "daedalus"
    / "orchestration"
    / "attempt_bindings.py"
)


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _calls(node: ast.AST) -> tuple[str, ...]:
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        target = child.func
        if isinstance(target, ast.Name):
            names.append(target.id)
        elif isinstance(target, ast.Attribute):
            names.append(target.attr)
    return tuple(names)


def test_module_is_a_contract_boundary_not_an_execution_or_state_store() -> None:
    tree = _tree()
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        (node.module or "").split(".", 1)[0]
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    )
    assert imported_roots.isdisjoint(
        {
            "sqlite3",
            "subprocess",
            "os",
            "shutil",
            "docker",
            "requests",
            "socket",
        }
    )
    forbidden_calls = {
        "run",
        "Popen",
        "connect",
        "execute",
        "commit",
        "consume",
        "promote_candidates",
        "issue_owner_approval",
        "issue_effect_lease",
    }
    assert forbidden_calls.isdisjoint(_calls(tree))


def test_consumer_rebuilds_contracts_and_uses_caller_owned_authorities() -> None:
    function = _function("verify_renovation_attempt_plan")
    argument_names = tuple(argument.arg for argument in function.args.kwonlyargs)
    assert "renovation_plan" in argument_names
    assert "mission" in argument_names
    assert "base_snapshot" in argument_names
    assert "expected_runtime_manifest_sha256" in argument_names
    assert "expected_policy_decision_sha256" in argument_names
    calls = _calls(function)
    assert "from_dict" in calls
    assert "verify_renovation_plan" in calls
    assert "_canonical_rebuild_attempt" in calls
    assert "renovation_replay_key" in calls


def test_replay_identity_binds_all_four_required_dimensions() -> None:
    function = _function("renovation_replay_key")
    literals = {
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert {
        "renovation_plan_sha256",
        "work_item_sha256",
        "attempt_sha256",
        "sequence",
    }.issubset(literals)


def test_assembler_reverifies_before_returning() -> None:
    function = _function("assemble_renovation_attempt_plan")
    calls = _calls(function)
    assert calls.count("verify_renovation_plan") == 1
    assert calls.count("verify_renovation_attempt_plan") == 1
    returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    assert isinstance(returns[0].value, ast.Call)
    target = returns[0].value.func
    assert isinstance(target, ast.Name)
    assert target.id == "verify_renovation_attempt_plan"


def test_untrusted_parser_requires_complete_canonical_wire_equality() -> None:
    function = _function("parse_renovation_attempt_plan")
    comparisons = [node for node in ast.walk(function) if isinstance(node, ast.Compare)]
    assert any(
        any(isinstance(operator, ast.NotEq) for operator in comparison.ops)
        for comparison in comparisons
    )
    calls = _calls(function)
    assert "from_dict" in calls
    assert "to_dict" in calls


def test_contract_vocabulary_contains_no_false_restart_or_promotion_receipt() -> None:
    tree = _tree()
    class_names = {
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    }
    assert class_names == {
        "RenovationAttemptBindingError",
        "RenovationAttemptBinding",
        "RenovationAttemptPlan",
    }
    source = SOURCE.read_text(encoding="utf-8")
    assert "PromotionReceipt" not in source
    assert "OwnerApproval" not in source
    assert "AttemptStartedReceipt" not in source
    assert "RestartReceipt" not in source
