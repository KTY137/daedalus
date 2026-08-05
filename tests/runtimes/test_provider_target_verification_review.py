from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_target_verification as verifier
import daedalus.runtimes.provider_target_verification_contracts as contracts


def _tree(module) -> ast.Module:
    return ast.parse(inspect.getsource(module))


def _function(module, name: str) -> ast.FunctionDef:
    for node in _tree(module).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _class(module, name: str) -> ast.ClassDef:
    for node in _tree(module).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"missing class {name}")


def test_verifier_has_no_loader_execution_process_network_or_write_primitives() -> None:
    tree = _tree(verifier)
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
            "put_bytes",
            "capture_tree",
            "materialize_tree",
            "write_text",
            "write_bytes",
            "unlink",
            "rename",
            "replace",
        }
    )


def test_public_apis_accept_no_callback_loader_or_raw_verifier_secret() -> None:
    for name in (
        "issue_provider_target_verification_receipt",
        "verify_provider_target_verification_receipt",
    ):
        function = _function(verifier, name)
        names = [
            item.arg
            for item in (
                function.args.args
                + function.args.kwonlyargs
            )
        ]
        assert {
            "invoke",
            "output_digests",
            "callback",
            "loader",
            "provider",
            "client",
            "executor",
            "verifier_secret",
        }.isdisjoint(names)
        assert "source_store" in names
        assert "source_tree_ref" in names
        assert "verifier_keyring" in names


def test_signed_target_authentication_precedes_source_tree_read() -> None:
    source = inspect.getsource(verifier._structural_projection)
    target_auth = source.index("project_provider_executable_targets(")
    tree_read = source.index("source_store.load_tree(source_tree_ref)")
    source_verify = source.index("_verify_one_target(")
    assert target_auth < tree_read < source_verify


def test_receipt_signature_precedes_every_source_tree_read() -> None:
    source = inspect.getsource(
        verifier.verify_provider_target_verification_receipt
    )
    signature = source.index(
        "hmac.compare_digest(receipt.signature_sha256, expected_signature)"
    )
    structural = source.index("_structural_projection(")
    assert signature < structural


def test_exact_blob_digest_is_recomputed_before_utf8_decode_and_ast_parse() -> None:
    source = inspect.getsource(verifier._verify_one_target)
    read = source.index("source_store.read_bytes(")
    digest = source.index("hashlib.sha256(payload).hexdigest()")
    decode = source.index('payload.decode("utf-8")')
    parse = source.index("ast.parse(")
    resolve = source.index("_resolve_definition(")
    assert read < digest < decode < parse < resolve


def test_module_resolution_is_exact_and_ambiguous_definitions_refuse() -> None:
    module_paths = inspect.getsource(verifier._module_paths)
    assert 'f"{base}.py"' in module_paths
    assert 'f"{base}/__init__.py"' in module_paths

    entry_lookup = inspect.getsource(verifier._entry_for_module)
    assert "if len(matches) != 1" in entry_lookup

    definition_lookup = inspect.getsource(verifier._resolve_definition)
    assert "if len(matches) != 1" in definition_lookup
    assert "non-final target owner must be an exact class definition" in definition_lookup
    assert "target must resolve to a function or method" in definition_lookup


def test_source_tree_store_ref_receipt_and_nested_targets_require_exact_types() -> None:
    structural = inspect.getsource(verifier._structural_projection)
    assert "type(source_store) is not SourceTreeStore" in structural
    assert "type(source_tree_ref) is not ArtifactRef" in structural

    verification = inspect.getsource(
        verifier.verify_provider_target_verification_receipt
    )
    assert (
        "type(receipt) is not ProviderExecutableTargetVerificationReceipt"
        in verification
    )

    receipt = _class(
        contracts,
        "ProviderExecutableTargetVerificationReceipt",
    )
    post_init = next(
        node
        for node in receipt.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    rendered = ast.unparse(post_init)
    assert "type(self.invoke) is not VerifiedPythonTarget" in rendered
    assert "type(self.output_digests) is not VerifiedPythonTarget" in rendered


def test_receipt_claims_are_fixed_and_wire_parser_refuses_escalation() -> None:
    receipt = _class(
        contracts,
        "ProviderExecutableTargetVerificationReceipt",
    )
    to_dict = next(
        node
        for node in receipt.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    rendered = ast.unparse(to_dict)
    assert "'targets_structurally_verified': True" in rendered
    assert "'provider_execution_allowed': False" in rendered

    parser = next(
        node
        for node in receipt.body
        if isinstance(node, ast.FunctionDef) and node.name == "from_dict"
    )
    parser_source = ast.unparse(parser)
    assert "payload['targets_structurally_verified'] is not True" in parser_source
    assert "payload['provider_execution_allowed'] is not False" in parser_source


def test_receipt_signature_covers_complete_canonical_wire() -> None:
    receipt = _class(
        contracts,
        "ProviderExecutableTargetVerificationReceipt",
    )
    signing = next(
        node
        for node in receipt.body
        if isinstance(node, ast.FunctionDef) and node.name == "signing_digest"
    )
    rendered = ast.unparse(signing)
    assert "body = self.to_dict()" in rendered
    assert "body['signature_sha256'] = '0' * 64" in rendered
    assert "canonical_sha(body)" in rendered

    verifier_source = inspect.getsource(
        verifier.verify_provider_target_verification_receipt
    )
    assert "receipt != expected" in verifier_source
    assert "re-read exact bytes" in (
        verifier.verify_provider_target_verification_receipt.__doc__ or ""
    )


def test_verifier_reuses_canonical_source_tree_and_signed_target_authorities() -> None:
    tree = _tree(verifier)
    imports = {
        alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert {
        "SourceTreeStore",
        "SourceTreeManifest",
        "ArtifactRef",
        "ProviderExecutableTargetAuthority",
        "ProviderExecutableTargetManifest",
        "project_provider_executable_targets",
    }.issubset(imports)


def test_exports_are_bounded_to_contracts_and_two_read_only_operations() -> None:
    assert set(verifier.__all__) == {
        "issue_provider_target_verification_receipt",
        "verify_provider_target_verification_receipt",
    }
    assert set(contracts.__all__) == {
        "ProviderExecutableTargetVerificationReceipt",
        "ProviderTargetVerificationBindingError",
        "ProviderTargetVerificationError",
        "ProviderTargetVerificationSignatureError",
        "ProviderTargetVerificationSourceError",
        "VerifiedPythonTarget",
    }
