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
            assert forbidden_modules.isdisjoint(alias.name.split(".")[0] for alias in node.names)
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_modules
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in forbidden_calls
            if isinstance(node.func, ast.Attribute):
                assert node.func.attr not in forbidden_calls


def test_review_requires_exact_projection_before_repository_resolution() -> None:
    function = _function(_tree(), "verify_provider_executable_structure")
    source = ast.unparse(function)

    type_fence = source.index(
        "type(projection) is not ProviderExecutableTargetProjection"
    )
    first_resolution = source.index("resolve_python_target_structure")
    assert type_fence < first_resolution
    assert source.count("resolve_python_target_structure") == 2
    assert "projection.invoke_source_sha256" in source
    assert "projection.output_digests_source_sha256" in source


def test_review_rebuilds_receipt_instead_of_trusting_retained_fields() -> None:
    function = _function(_tree(), "verify_provider_executable_structure_receipt")
    source = ast.unparse(function)

    assert "verify_provider_executable_structure(repository_root, projection)" in source
    assert "rebuilt.to_dict() != receipt.to_dict()" in source
    assert "ProviderExecutableStructureBindingError" in source


def test_review_permanently_refuses_execution_and_git_head_claims() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert '"targets_structurally_verified": True' in source
    assert '"repository_bytes_executed": False' in source
    assert '"provider_execution_allowed": False' in source
    assert '"source_revision_verified_against_git_head": False' in source
    assert 'payload["provider_execution_allowed"] is not False' in source
    assert 'payload["source_revision_verified_against_git_head"] is not False' in source


def test_review_module_is_responsibility_local_and_additive() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "from daedalus.runtimes.provider_executable_targets" in source
    assert "from daedalus.gates.python_target_structure" in source
    assert "ProviderExecutableTargetProjection" in source
    assert "ProviderExecutableStructureReceipt" in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "closed = True" not in source
