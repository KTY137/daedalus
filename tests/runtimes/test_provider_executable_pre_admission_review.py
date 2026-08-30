from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_executable_pre_admission as module


def test_pre_admission_module_has_no_loader_process_network_or_callback_imports():
    tree = ast.parse(inspect.getsource(module))
    forbidden_roots = {
        "asyncio",
        "httpx",
        "importlib",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden_roots)


def test_pre_admission_factory_contains_no_execution_or_effect_start_calls():
    tree = ast.parse(inspect.getsource(module.build_provider_executable_pre_admission))
    called_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    called_attrs = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    forbidden = {
        "begin_effect",
        "complete_effect",
        "eval",
        "exec",
        "invoke",
        "output_digests",
        "Popen",
        "run",
        "system",
    }
    assert (called_names | called_attrs).isdisjoint(forbidden)


def test_pre_admission_receipt_cannot_claim_executable_authority():
    source = inspect.getsource(module.ProviderExecutablePreAdmissionReceipt.to_dict)
    assert '"provider_execution_allowed"' not in source
    assert "_FALSE_CLAIMS" in source
    assert "repository_bytes_executed" in module._FALSE_CLAIMS
    assert "provider_execution_allowed" in module._FALSE_CLAIMS
    assert "callback_seam_removed" in module._FALSE_CLAIMS
