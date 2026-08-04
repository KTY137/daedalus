from __future__ import annotations

import ast
from pathlib import Path

from daedalus.spine.promotion_recovery_consumption_store_inventory import (
    BASE_REVISION,
    BLOCKERS,
    ENTRYPOINTS,
    INVENTORY_DELTA,
)


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    ROOT
    / "daedalus"
    / "spine"
    / "promotion_recovery_consumption_store_inventory.py"
)


def _tree() -> ast.Module:
    return ast.parse(INVENTORY_PATH.read_text(encoding="utf-8"))


def _qualified_imports(tree: ast.Module) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            imports.update(
                f"{prefix}.{alias.name}" if prefix else alias.name
                for alias in node.names
            )
    return imports


def test_inventory_module_has_no_effect_or_registry_authority() -> None:
    tree = _tree()
    imports = _qualified_imports(tree)
    forbidden = {
        "sqlite3",
        "subprocess",
        "os",
        "tempfile",
        "daedalus.spine.effect_boundary",
        "daedalus.kernel.promotion_recovery_consumption_store",
    }
    assert imports.isdisjoint(forbidden)

    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert calls.isdisjoint(
        {
            "begin_effect",
            "initialize_promotion_recovery_consumption_store",
            "install_promotion_recovery_consumption_inventory",
        }
    )

    assigned_attributes = {
        node.targets[0].attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Attribute)
    }
    assert assigned_attributes.isdisjoint(
        {"ENTRYPOINTS", "REGISTRY_BY_ID", "_surface_for_function"}
    )


def test_inventory_cannot_claim_centrality_or_closure() -> None:
    assert INVENTORY_DELTA.source_revision == BASE_REVISION
    assert INVENTORY_DELTA.closed is False
    assert INVENTORY_DELTA.canonical_registry_integrated is False
    assert INVENTORY_DELTA.canonical_scanner_integrated is False
    assert len(ENTRYPOINTS) == 1
    row = ENTRYPOINTS[0]
    assert row.wiring == "unguarded"
    assert row.guard_contracts == ()
    assert "central" not in row.wiring


def test_blockers_cover_registration_scanning_authority_and_migration() -> None:
    assert BLOCKERS == (
        "canonical-effect-boundary-entrypoint-row-not-yet-integrated",
        "static-effect-scanner-does-not-yet-classify-explicit-store-initializer",
        "explicit-store-initializer-remains-unguarded",
        "initializer-not-bound-to-persisted-effect-lease",
        "initializer-not-bound-to-runtime-conformance-kill-switch-or-docker-sandbox",
        "production-callers-not-yet-migrated-to-preprovisioned-store",
        "legacy-auto-initializing-constructor-remains-production-visible",
    )


def test_revision_fence_uses_exact_equality_against_the_frozen_parent() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name
        == "build_promotion_recovery_consumption_store_inventory_delta"
    )
    stale_comparisons = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Compare)
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.NotEq)
        and isinstance(node.left, ast.Name)
        and node.left.id == "source_revision"
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and node.comparators[0].id == "BASE_REVISION"
    ]
    assert len(stale_comparisons) == 1
    assert len(BASE_REVISION) == 40
    assert BASE_REVISION == BASE_REVISION.lower()


def test_scanner_contract_uses_exact_equality_not_prefix_or_substring_matching() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "recognizes_recovery_consumption_store_initializer"
    )
    comparisons = [node for node in ast.walk(function) if isinstance(node, ast.Compare)]
    assert len(comparisons) == 2
    assert all(
        len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq)
        for node in comparisons
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"startswith", "endswith"}
        for node in ast.walk(function)
    )


def test_inventory_exports_are_bounded() -> None:
    tree = _tree()
    export_assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    assert isinstance(export_assignment.value, (ast.List, ast.Tuple))
    exports = {
        element.value
        for element in export_assignment.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert "effect_boundary" not in exports
    assert "initialize_promotion_recovery_consumption_store" not in exports
    assert "install" not in exports
