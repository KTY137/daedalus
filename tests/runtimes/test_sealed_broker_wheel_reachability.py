from __future__ import annotations

import ast
from pathlib import Path

import daedalus.runtimes.broker as broker
import daedalus.runtimes.provider_executable_object_registry as executable_registry


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "daedalus"
BROKER = PACKAGE_ROOT / "runtimes" / "broker.py"
REGISTRY = PACKAGE_ROOT / "runtimes" / "provider_executable_object_registry.py"
TEST_DOUBLE = ROOT / "tests" / "runtimes" / "runtime_provider_test_double.py"


def test_wheel_projection_contains_no_callback_broker() -> None:
    packaging = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["daedalus*"]' in packaging
    assert 'exclude = ["tests*", "tools*"]' in packaging
    assert TEST_DOUBLE.is_file()

    wheel_python_sources = tuple(PACKAGE_ROOT.rglob("*.py"))
    assert wheel_python_sources
    assert all(TEST_DOUBLE not in source.parents for source in wheel_python_sources)
    assert all(
        "run_runtime_provider_test_double"
        not in source.read_text(encoding="utf-8")
        for source in wheel_python_sources
    )
    assert not hasattr(broker, "_run_runtime_provider_test_double")
    assert not hasattr(broker, "run_runtime_provider_test_double")


def test_production_broker_has_no_callable_or_tests_reachability() -> None:
    source = BROKER.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(BROKER))
    production = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_runtime_provider"
    )
    parameter_names = {
        argument.arg
        for argument in (
            *production.args.posonlyargs,
            *production.args.args,
            *production.args.kwonlyargs,
        )
    }
    assert {"invoke", "output_digests", "callback"}.isdisjoint(parameter_names)

    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_roots.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )
    assert "tests" not in imported_roots


def test_registry_execution_reaches_only_the_sealed_operation() -> None:
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    registry = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "ProviderExecutableObjectRegistry"
    )
    execute = next(
        node
        for node in registry.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_execute_sealed_operation"
    )
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(execute)
        if isinstance(node, ast.Call)
    }
    assert "entry.sealed_operation.invoke" in calls
    assert "entry.sealed_operation.output_digests" in calls
    assert "entry.invoke" not in calls
    assert "entry.output_digests" not in calls


def test_native_process_leaf_has_no_module_reachable_factory_or_live_template() -> None:
    tree = ast.parse(REGISTRY.read_text(encoding="utf-8"), filename=str(REGISTRY))
    top_level_functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert "_build_native_subprocess_run" not in top_level_functions
    assert not hasattr(executable_registry, "_build_native_subprocess_run")

    for name in ("_native_windows_run", "_native_posix_run"):
        template = getattr(executable_registry, name)
        required_native_bindings = {
            referenced
            for referenced in template.__code__.co_names
            if referenced.startswith("_NATIVE_")
        }
        assert required_native_bindings
        assert required_native_bindings.isdisjoint(template.__globals__)

    loaded_attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "Popen" not in loaded_attributes
