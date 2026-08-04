from __future__ import annotations

import ast
import inspect

import daedalus.kernel.promotion_recovery_decision as decision


FORBIDDEN_CALLS = {
    "open",
    "sqlite3.connect",
    "subprocess.run",
    "subprocess.Popen",
    "GitWorktreeManager",
    "grant",
    "begin",
    "finish",
    "consume",
    "terminalize_promotion_effect",
    "promote_candidates",
    "issue_owner_approval",
    "issue_promotion_recovery_decision",
}
FORBIDDEN_PARAMETERS = {
    "callback",
    "provider",
    "writer",
    "outcome",
    "terminal_receipt",
    "repo_root",
    "expectation",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_recovery_decision_module_has_no_issuer_or_effect_authority() -> None:
    source = inspect.getsource(decision)
    tree = ast.parse(source)
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert not (set(filter(None, calls)) & FORBIDDEN_CALLS)
    assert all(
        not name.endswith(
            (
                ".grant",
                ".begin",
                ".finish",
                ".consume",
                ".promote_candidates",
            )
        )
        for name in filter(None, calls)
    )
    assert "issue_promotion_recovery_decision" not in vars(decision)
    assert "issue_owner_approval" not in vars(decision)


def test_public_functions_accept_no_smuggled_writer_or_expectation_authority() -> None:
    for function in (
        decision.recovery_expectation,
        decision.verify_promotion_recovery_decision,
    ):
        signature = inspect.signature(function)
        assert FORBIDDEN_PARAMETERS.isdisjoint(signature.parameters)
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )


def test_decision_contracts_expose_no_execution_methods() -> None:
    forbidden = {
        "execute",
        "begin",
        "finish",
        "grant",
        "consume",
        "promote",
        "cancel",
        "terminalize",
    }
    for contract in (
        decision.PromotionRecoveryDecision,
        decision.PromotionRecoveryExpectation,
        decision.VerifiedPromotionRecoveryDecision,
    ):
        assert forbidden.isdisjoint(vars(contract))


def test_exact_current_plan_and_authorization_are_revalidated_once() -> None:
    source = inspect.getsource(decision.recovery_expectation)
    tree = ast.parse(source)
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("plan_promotion_recovery") == 1
    assert calls.count("_verify_plan_digest") == 1
    assert calls.count("_promotion_authorization_digest") == 1
    assert all(
        not name.startswith("promotion_ledger.")
        for name in filter(None, calls)
    )
    assert "EFFECT_ONLY_PENDING" in source
    assert "OWNER_DECISION_BEFORE_EFFECT_CANCELLATION" in source
    assert "automatic_external_reexecution is not False" in source
    assert "owner_decision_required is not True" in source


def test_signature_and_time_checks_precede_current_state_projection() -> None:
    source = inspect.getsource(decision.verify_promotion_recovery_decision)
    signature_offset = source.index("hmac.compare_digest")
    time_offset = source.index("instant =")
    projection_offset = source.index("expectation = recovery_expectation")
    comparison_offset = source.index("comparisons =")

    assert signature_offset < time_offset < projection_offset < comparison_offset
