from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.spine.promotion_recovery_consumption_inventory as inventory


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_IMPORTS = {
    "daedalus.spine.effect_boundary",
    "sqlite3",
    "subprocess",
}
FORBIDDEN_CALLS = {
    "open",
    "setattr",
    "delattr",
    "append",
    "extend",
    "write_text",
    "write_bytes",
    "mkdir",
    "unlink",
    "replace",
    "sqlite3.connect",
    "subprocess.run",
    "subprocess.Popen",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_inventory_delta_module_is_pure_and_cannot_patch_canonical_registry() -> None:
    source = inspect.getsource(inventory)
    tree = ast.parse(source)
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    calls = {
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }

    assert FORBIDDEN_IMPORTS.isdisjoint(imports)
    assert FORBIDDEN_CALLS.isdisjoint(set(filter(None, calls)))
    assert "ENTRYPOINTS.append" not in source
    assert "GUARD_CONTRACT_IMPLEMENTED.update" not in source
    assert "canonical_registry_integrated=False" in source
    assert "closed=False" in source


def test_inventory_delta_contains_no_false_central_or_closed_claim() -> None:
    wire = inventory.INVENTORY_DELTA.to_dict()

    assert wire["canonical_registry_integrated"] is False
    assert wire["closed"] is False
    assert wire["blockers"]
    assert all(row.wiring != "central" for row in inventory.ENTRYPOINTS)
    assert inventory.ENTRYPOINTS[0].wiring == "unguarded"
    assert inventory.ENTRYPOINTS[0].guard_contracts == ()
    assert inventory.ENTRYPOINTS[1].wiring == "local_guards"


def test_every_declared_target_resolves_without_importing_target_module() -> None:
    for row in inventory.ENTRYPOINTS:
        module, qualname = row.target.split(":", 1)
        path = ROOT / Path(*module.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        class_name, method_name = qualname.split(".", 1)
        selected_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == class_name
        )
        selected_methods = {
            node.name
            for node in selected_class.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert method_name in selected_methods


def test_guard_evidence_target_resolves_to_verifier_function() -> None:
    guard = inventory.GUARD_CONTRACTS[0]
    module, function = guard.evidence_target.split(":", 1)
    path = ROOT / Path(*module.split(".")).with_suffix(".py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    assert function == "verify_promotion_recovery_decision"
    assert function in functions


def test_blockers_cover_registration_discovery_and_both_wiring_gaps() -> None:
    assert set(inventory.BLOCKERS) == {
        "canonical-effect-boundary-guard-contract-not-yet-integrated",
        "canonical-effect-boundary-entrypoint-rows-not-yet-integrated",
        "static-effect-scanner-does-not-yet-discover-recovery-consumption-writes",
        "constructor-performs-unguarded-schema-initialization",
        "consume-is-locally-owner-guarded-but-not-effect-lease-central",
    }


def test_scanner_recognizer_has_no_wildcards_or_substring_matching() -> None:
    source = inspect.getsource(inventory.recognizes_recovery_consumption_method)

    assert "module == SCANNER_MODULE" in source
    assert "class_name == SCANNER_CLASS" in source
    assert "method in SCANNER_METHODS" in source
    assert "startswith" not in source
    assert "endswith" not in source
    assert " in module" not in source
    assert " in class_name" not in source
