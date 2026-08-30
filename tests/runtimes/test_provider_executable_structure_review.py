# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


MODULE = Path("daedalus/runtimes/provider_executable_structure.py")


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE))


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_review_finds_no_dynamic_loading_execution_or_effect_authority() -> None:
    tree = _tree()
    forbidden_modules = {"importlib", "subprocess", "runpy", "ctypes"}
    forbidden_calls = {
        "__import__",
        "compile",
        "eval",
        "exec",
        "import_module",
        "open",
        "begin_effect",
        "finish_effect",
        "run_runtime_provider",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert forbidden_modules.isdisjoint(roots)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_modules
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls


def test_review_public_api_accepts_authority_not_loose_projection() -> None:
    function = _function(_tree(), "verify_provider_executable_structure")
    positional = [argument.arg for argument in function.args.args]
    keyword_only = [argument.arg for argument in function.args.kwonlyargs]

    assert positional == [
        "repository_root",
        "target_authority",
        "invocation_authority",
        "identity_registry",
        "execution",
        "manifest",
    ]
    assert "projection" not in positional
    assert "projection" not in keyword_only
    assert keyword_only == [
        "target_contract_id",
        "authority_id",
        "authority_keyring",
        "observation_keyring",
        "at",
    ]


def test_review_authenticates_before_repository_resolution() -> None:
    function = _function(_tree(), "verify_provider_executable_structure")
    source = ast.unparse(function)

    authentication = source.index("_authenticate_projection(")
    first_resolution = source.index("resolve_python_target_structure(")
    assert authentication < first_resolution
    assert source.count("resolve_python_target_structure(") == 2
    assert "projection.invoke_source_sha256" in source
    assert "projection.output_digests_source_sha256" in source


def test_review_authenticator_replays_signed_predecessor_exactly() -> None:
    function = _function(_tree(), "_authenticate_projection")
    source = ast.unparse(function)

    for exact_type in (
        "ProviderExecutableTargetAuthority",
        "ProviderInvocationObservationAuthority",
        "ProviderInvocationRegistryManifest",
        "EffectExecutionRequest",
        "ProviderExecutableTargetManifest",
    ):
        assert exact_type in source
    assert "project_provider_executable_targets(" in source
    assert "ProviderExecutableTargetError" in source
    assert "type(projection) is not ProviderExecutableTargetProjection" in source


def test_review_receipt_retains_complete_authority_chain() -> None:
    source = MODULE.read_text(encoding="utf-8")

    for field in (
        "target_authority_sha256",
        "invocation_authority_sha256",
        "invocation_contract_sha256",
        "target_contract_id",
        "execution_id",
        "idempotency_key",
        "lease_sha256",
        "identity_registry_sha256",
        "identity_descriptor_sha256",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
    ):
        assert field in source
    assert '"target_authority_authenticated": True' in source
    assert '"targets_structurally_verified": True' in source
    assert '"repository_bytes_executed": False' in source
    assert '"provider_execution_allowed": False' in source
    assert '"source_revision_verified_against_git_head": False' in source


def test_review_rebuilds_receipt_instead_of_trusting_retained_fields() -> None:
    function = _function(
        _tree(),
        "verify_provider_executable_structure_receipt",
    )
    source = ast.unparse(function)

    assert "verify_provider_executable_structure(" in source
    assert "rebuilt.to_dict() != receipt.to_dict()" in source
    assert "ProviderExecutableStructureBindingError" in source


def test_review_module_is_responsibility_local_and_additive() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "from daedalus.runtimes.provider_executable_targets" in source
    assert "from daedalus.gates.python_target_structure" in source
    assert "ProviderExecutableTargetAuthority" in source
    assert "ProviderExecutableStructureReceipt" in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "closed = True" not in source
