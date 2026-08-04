from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.kairos.gated_writes as gated_writes
from daedalus.spine.effect_boundary import check_conformance


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        value = func.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
        return ".".join(reversed(parts))
    return ""


def _promotion_function() -> ast.FunctionDef | ast.AsyncFunctionDef:
    tree = ast.parse(inspect.getsource(gated_writes.promote_candidates))
    function = tree.body[0]
    assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
    return function


def _promotion_lock(function):
    with_nodes = [node for node in ast.walk(function) if isinstance(node, ast.With)]
    promotion_locks = [
        node
        for node in with_nodes
        if any(
            isinstance(item.context_expr, ast.Call)
            and _call_name(item.context_expr) == "_PromotionLock"
            for item in node.items
        )
    ]
    assert len(promotion_locks) == 1
    return promotion_locks[0]


def test_public_seam_requires_all_persisted_authorities() -> None:
    signature = inspect.signature(gated_writes.promote_candidates)
    assert signature.parameters["approval_ledger"].default is None
    assert signature.parameters["owner_keyring"].default is None
    assert signature.parameters["promotion_execution_ledger"].default is None
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "isinstance(promotion_execution_ledger, PromotionExecutionLedger)" in source
    assert "_legacy_unpersisted_refusal" in source


def test_legacy_refusal_contains_no_git_or_other_effect_primitive() -> None:
    source = inspect.getsource(gated_writes._legacy_unpersisted_refusal)
    tree = ast.parse(source)
    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "resolve_live_target_revision" not in source
    assert "authorize_promotion" not in source
    assert "subprocess.run" not in calls
    assert "GitWorktreeManager" not in calls
    assert "_PromotionLock" not in calls
    assert "resolve_spine_db_path" not in calls
    assert calls <= {"_promotion_refusal", "PromotionAuthorizationError"}


def test_persisted_capability_and_execution_start_precede_mutation() -> None:
    function = _promotion_function()
    source = inspect.getsource(gated_writes.promote_candidates)
    snapshot_at = source.index("_snapshot_promotion_candidates(submitted_candidates)")
    preflight_at = source.index(
        "authorize_persisted_promotion(\n            approval_ledger=approval_ledger"
    )
    manager_at = source.index("GitWorktreeManager(root)")
    fingerprint_at = source.index("fingerprint_primary_checkout(root)")
    begin_at = source.index("promotion_execution_ledger.begin(")
    lock_at = source.index("with _PromotionLock(")

    assert snapshot_at < preflight_at < manager_at < fingerprint_at < begin_at < lock_at

    lock = _promotion_lock(function)
    lock_source = ast.unparse(ast.Module(body=lock.body, type_ignores=[]))
    assert "resolve_live_target_revision" in lock_source
    assert "authorize_persisted_promotion" in lock_source
    assert "_promote_locked" in lock_source


def test_locked_source_order_is_target_read_auth_mutation_and_result_read() -> None:
    function = _promotion_function()
    lock = _promotion_lock(function)
    body_source = ast.unparse(ast.Module(body=lock.body, type_ignores=[]))
    assert "authorize_promotion = authorize_persisted_promotion" in body_source
    assert "candidates=sealed_candidates" in body_source
    calls = [
        _call_name(node)
        for statement in lock.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    ]
    first_target_read = calls.index("resolve_live_target_revision")
    live_auth = calls.index("authorize_promotion")
    mutate = calls.index("_promote_locked")
    result_read = calls.index("resolve_live_target_revision", mutate + 1)
    assert first_target_read < live_auth < mutate < result_read


def test_material_snapshot_and_stale_fences_precede_retained_mutation() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "submitted_candidates = tuple(candidates)" in source
    assert "len(submitted_candidates) != 1" in source
    assert "_snapshot_promotion_candidates(submitted_candidates)" in source
    assert "artifact.base_revision" in source
    assert "live_authorization.live_target_revision" in source
    assert "live promotion authorization differs from persisted start" in source
    assert "stale regeneration requires new evidence and OwnerApproval" in source
    assert source.index("len(submitted_candidates) != 1") < source.index(
        "_snapshot_promotion_candidates(submitted_candidates)"
    ) < source.index("GitWorktreeManager")
    assert source.index("live_authorization.live_target_revision") < source.index(
        "_promote_locked"
    )


def test_restart_paths_do_not_cross_the_lock_twice() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    replay_at = source.index("if not begin.execute:")
    lock_at = source.index("with _PromotionLock(")
    assert replay_at < lock_at
    replay_slice = source[replay_at:lock_at]
    assert "begin.completion.report_dict()" in replay_slice
    assert "pending_reconciliation" in replay_slice
    assert "_promote_locked" not in replay_slice


def test_terminal_paths_return_persisted_reports() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "promotion_execution_ledger.complete(" in source
    assert "return completion.report_dict()" in source
    assert "_complete_refusal(" in source
    assert "_complete_fault(" in source
    assert "primary_checkout_after_sha256=primary_after" in source


def test_effect_inventory_still_observes_the_promotion_guard_anchors() -> None:
    root = Path(__file__).resolve().parents[2]
    report = check_conformance(root)
    missing = [
        finding
        for finding in report.findings
        if finding.code == "registry.guard_anchor_missing"
        and finding.subject == "python.promote_candidates"
    ]
    assert missing == []


def test_dynamic_retained_source_is_exactly_bound_before_exec() -> None:
    source = inspect.getsource(gated_writes)
    verify_at = source.index("_verify_retained_source(_retained_source.read_bytes())")
    exec_at = source.index("exec(")
    delete_at = source.index("del promote_candidates")
    sealed_at = source.index("def promote_candidates(", delete_at)
    assert verify_at < exec_at < delete_at < sealed_at
    assert "_RETAINED_SOURCE_GIT_BLOB_SHA1" in source
    assert "compare_digest" in source
    assert "integrity mismatch" in source


def test_compatibility_module_has_no_second_promotion_authority() -> None:
    source = inspect.getsource(gated_writes)
    assert "_gated_writes_legacy.py.src" in source
    assert "exec(" in source
    assert "del promote_candidates" in source
    assert "_retired_legacy_promotion" in source
    assert "PromotionExecutionLedger" in source
    assert "authorize_promotion = authorize_persisted_promotion" in source
    assert "snapshot_promotion_candidates as _snapshot_promotion_candidates" in source
    assert 'name.startswith("_")' in source
    assert "merge_pull_request" not in source
    assert "git push" not in source
    assert "owner_keyring" in source
