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


def test_public_seam_keeps_old_call_shape_but_requires_all_persisted_authorities() -> None:
    signature = inspect.signature(gated_writes.promote_candidates)
    assert signature.parameters["approval_ledger"].default is None
    assert signature.parameters["promotion_ledger"].default is None
    assert signature.parameters["owner_keyring"].default is None
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "approval_ledger is None or promotion_ledger is None or not owner_keyring" in source
    assert "_legacy_unpersisted_refusal" in source
    assert "promotion_ledger must be PromotionLedger" in source


def test_locked_order_is_auth_fingerprint_start_mutation_fingerprint_receipt() -> None:
    tree = ast.parse(inspect.getsource(gated_writes.promote_candidates))
    function = tree.body[0]
    assert isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
    promotion_locks = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.With)
        and any(
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
    first_fingerprint = calls.index("_primary_checkout_fingerprint")
    start = calls.index("promotion_ledger.begin")
    mutation = calls.index("_promote_locked")
    second_fingerprint = calls.index("_primary_checkout_fingerprint", first_fingerprint + 1)
    receipt = calls.index("promotion_ledger.complete")
    assert calls.index("resolve_live_target_revision") < calls.index(
        "authorize_promotion"
    ) < first_fingerprint < start < mutation < second_fingerprint < receipt


def test_every_exact_start_replay_is_non_executable() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "if not begin.execute:" in source
    assert "if begin.completion is not None:" in source
    assert "return _reconcile_pending(" in source
    assert source.index("if not begin.execute:") < source.index("_promote_locked(")


def test_stale_cardinality_and_primary_fences_precede_retained_mutation() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    assert "len(candidates) != 1" in source
    assert "artifact.base_revision" in source
    assert "authorization.live_target_revision" in source
    assert "stale regeneration requires new evidence and OwnerApproval" in source
    assert source.index("len(candidates) != 1") < source.index("_PromotionLock")
    assert source.index("authorization.live_target_revision") < source.index(
        "_primary_checkout_fingerprint"
    ) < source.index("promotion_ledger.begin") < source.index("_promote_locked")


def test_primary_fingerprint_is_read_only_complete_and_double_sampled() -> None:
    source = inspect.getsource(gated_writes._primary_checkout_fingerprint)
    inventory_source = inspect.getsource(gated_writes._primary_inventory)
    path_source = inspect.getsource(gated_writes._primary_path_state)
    assert "first = _primary_inventory(root)" in source
    assert "second = _primary_inventory(root)" in source
    assert "if first != second" in source
    assert "rev-parse" in inventory_source
    assert "ls-files" in inventory_source
    assert "--stage" in inventory_source
    assert "--others" in inventory_source
    assert "--exclude-standard" in inventory_source
    assert "--porcelain=v2" in inventory_source
    assert "--ignore-submodules=none" in inventory_source
    assert "content_sha256" in path_source
    assert "O_NOFOLLOW" in path_source
    assert "os.lstat" in path_source
    for forbidden in ("checkout", "reset", "clean", "add", "commit", "merge", "push"):
        assert f'"{forbidden}"' not in inventory_source


def test_pending_reconciliation_never_calls_the_mutation_helper() -> None:
    source = inspect.getsource(gated_writes._reconcile_pending)
    assert "_promote_locked" not in source
    assert "automatic execution was refused" in source
    assert "outcome=\"faulted\"" in source
    assert "promotion_ledger.complete" in source


def test_deterministic_branch_and_ids_derive_only_from_authorization() -> None:
    assert gated_writes._planned_integration_branch(
        type("Auth", (), {"authorization_sha256": "a" * 64})()
    ) == ("kairos-integration-" + "a" * 40)
    assert "uuid" not in inspect.getsource(gated_writes._promote_locked)
    assert "integration_branch=integration_branch" in inspect.getsource(
        gated_writes._promote_locked
    )


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
    delete_promotion_at = source.index("del promote_candidates")
    delete_locked_at = source.index("del _promote_locked")
    sealed_at = source.index("def promote_candidates(", delete_promotion_at)
    assert verify_at < exec_at < delete_promotion_at < sealed_at
    assert verify_at < exec_at < delete_locked_at < sealed_at
    assert "_RETAINED_SOURCE_GIT_BLOB_SHA1" in source
    assert "compare_digest" in source
    assert "integrity mismatch" in source


def test_compatibility_module_has_no_second_legacy_promotion_authority() -> None:
    source = inspect.getsource(gated_writes)
    assert "_gated_writes_legacy.py.src" in source
    assert "del promote_candidates" in source
    assert "del _promote_locked" in source
    assert "_retired_legacy_promotion" in source
    assert "persisted ApprovalLedger, PromotionLedger and owner keyring are mandatory" in source
    assert "authorize_promotion = authorize_persisted_promotion" in source
    assert 'name.startswith("_")' in source
    assert "merge_pull_request" not in source
    assert "git push" not in source
    assert "owner_keyring" in source
