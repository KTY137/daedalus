from __future__ import annotations

import ast
from pathlib import Path


MODULE = Path("daedalus/gates/repository/head_revision.py")
CONTRACT = Path("daedalus/runtimes/contracts/repository.py")


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


def test_review_finds_no_process_network_write_or_effect_authority() -> None:
    tree = _tree()
    forbidden_modules = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "importlib",
    }
    forbidden_calls = {
        "open",
        "write_text",
        "write_bytes",
        "unlink",
        "rename",
        "replace",
        "mkdir",
        "rmdir",
        "run",
        "Popen",
        "system",
        "begin_effect",
        "finish_effect",
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


def test_review_uses_shared_race_aware_reader_for_git_bytes() -> None:
    source = MODULE.read_text(encoding="utf-8")

    assert "read_repository_source" in source
    assert "resolve_repository_root" in source
    assert '".git/HEAD"' in source
    assert '".git/packed-refs"' in source
    assert "subprocess" not in source
    assert "rev-parse" not in source


def test_review_performs_two_complete_head_observations() -> None:
    function = _function(_tree(), "verify_repository_head_revision")
    source = ast.unparse(function)

    assert source.count("_resolve_once(root)") == 2
    first = source.index("first = _resolve_once(root)")
    second = source.index("second = _resolve_once(root)")
    comparison = source.index("first.to_dict() != second.to_dict()")
    binding = source.index("first.resolved_revision != expected")
    assert first < second < comparison < binding
    assert "root_before" in source
    assert "git_before" in source


def test_review_receipt_claims_only_observed_head_equality() -> None:
    source = "\n".join(
        (
            MODULE.read_text(encoding="utf-8"),
            CONTRACT.read_text(encoding="utf-8"),
        )
    )

    assert '"repository_head_verified": True' in source
    assert '"commit_object_verified": False' in source
    assert '"worktree_clean_verified": False' in source
    assert '"process_spawned": False' in source
    assert '"repository_mutated": False' in source
    assert "provider_execution_allowed" not in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "closed = True" not in source


def test_review_live_receipt_verification_rebuilds_every_field() -> None:
    function = _function(
        _tree(),
        "verify_repository_head_revision_receipt",
    )
    source = ast.unparse(function)

    assert "verify_repository_head_revision(" in source
    assert "rebuilt.to_dict() != receipt.to_dict()" in source
    assert "RepositoryHeadRevisionBindingError" in source


def test_review_symbolic_resolution_never_hides_a_present_symlink() -> None:
    optional = _function(_tree(), "_safe_optional_regular_file")
    source = ast.unparse(optional)

    assert "FileNotFoundError" in source
    assert "stat.S_ISLNK" in source
    assert "contains a symlink" in source
    assert "return False" in source
