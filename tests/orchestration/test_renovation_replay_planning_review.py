from __future__ import annotations

import ast
from pathlib import Path

MODULE = (
    Path(__file__).resolve().parents[2]
    / "daedalus"
    / "orchestration"
    / "replay_planning.py"
)


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def test_replay_planner_contains_no_execution_or_persistence_authority() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden_imports = {
        "sqlite3",
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "docker",
        "shutil",
        "tempfile",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not (imported & forbidden_imports)

    forbidden_fragments = (
        "promote_candidates",
        "OwnerApproval",
        "PromotionReceipt",
        "EffectLease",
        "os.system",
        "subprocess.",
        "sqlite3.",
        "create_worktree",
        "materialize",
    )
    for fragment in forbidden_fragments:
        assert fragment not in source


def test_dependency_fence_and_unknown_outcome_reconciliation_are_explicit() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert (
        'second_observation.state != "not-started" '
        'and first_observation.state != "succeeded"'
    ) in source
    assert 'observation.state in {"started", "unknown"}' in source
    assert 'action = "reconcile"' in source
    assert 'action = "execute" if dependency_satisfied else "blocked-dependency"' in source


def test_consumer_recomputes_parent_authority_and_complete_decision_plan() -> None:
    tree = _tree()
    verify = _function(tree, "verify_renovation_replay_plan")
    calls = {
        node.func.id
        for node in ast.walk(verify)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "verify_renovation_attempt_plan" in calls
    assert "_derive_replay_plan" in calls

    comparisons = [
        node
        for node in ast.walk(verify)
        if isinstance(node, ast.Compare)
    ]
    assert any(
        any(isinstance(op, ast.NotEq) for op in node.ops)
        and any(
            isinstance(part, ast.Name) and part.id == "expected"
            for part in (node.left, *node.comparators)
        )
        for node in comparisons
    )


def test_observation_and_plan_parsers_require_complete_canonical_wire() -> None:
    source = MODULE.read_text(encoding="utf-8")
    assert 'dict(payload) != value.to_dict()' in source
    assert "object_pairs_hook=_reject_duplicate_keys" in source
    assert source.count("wire is not canonical") >= 2
