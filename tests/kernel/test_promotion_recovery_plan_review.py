from __future__ import annotations

import ast
import inspect

import daedalus.kernel.promotion_recovery as recovery


FORBIDDEN_CALLS = {
    "grant",
    "begin",
    "finish",
    "terminalize_promotion_effect",
    "promote_candidates",
    "sqlite3.connect",
    "subprocess.run",
    "subprocess.Popen",
    "GitWorktreeManager",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_recovery_projection_is_read_only_and_has_one_state_authority() -> None:
    tree = ast.parse(inspect.getsource(recovery))
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("inspect_promotion_reconciliation") == 1
    assert not (set(filter(None, calls)) & FORBIDDEN_CALLS)
    assert all(
        not name.endswith((".grant", ".begin", ".finish", ".promote_candidates"))
        for name in filter(None, calls)
    )


def test_every_reconciliation_disposition_has_one_operator_action() -> None:
    assert set(recovery._ACTION_BY_DISPOSITION) == set(
        recovery.PromotionReconciliationDisposition
    )
    assert len(set(recovery._ACTION_BY_DISPOSITION.values())) == len(
        recovery._ACTION_BY_DISPOSITION
    )


def test_plan_contract_cannot_expose_execution_methods() -> None:
    forbidden = {"execute", "begin", "finish", "grant", "promote", "cancel"}
    assert forbidden.isdisjoint(vars(recovery.PromotionRecoveryPlan))
    assert forbidden.isdisjoint(vars(recovery.PromotionRecoveryAction))
