from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_inventory.py"


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _segment(source: str, node: ast.AST) -> str:
    value = ast.get_source_segment(source, node)
    assert value is not None
    return value


def test_counter_review_confirms_read_only_authority_boundary() -> None:
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET))
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "subprocess" not in imports
    assert "sqlite3" not in imports
    assert "daedalus.kernel.approvals" not in imported_from
    assert "daedalus.kernel.effects" not in imported_from
    assert "daedalus.kairos.gated_writes" not in imported_from


def test_counter_review_requires_all_three_exact_promotion_rows() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert source.count("PromotionEffectRequirement(") == 3
    for entrypoint_id in (
        "python.promote_candidates",
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    ):
        assert source.count(f'entrypoint_id="{entrypoint_id}"') == 1
    assert source.count("wiring is not Wiring.CENTRAL") == 1
    assert source.count("registry.missing") == 1
    assert source.count("registry.target_mismatch") == 1
    assert source.count("registry.effects_mismatch") == 1
    assert source.count("registry.guards_mismatch") == 1


def test_counter_review_derives_closed_and_rebuilds_live_state() -> None:
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET))
    builder = _segment(source, _function(tree, "build_promotion_effect_inventory"))
    verifier = _segment(source, _function(tree, "verify_promotion_effect_inventory"))
    assert 'closed = all(finding.status == "central" for finding in findings)' in builder
    assert "report.closed" not in builder
    assert "build_promotion_effect_inventory(" in verifier
    assert "if rebuilt != report" in verifier


def test_counter_review_binds_source_bytes_before_ast_claims() -> None:
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET))
    loader = _segment(source, _function(tree, "_source_bytes"))
    anchors = _segment(source, _function(tree, "_source_blockers"))
    assert "resolve(strict=True)" in loader
    assert "relative_to(resolved_root)" in loader
    assert "is_symlink()" in loader
    assert "read_bytes()" in loader
    assert "payload.decode(\"utf-8\")" in loader
    assert "_sha256_bytes(payload)" in anchors
    assert "ast.parse" in anchors
