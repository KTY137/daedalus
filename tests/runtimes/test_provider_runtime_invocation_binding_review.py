from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus/runtimes/provider_runtime_invocation_binding.py"


def _tree() -> ast.AST:
    return ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))


def test_runtime_invocation_binding_contains_no_execution_or_effect_start() -> None:
    tree = _tree()
    forbidden_calls = {
        "grant",
        "begin_effect",
        "finish_effect",
        "bind_start",
        "invoke",
        "output_digests",
        "Popen",
        "run",
        "system",
        "exec",
        "eval",
        "__import__",
    }
    observed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            observed.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            observed.add(node.func.attr)

    assert forbidden_calls.isdisjoint(observed)


def test_runtime_invocation_binding_has_no_callable_or_dynamic_loader_surface() -> None:
    tree = _tree()
    imported_names: set[str] = set()
    attribute_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module)
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Attribute):
            attribute_names.add(node.attr)

    source = SOURCE.read_text(encoding="utf-8")
    assert "Callable" not in source
    assert "types.FunctionType" not in source
    assert not any(
        name in imported_names
        for name in ("subprocess", "socket", "importlib", "ctypes", "multiprocessing")
    )
    assert {"resolve", "resolve_registered", "get_callable"}.isdisjoint(attribute_names)


def test_runtime_invocation_binding_reuses_existing_authorities() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "verify_provider_invocation_abi_contract" in source
    assert "bind_provider_runtime_executable" in source
    assert "ProviderObservationBindingLedger" in source
    assert "ProviderExecutableObjectRegistry" in source
    assert "ProviderInvocationObservationAuthority" in source
