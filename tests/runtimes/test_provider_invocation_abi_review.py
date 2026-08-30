from __future__ import annotations

import ast
from pathlib import Path


MODULE = Path("daedalus/runtimes/provider_invocation_abi.py")


def _tree() -> ast.AST:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def test_invocation_abi_boundary_contains_no_execution_or_loader_apis() -> None:
    tree = _tree()
    forbidden_import_roots = {
        "asyncio",
        "importlib",
        "multiprocessing",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    forbidden_calls = {
        "begin_effect",
        "eval",
        "exec",
        "open",
        "run_runtime_provider",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(
                alias.name.split(".", 1)[0] in forbidden_import_roots
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            assert root not in forbidden_import_roots
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            elif isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls


def test_invocation_abi_public_surface_exposes_no_callable_resolver() -> None:
    tree = _tree()
    function_names = {
        node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "resolve_callable" not in function_names
    assert "load_provider" not in function_names
    assert "invoke_provider" not in function_names

    source = MODULE.read_text(encoding="utf-8")
    assert "Callable[" not in source
    assert "provider_execution_allowed\": True" not in source
    assert "effect_start_authorized\": True" not in source
