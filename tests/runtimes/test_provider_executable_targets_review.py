# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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

    direct_calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert direct_calls.isdisjoint(
        {"eval", "exec", "open", "compile", "__import__"}
    )
    attribute_calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert attribute_calls.isdisjoint(
        {
            "import_module",
            "run",
            "Popen",
            "system",
            "connect",
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
        }
    )


def test_public_projection_api_accepts_no_callback_loader_or_identity_assertion() -> None:
    function = _function("project_provider_executable_targets")
    args = [item.arg for item in function.args.args]
    kwonly = [item.arg for item in function.args.kwonlyargs]
    assert args == [
        "target_authority",
        "authority",
        "identity_registry",
        "execution",
        "manifest",
    ]
    assert kwonly == [
        "target_contract_id",
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


def test_invocation_and_target_signatures_precede_manifest_lookup() -> None:
    source = inspect.getsource(module.project_provider_executable_targets)
    invocation_auth = source.index("project_provider_invocation_identity(")
    target_signature = source.index(
        "hmac.compare_digest(target_authority.signature_sha256, signature)"
    )
    early_binding = source.index("early_mismatches = tuple(")
    target_lookup = source.index(
        "manifest.descriptor_for_provider(identity.provider_id)"
    )
    descriptor_binding = source.index("descriptor_comparisons = {")
    assert (
        invocation_auth
        < target_signature
        < early_binding
        < target_lookup
        < descriptor_binding
    )


def test_signed_target_authority_binds_complete_invocation_and_target_subject() -> None:
    authority = _class("ProviderExecutableTargetAuthority")
    fields = {
        node.target.id
        for node in authority.body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    }
    assert fields == {
        "authority_key_id",
        "target_contract_id",
        "invocation_authority_sha256",
        "invocation_contract_sha256",
        "invocation_identity_sha256",
        "identity_registry_sha256",
        "identity_descriptor_sha256",
        "target_manifest_sha256",
        "target_descriptor_sha256",
        "provider_id",
        "adapter_id",
        "implementation_id",
        "entrypoint_id",
        "runtime_id",
        "execution_id",
        "idempotency_key",
        "lease_sha256",
        "source_revision",
        "signature_sha256",
    }
    signing = next(
        node
        for node in authority.body
        if isinstance(node, ast.FunctionDef) and node.name == "signing_digest"
    )
    signing_source = ast.unparse(signing)
    assert "body = self.to_dict()" in signing_source
    assert "body['signature_sha256'] = '0' * 64" in signing_source
    assert "canonical_sha(body)" in signing_source


def test_target_manifest_is_signed_before_any_descriptor_can_be_selected() -> None:
    function = _function("project_provider_executable_targets")
    source = ast.unparse(function)
    assert (
        "'target_manifest_sha256': "
        "(target_authority.target_manifest_sha256, manifest.digest)"
        in source
    )
    assert (
        "'target_descriptor_sha256': "
        "(target_authority.target_descriptor_sha256, descriptor.digest)"
        in source
    )
    assert "provider executable target authority binding mismatch before target lookup" in source


def test_identity_and_descriptor_bindings_are_complete() -> None:
    function = _function("project_provider_executable_targets")
    assignments = {
        target.id: node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    assert isinstance(assignments["early"], ast.Dict)
    early_keys = {
        key.value
        for key in assignments["early"].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert early_keys == {
        "authority_key_id",
        "target_contract_id",
        "invocation_authority_sha256",
        "invocation_contract_sha256",
        "invocation_identity_sha256",
        "identity_registry_sha256",
        "identity_descriptor_sha256",
        "target_manifest_sha256",
        "provider_id",
        "adapter_id",
        "implementation_id",
        "entrypoint_id",
        "runtime_id",
        "execution_id",
        "idempotency_key",
        "lease_sha256",
        "source_revision",
    }
    assert isinstance(assignments["descriptor_comparisons"], ast.Dict)
    descriptor_keys = {
        key.value
        for key in assignments["descriptor_comparisons"].keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }
    assert descriptor_keys == {
        "target_descriptor_sha256",
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


def test_module_exports_only_signed_inert_contract_operations() -> None:
    assert set(module.__all__) == {
        "ProviderExecutableTargetAuthority",
        "ProviderExecutableTargetBindingError",
        "ProviderExecutableTargetDescriptor",
        "ProviderExecutableTargetError",
        "ProviderExecutableTargetManifest",
        "ProviderExecutableTargetProjection",
        "ProviderExecutableTargetShapeError",
        "ProviderExecutableTargetSignatureError",
        "build_provider_executable_target_manifest",
        "issue_provider_executable_target_authority",
        "project_provider_executable_targets",
    }
