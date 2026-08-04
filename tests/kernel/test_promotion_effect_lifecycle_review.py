from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus" / "kairos" / "promotion_effect_lifecycle.py"


def _function(name: str) -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def test_preauthorization_and_effect_start_precede_delegate() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    preauthorize = text.index("_preauthorize_exact_subject(", text.index("def promote_candidates_with_effect_lifecycle"))
    grant = text.index("promotion_effect_capability.grant()", preauthorize)
    begin = text.index("effect_begin = promotion_effect_capability.begin()", grant)
    delegate = text.index("gated_writes.promote_candidates(", begin)
    assert preauthorize < grant < begin < delegate


def test_pending_and_complete_restart_paths_return_before_delegate() -> None:
    function = _function("promote_candidates_with_effect_lifecycle")
    delegate_lines = [
        node.lineno
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func) == "gated_writes.promote_candidates"
    ]
    assert len(delegate_lines) == 1
    delegate_line = delegate_lines[0]
    source_lines = SOURCE.read_text(encoding="utf-8").splitlines()
    for marker in (
        "PromotionReconciliationDisposition.COMPLETE",
        "PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED",
        "PromotionReconciliationDisposition.EFFECT_ONLY_PENDING",
        "PromotionReconciliationDisposition.PROMOTION_PENDING",
    ):
        marker_lines = [
            index + 1 for index, line in enumerate(source_lines) if marker in line
        ]
        assert any(line < delegate_line for line in marker_lines)
    assert "Existing pending\n    starts return reconciliation state and never call promotion again" in SOURCE.read_text(encoding="utf-8")


def test_adapter_has_no_direct_git_worktree_or_approval_issuance_authority() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden_calls: list[str] = []
    allowed_effect_calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = ast.unparse(node.func)
        if target in {
            "subprocess.run",
            "subprocess.Popen",
            "issue_owner_approval",
            "verify_owner_approval",
            "promotion_effect_capability.finish",
            "promotion_effect_capability.authorization.effect_ledger.finish",
        }:
            forbidden_calls.append(target)
        if target in {
            "promotion_effect_capability.grant",
            "promotion_effect_capability.begin",
            "gated_writes.promote_candidates",
            "terminalize_promotion_effect",
        }:
            allowed_effect_calls.append(target)
    assert forbidden_calls == []
    assert allowed_effect_calls.count("promotion_effect_capability.grant") == 1
    assert allowed_effect_calls.count("promotion_effect_capability.begin") == 1
    assert allowed_effect_calls.count("gated_writes.promote_candidates") == 1
    assert allowed_effect_calls.count("terminalize_promotion_effect") == 2
    assert "GitWorktree" not in text
    assert "subprocess" not in text
    assert "OwnerApproval" not in text


def test_delegate_return_is_not_used_as_terminal_report_authority() -> None:
    function = _function("promote_candidates_with_effect_lifecycle")
    delegate_calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and ast.unparse(node.func) == "gated_writes.promote_candidates"
    ]
    assert len(delegate_calls) == 1
    parent = None
    for node in ast.walk(function):
        for child in ast.iter_child_nodes(node):
            if child is delegate_calls[0]:
                parent = node
                break
    assert isinstance(parent, ast.Expr)
    text = SOURCE.read_text(encoding="utf-8")
    assert "return promotion.completion.report_dict()" in text
    assert "_retained_report(terminalized.reconciliation)" in text


def test_status_never_claims_automatic_execution() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert '"automatic_execution_allowed": False' in text
    assert '"automatic_execution_allowed": True' not in text
    assert "automatic_execution_allowed=True" not in text
