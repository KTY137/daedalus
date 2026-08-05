from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_executable_targets as module


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _function(name: str) -> ast.FunctionDef:
    for node in _tree().body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(name: str) -> ast.ClassDef:
    for node in _tree().body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def test_module_has_no_import_loader_execution_process_network_or_write_authority() -> None:
    tree = _tree()
    forbidden_import_roots = {
        "builtins",
        "importlib",
        "pathlib",
        "subprocess",
        "socket",
        "sqlite3",
        "urllib",
        "http",
        "requests",
    }
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".", 1)[0])
    assert imported.isdisjoint(forbidden_import_roots)

    forbidden_calls = {
        "eval",
        "exec",
        "open",
        "compile",
        "__import__",
        "import_module",
        "run",
        "Popen",
        "system",
        "connect",
        "write_text",
        "write_bytes",
        "unlink",
        "replace",
        "rename",
    }
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    calls.update(
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    )
    assert calls.isdisjoint(forbidden_calls)


def test_public_projection_api_accepts_no_callback_loader_or_projection_assertion() -> None:
    function = _function("project_provider_executable_targets")
    args = [item.arg for item in function.args.args]
    kwonly = [item.arg for item in function.args.kwonlyargs]
    assert args == ["authority", "identity_registry", "execution", "manifest"]
    assert kwonly == [
        "authority_id",
        "authority_keyring",
        "observation_keyring",
        "at",
    ]
    forbidden = {
        "identity",
        "invoke",
        "output_digests",
        "callback",
        "loader",
        "provider",
        "client",
        "executor",
    }
    assert forbidden.isdisjoint(args + kwonly)


def test_invocation_authentication_precedes_manifest_binding_and_lookup() -> None:
    source = inspect.getsource(module.project_provider_executable_targets)
    authentication = source.index("project_provider_invocation_identity(")
    revision = source.index("manifest.source_revision != identity.source_revision")
    registry = source.index(
        "manifest.identity_registry_sha256 != identity.registry_sha256"
    )
    lookup = source.index("manifest.descriptor_for_provider(identity.provider_id)")
    comparisons = source.index("comparisons = {")
    assert authentication < revision < registry < lookup < comparisons


def test_identity_is_derived_internally_and_complete_binding_is_compared() -> None:
    function = _function("project_provider_executable_targets")
    source = ast.unparse(function)
    assert "identity = project_provider_invocation_identity" in source
    required = {
        "provider_id",
        "adapter_id",
        "implementation_id",
        "entrypoint_id",
        "runtime_id",
        "source_revision",
        "identity_descriptor_sha256",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
    }
    comparisons = next(
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "comparisons"
            for target in node.targets
        )
    )
    assert isinstance(comparisons.value, ast.Dict)
    keys = {
        key.value
        for key in comparisons.value.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert keys == required


def test_projection_permanently_refuses_structural_and_execution_claims() -> None:
    cls = _class("ProviderExecutableTargetProjection")
    method = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    returns = [node for node in ast.walk(method) if isinstance(node, ast.Return)]
    assert len(returns) == 1
    rendered = ast.unparse(returns[0].value)
    assert "'targets_structurally_verified': False" in rendered
    assert "'provider_execution_allowed': False" in rendered

    parser = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "from_dict"
    )
    parser_source = ast.unparse(parser)
    assert "payload['targets_structurally_verified'] is not False" in parser_source
    assert "payload['provider_execution_allowed'] is not False" in parser_source


def test_target_grammar_is_daedalus_local_and_descriptor_is_data_only() -> None:
    pattern = module._TARGET_RE.pattern
    assert pattern.startswith("^daedalus")
    assert pattern.endswith("$")

    descriptor = _class("ProviderExecutableTargetDescriptor")
    methods = {
        node.name
        for node in descriptor.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert methods == {"__post_init__", "to_dict", "from_dict", "digest"}
    fields = {
        node.target.id
        for node in descriptor.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert "invoke_target" in fields
    assert "output_digests_target" in fields
    assert not {"invoke", "output_digests", "execute", "load"}.intersection(fields)


def test_module_exports_only_inert_contract_and_projection_operations() -> None:
    exports = set(module.__all__)
    assert exports == {
        "ProviderExecutableTargetBindingError",
        "ProviderExecutableTargetDescriptor",
        "ProviderExecutableTargetError",
        "ProviderExecutableTargetManifest",
        "ProviderExecutableTargetProjection",
        "ProviderExecutableTargetShapeError",
        "build_provider_executable_target_manifest",
        "project_provider_executable_targets",
    }
