from __future__ import annotations

import ast
from pathlib import Path


MODULE = Path("daedalus/kernel/promotion_terminalization.py")


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def test_terminalization_module_has_one_narrow_writer_seam():
    tree = _tree()
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    finish_calls = [
        node
        for node in calls
        if isinstance(node.func, ast.Attribute) and node.func.attr == "finish"
    ]
    assert len(finish_calls) == 1
    rendered = ast.unparse(finish_calls[0].func)
    assert rendered == "capability.authorization.effect_ledger.finish"


def test_terminalization_module_cannot_begin_or_authorize_an_effect():
    tree = _tree()
    forbidden_attributes = {
        "begin",
        "begin_effect",
        "grant",
        "verify",
        "revoke",
        "issue_effect_lease",
        "promote_candidates",
        "complete",
    }
    observed = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes
    }
    assert observed == set()


def test_terminalization_module_imports_no_effect_runtime_or_repository_tools():
    tree = _tree()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden_fragments = (
        "subprocess",
        "docker",
        "worktree",
        "kairos.gated_writes",
        "runtime_effects",
        "sandbox",
        "providers",
    )
    assert not any(
        fragment in module
        for fragment in forbidden_fragments
        for module in imported
    )


def test_write_material_is_derived_only_from_strict_projection():
    source = MODULE.read_text(encoding="utf-8")
    assert "expected = projection.expected_effect_terminal" in source
    assert "outcome=expected.outcome" in source
    assert "output_digests=expected.output_digests" in source
    assert "detail_sha256=expected.detail_sha256" in source
    assert "inspect_promotion_reconciliation(capability, promotion_ledger)" in source
    assert "current_kill_switch_generation" not in source
    assert "lease_keyring" not in source
