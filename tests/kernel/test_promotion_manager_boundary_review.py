from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "daedalus" / "kairos" / "gated_writes.py"
RESOURCE = ROOT / "daedalus" / "kairos" / "_gated_writes_execution_accounting.py.src"
AUDIT = ROOT / "daedalus" / "kairos" / "promotion_manager_audit.py"
BOUNDARY = ROOT / "daedalus" / "kairos" / "promotion_manager_boundary.py"
EXPECTED_PARENT_BLOB = "56fb60a5432b3a372c90b8b6bf279129f69db870"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _segment(path: Path, node: ast.AST) -> str:
    value = ast.get_source_segment(_source(path), node)
    assert value is not None
    return value


def _git_blob_sha(payload: bytes) -> str:
    return hashlib.sha1(
        f"blob {len(payload)}\0".encode("ascii") + payload
    ).hexdigest()


def test_wrapper_executes_exact_parent_blob_before_installing_boundary() -> None:
    assert _git_blob_sha(RESOURCE.read_bytes()) == EXPECTED_PARENT_BLOB
    source = _source(WRAPPER)
    assert f'_EXPECTED_GIT_BLOB_SHA = "{EXPECTED_PARENT_BLOB}"' in source
    assert "_git_blob_sha(_payload)" in source
    assert "exec(" in source
    assert "install_promotion_manager_boundary(globals())" in source
    assert source.index("exec(") < source.index("install_promotion_manager_boundary")


def test_wrapper_contains_no_reimplemented_promotion_logic() -> None:
    tree = _tree(WRAPPER)
    functions = {
        node.name for node in tree.body if isinstance(node, ast.FunctionDef)
    }
    assert functions == {"_git_blob_sha"}
    source = _source(WRAPPER)
    assert "git worktree" not in source.lower()
    assert "subprocess" not in source
    assert "OwnerApproval" not in source
    assert "merge_pull_request" not in source


def test_boundary_replaces_only_constructor_and_public_call_seams() -> None:
    installer = _segment(
        BOUNDARY,
        _function(BOUNDARY, "install_promotion_manager_boundary"),
    )
    for required in (
        'namespace["GitWorktreeManager"] = state.manager_factory',
        'namespace["PromotionExecutionLedger"] = state.ledger_factory',
        'namespace["promote_candidates"] = state.promote_candidates',
        'namespace["_REAL_GIT_WORKTREE_MANAGER"]',
        'namespace["_REAL_PROMOTION_EXECUTION_LEDGER"]',
        'namespace["_ACCOUNTED_PROMOTE_CANDIDATES"]',
    ):
        assert required in installer
    assert "exec(" not in installer


def test_boundary_never_performs_mutating_git_or_filesystem_calls() -> None:
    source = _source(BOUNDARY)
    forbidden = (
        "subprocess",
        "git worktree",
        "git merge",
        "Path.write_text",
        "Path.write_bytes",
        "os.replace",
        "shutil",
        "issue_owner_approval",
        "merge_pull_request",
    )
    for token in forbidden:
        assert token not in source
    assert "resolve_live_target_revision" in source


def test_manager_adapter_delegates_before_recording_success() -> None:
    tree = _tree(AUDIT)
    manager = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AuditedWorktreeManager"
    )
    methods = {
        child.name: child
        for child in manager.body
        if isinstance(child, ast.FunctionDef)
    }
    create = _segment(AUDIT, methods["create_worktree"])
    cleanup = _segment(AUDIT, methods["cleanup_worktree"])
    reap = _segment(AUDIT, methods["reap_branches"])
    assert create.index("self._delegate.create_worktree") < create.index(
        'status="succeeded"'
    )
    assert cleanup.index("self._delegate.cleanup_worktree") < cleanup.index(
        'status="succeeded"'
    )
    assert reap.index("self._delegate.reap_branches") < reap.index(
        'status="succeeded"'
    )
    assert "except BaseException" in create
    assert "except BaseException" in cleanup
    assert "except BaseException" in reap
    assert "raise" in create and "raise" in cleanup and "raise" in reap


def test_execution_proxy_binds_audit_before_terminal_delegate() -> None:
    tree = _tree(BOUNDARY)
    proxy = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_AuditedExecutionLedger"
    )
    complete = next(
        child
        for child in proxy.body
        if isinstance(child, ast.FunctionDef) and child.name == "complete"
    )
    source = _segment(BOUNDARY, complete)
    assert 'enriched["manager_audit"] = snapshot.to_dict()' in source
    assert 'enriched["manager_audit_sha256"] = snapshot.digest' in source
    assert source.index("_assess_completion(") < source.rindex(
        "self._delegate.complete("
    )


def test_unknown_identity_uses_pending_not_optimistic_fault() -> None:
    source = _source(BOUNDARY)
    assert "PromotionManagerAuditPending" in source
    assert "cannot prove the surviving integration identity" in source
    assert "refused promotion did not prove branch deletion" in source
    assert "promotion mutation entered without one auditable allocation" in source


def test_no_gate_or_owner_claim_is_embedded() -> None:
    source = (_source(WRAPPER) + _source(AUDIT) + _source(BOUNDARY)).lower()
    assert "closed=true" not in source
    assert "gate 0 is closed" not in source
    assert "issue_owner_approval" not in source
    assert "automatic promotion" not in source
