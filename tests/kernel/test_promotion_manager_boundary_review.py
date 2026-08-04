from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "daedalus" / "kairos" / "gated_writes.py"
AUDIT = ROOT / "daedalus" / "kairos" / "promotion_manager_audit.py"
BOUNDARY = ROOT / "daedalus" / "kairos" / "promotion_manager_boundary.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _method(path: Path, class_name: str, name: str) -> ast.FunctionDef:
    for node in _tree(path).body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for child in node.body:
                if isinstance(child, ast.FunctionDef) and child.name == name:
                    return child
    raise AssertionError(f"missing {class_name}.{name}")


def _segment(path: Path, node: ast.AST) -> str:
    value = ast.get_source_segment(_source(path), node)
    assert value is not None
    return value


def test_public_boundary_remains_unwired_until_dependent_packet() -> None:
    source = _source(PUBLIC)
    assert "def promote_candidates(" in source
    assert "install_promotion_manager_boundary(globals())" not in source
    assert "install_promotion_manager_replay_boundary(globals())" not in source
    assert "issue_owner_approval" not in source
    assert "merge_pull_request" not in source


def test_installer_preserves_public_ledger_class_and_wraps_only_call_seams() -> None:
    installer = _segment(
        BOUNDARY,
        _function(BOUNDARY, "install_promotion_manager_boundary"),
    )
    for required in (
        'namespace["GitWorktreeManager"] = state.manager_factory',
        'namespace["PromotionExecutionLedger"] = ledger_type',
        'namespace["promote_candidates"] = state.promote_candidates',
        'namespace["_REAL_GIT_WORKTREE_MANAGER"]',
        'namespace["_REAL_PROMOTION_EXECUTION_LEDGER"]',
        'namespace["_ACCOUNTED_PROMOTE_CANDIDATES"]',
    ):
        assert required in installer
    assert "state.ledger_factory" not in installer
    assert "exec(" not in installer


def test_typed_proxy_cannot_turn_an_arbitrary_object_into_a_valid_ledger() -> None:
    source = _source(BOUNDARY)
    tree = _tree(BOUNDARY)
    proxy = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_AuditedExecutionLedger"
    )
    assert any(
        isinstance(base, ast.Name) and base.id == "PromotionExecutionLedger"
        for base in proxy.bases
    )
    wrapper = _segment(BOUNDARY, _method(BOUNDARY, "_BoundaryState", "wrap_ledger"))
    assert "if not isinstance(delegate, self.ledger_type)" in wrapper
    assert "return delegate" in wrapper
    assert "wrapper(delegate, self)" in wrapper
    assert "ledger_constructor" not in source


def test_manager_context_is_single_and_scoped_to_one_public_call() -> None:
    manager_factory = _segment(
        BOUNDARY,
        _method(BOUNDARY, "_BoundaryState", "manager_factory"),
    )
    promote = _segment(
        BOUNDARY,
        _method(BOUNDARY, "_BoundaryState", "promote_candidates"),
    )
    assert "self.active_manager.get() is not None" in manager_factory
    assert "more than one manager" in manager_factory
    assert "token = self.active_manager.set(None)" in promote
    assert "self.active_manager.reset(token)" in promote
    assert '"promotion_execution_ledger" in call_kwargs' in promote


def test_boundary_never_performs_mutating_git_or_filesystem_calls() -> None:
    source = _source(BOUNDARY).lower()
    forbidden = (
        "subprocess",
        "git worktree",
        "git merge",
        "path.write_text",
        "path.write_bytes",
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
    complete = _segment(
        BOUNDARY,
        _method(BOUNDARY, "_AuditedExecutionLedger", "complete"),
    )
    assert 'enriched["manager_audit"] = snapshot.to_dict()' in complete
    assert 'enriched["manager_audit_sha256"] = snapshot.digest' in complete
    assert complete.index("_assess_completion(") < complete.rindex(
        "self._delegate.complete("
    )


def test_unknown_identity_uses_pending_not_optimistic_fault() -> None:
    source = _source(BOUNDARY)
    assert "PromotionManagerAuditPending" in source
    assert "cannot prove the surviving integration identity" in source
    assert "refused promotion did not prove branch deletion" in source
    assert "promotion mutation entered without one auditable allocation" in source


def test_no_gate_or_owner_claim_is_embedded() -> None:
    source = (_source(AUDIT) + _source(BOUNDARY)).lower()
    assert "closed=true" not in source
    assert "gate 0 is closed" not in source
    assert "issue_owner_approval" not in source
    assert "automatic promotion" not in source
