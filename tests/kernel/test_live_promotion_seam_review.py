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


def test_public_seam_retains_old_call_shape_but_requires_all_authorities() -> None:
    signature = inspect.signature(gated_writes.promote_candidates)
    assert signature.parameters["approval_ledger"].default is None
    assert signature.parameters["owner_keyring"].default is None
    assert signature.parameters["promotion_ledger"].default is None
    source = inspect.getsource(gated_writes.promote_candidates)
    assert (
        "approval_ledger is None or not owner_keyring or promotion_ledger is None"
        in source
    )
    assert "_legacy_unpersisted_refusal" in source
    assert "isinstance(promotion_ledger, PromotionLedger)" in source


def test_locked_source_order_persists_start_before_mutation_and_terminal_after() -> None:
    tree = ast.parse(inspect.getsource(gated_writes.promote_candidates))
    function = tree.body[0]
    assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
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
    body_source = ast.unparse(ast.Module(body=promotion_locks[0].body, type_ignores=[]))
    assert "authorize_promotion = authorize_persisted_promotion" in body_source
    calls = [
        _call_name(node)
        for statement in promotion_locks[0].body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call)
    ]
    assert calls.index("resolve_live_target_revision") < calls.index(
        "authorize_promotion"
    ) < calls.index("_primary_checkout_fingerprint") < calls.index(
        "promotion_ledger.begin"
    ) < calls.index("_promote_locked")
    assert calls.index("_promote_locked") < calls.index(
        "promotion_ledger.complete"
    ) < calls.index("promotion_ledger.verify_receipt")


def test_pending_replay_is_fail_closed_and_terminal_replay_is_read_only() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "if not begin_result.execute" in source
    assert "begin_result.completion is not None" in source
    assert "automatic re-execution is forbidden" in source
    assert "promotion_pending_reconciliation" in inspect.getsource(
        gated_writes._pending_response
    )
    assert source.index("if not begin_result.execute") < source.index(
        "_promote_locked"
    )


def test_stale_and_multi_candidate_fences_precede_start_and_mutation() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "len(candidates) != 1" in source
    assert "artifact.base_revision" in source
    assert "authorization.live_target_revision" in source
    assert "stale regeneration requires new evidence and OwnerApproval" in source
    assert source.index("len(candidates) != 1") < source.index("_PromotionLock")
    assert source.index("authorization.live_target_revision") < source.index(
        "promotion_ledger.begin"
    ) < source.index("_promote_locked")


def test_primary_checkout_fingerprint_is_read_only_and_content_sensitive() -> None:
    source = inspect.getsource(gated_writes._primary_checkout_fingerprint)
    runner = inspect.getsource(gated_writes._run_primary_git)
    assert "rev-parse" in source
    assert "--porcelain=v1" in source
    assert "--untracked-files=all" in source
    assert "sha256(status)" in source
    assert "GIT_OPTIONAL_LOCKS" in runner
    assert "--no-optional-locks" in runner
    for forbidden in ("checkout", "reset", "clean", "add", "commit", "merge"):
        assert f'"{forbidden}"' not in source
        assert f'"{forbidden}"' not in runner


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


def test_compatibility_module_has_no_second_legacy_promotion_authority() -> None:
    source = inspect.getsource(gated_writes)
    assert "_gated_writes_legacy.py.src" in source
    assert "exec(" in source
    assert "del promote_candidates" in source
    assert "_retired_legacy_promotion" in source
    assert "PromotionLedger" in source
    assert "automatic re-execution is forbidden" in source
    assert "authorize_promotion = authorize_persisted_promotion" in source
    assert 'name.startswith("_")' in source
    assert "merge_pull_request" not in source
    assert "git push" not in source
    assert "owner_keyring" in source
