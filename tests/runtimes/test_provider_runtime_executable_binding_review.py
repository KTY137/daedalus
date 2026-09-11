from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider.runtime_executable_binding as binding


def _function(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(inspect.getsource(binding))
    matches = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_public_binding_accepts_evidence_not_provider_callbacks() -> None:
    function = _function("bind_provider_runtime_executable")
    keyword_names = [arg.arg for arg in function.args.kwonlyargs]
    assert keyword_names == [
        "authorization",
        "execution",
        "observation_authority",
        "observation_binding_ledger",
        "executable_registry",
        "pre_admission",
        "at",
    ]
    assert "invoke" not in keyword_names
    assert "output_digests" not in keyword_names


def test_binding_authenticates_before_revalidation_and_never_starts_effect() -> None:
    source = inspect.getsource(binding.bind_provider_runtime_executable)
    observation_position = source.index("observation_binding_ledger.verify_authority(")
    registry_position = source.index("executable_registry.verify_registered(")
    return_position = source.index("return ProviderRuntimeExecutableBindingReceipt(")
    assert observation_position < registry_position < return_position

    forbidden = (
        ".grant(",
        ".begin_effect(",
        ".finish_effect(",
        ".bind_start(",
        ".require_bound(",
        "invoke()",
        "output_digests(",
    )
    for fragment in forbidden:
        assert fragment not in source


def test_module_has_no_dynamic_loader_process_network_or_callback_authority() -> None:
    source = inspect.getsource(binding)
    tree = ast.parse(source)
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)

    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "importlib",
        "asyncio.subprocess",
    }
    assert imported.isdisjoint(forbidden_imports)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "Callable" not in source


def test_exact_types_are_checked_before_boundary_methods() -> None:
    source = inspect.getsource(binding.bind_provider_runtime_executable)
    exact_position = source.index("_require_exact_boundary_types(")
    observation_position = source.index("observation_binding_ledger.verify_authority(")
    registry_position = source.index("executable_registry.verify_registered(")
    assert exact_position < observation_position < registry_position

    exact_source = inspect.getsource(binding._require_exact_boundary_types)
    assert "type(value) is not exact_type" in exact_source
    assert "isinstance(value" not in exact_source
