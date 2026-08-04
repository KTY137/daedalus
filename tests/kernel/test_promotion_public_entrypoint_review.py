from __future__ import annotations

import ast
import inspect

import daedalus.kairos.promotion_entrypoint as entrypoint


FORBIDDEN_NAMES = {
    "subprocess",
    "sqlite3",
    "GitWorktreeManager",
    "PromotionExecutionLedger.begin",
    "PromotionExecutionLedger.complete",
    "authorize_persisted_promotion",
    "issue_owner_approval",
    "consume_owner_approval",
    "merge",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_entrypoint_has_one_lifecycle_call_and_no_lower_authority() -> None:
    source = inspect.getsource(entrypoint)
    tree = ast.parse(source)
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    signature = inspect.signature(entrypoint.promote_candidates)

    assert calls.count("promote_candidates_with_effect_lifecycle") == 1
    assert not (set(filter(None, calls)) & FORBIDDEN_NAMES)
    assert "callback" not in signature.parameters
    assert "provider" not in signature.parameters
    assert "outcome" not in signature.parameters
    assert "terminal_receipt" not in signature.parameters


def test_entrypoint_imports_only_typed_contracts_and_lifecycle() -> None:
    tree = ast.parse(inspect.getsource(entrypoint))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert imports <= {
        "__future__",
        "typing",
        "daedalus.kernel.promotion_effects",
        "daedalus.kernel.promotion_execution",
        "promotion_effect_lifecycle",
    }
