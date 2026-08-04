from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus" / "spine" / "promotion_effect_rows.py"


def _source() -> str:
    return TARGET.read_text(encoding="utf-8")


def _tree() -> ast.Module:
    return ast.parse(_source(), filename=str(TARGET))


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _segment(node: ast.AST) -> str:
    value = ast.get_source_segment(_source(), node)
    assert value is not None
    return value


def test_counter_review_confirms_no_canonical_registry_import_or_mutation() -> None:
    tree = _tree()
    imported_modules = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert "daedalus.spine.effect_boundary" not in imported_modules
    source = _source().lower()
    assert "entrypoints" not in source
    assert "registry_by_id" not in source
    assert "build_gate_report" not in source


def test_counter_review_requires_exact_three_descriptor_literals() -> None:
    source = _source()
    assert source.count("PromotionExecutionRowDescriptor(") == 3
    for identity in (
        "kernel.promotion_execution.open",
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    ):
        assert source.count(f'entrypoint_id="{identity}"') == 1
    assert source.count('wiring="local_guards"') == 3
    assert source.count('effects=("filesystem_write",)') == 3
    assert source.count('guard_contracts=("spine.intent_ledger",)') == 3
    assert 'wiring="central"' not in source


def test_counter_review_materializer_is_dependency_injected_and_pure() -> None:
    materializer = _segment(_function("materialize_promotion_execution_rows"))
    assert "entrypoint_spec: Callable" in materializer
    assert "surface_values: Mapping" in materializer
    assert "effect_values: Mapping" in materializer
    assert "wiring_values: Mapping" in materializer
    assert "_assert_descriptor_set(descriptors)" in materializer
    assert "rows.append(" in materializer
    assert "return tuple(rows)" in materializer
    for forbidden in (
        "global ",
        "ENTRYPOINTS",
        "REGISTRY_BY_ID",
        "subprocess",
        "sqlite3",
        "write_text",
        "write_bytes",
    ):
        assert forbidden not in materializer


def test_counter_review_rejects_central_or_widened_descriptor_contracts() -> None:
    validator = next(
        node
        for node in _tree().body
        if isinstance(node, ast.ClassDef)
        and node.name == "PromotionExecutionRowDescriptor"
    )
    post_init = next(
        node
        for node in validator.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = _segment(post_init)
    assert 'self.effects != ("filesystem_write",)' in source
    assert 'self.guard_contracts != ("spine.intent_ledger",)' in source
    assert 'self.wiring != "local_guards"' in source
    assert "EffectLease, runtime conformance and sandbox composition" in source
