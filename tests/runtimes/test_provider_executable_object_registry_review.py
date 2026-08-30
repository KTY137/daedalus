from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus/runtimes/provider_executable_object_registry.py"


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"), filename=str(TARGET))


def test_guarded_registry_has_no_dynamic_import_or_provider_execution_boundary() -> None:
    tree = _tree()
    forbidden_import_roots = {
        "importlib",
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not forbidden_import_roots.intersection(
                alias.name.split(".", 1)[0] for alias in node.names
            )
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".", 1)[0] not in forbidden_import_roots

    forbidden_calls = {
        "exec",
        "eval",
        "__import__",
        "run_runtime_provider",
        "begin_effect",
        "grant",
        "complete_effect",
        "fail_effect",
        "_invoke_claude_cli",
    }
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            called_names.add(function.id)
        elif isinstance(function, ast.Attribute):
            called_names.add(function.attr)
    assert forbidden_calls.isdisjoint(called_names)
    assert "compile" in called_names


def test_registry_exposes_evidence_only_not_a_public_callable_resolver() -> None:
    tree = _tree()
    classes = {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }
    registry = classes["ProviderExecutableObjectRegistry"]
    public_methods = {
        node.name
        for node in registry.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
    }
    assert public_methods == {"register", "verify_registered"}

    exports = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in node.targets
        )
    )
    exported = {
        element.value
        for element in exports.value.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    }
    assert "_RegisteredProviderExecutableObjects" not in exported


def test_registry_reproves_loaded_function_ambient_dependencies() -> None:
    tree = _tree()
    function_names = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_referenced_global_names" in function_names
    assert "_verify_function_ambient_dependencies" in function_names

    attributes = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
    }
    assert "__globals__" in attributes
    assert "__builtins__" in attributes

    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "get_instructions" in calls


def test_admission_receipt_keeps_execution_authority_claims_false() -> None:
    tree = _tree()
    false_claims = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_FALSE_CLAIMS"
            for target in node.targets
        )
    )
    values = {
        element.value
        for element in false_claims.value.elts
        if isinstance(element, ast.Constant)
    }
    assert {
        "provider_code_executed",
        "provider_execution_allowed",
        "effect_start_authorized",
        "callback_seam_removed",
        "broker_invocation_performed",
        "automatic_reexecution_allowed",
    }.issubset(values)
