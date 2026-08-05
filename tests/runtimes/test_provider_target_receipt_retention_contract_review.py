from __future__ import annotations

import ast
import inspect

from daedalus.runtimes import provider_target_receipt_retention_contract as contract


def _names(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            values.add(node.id)
        elif isinstance(node, ast.Attribute):
            values.add(node.attr)
    return values


def _calls(tree: ast.AST) -> set[str]:
    values: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            values.add(function.id)
        elif isinstance(function, ast.Attribute):
            values.add(function.attr)
    return values


def test_independent_review_finds_no_effect_execution_or_persistence() -> None:
    source = inspect.getsource(contract)
    tree = ast.parse(source)
    names = _names(tree)
    calls = _calls(tree)

    assert not (
        {
            "sqlite3",
            "subprocess",
            "socket",
            "requests",
            "urllib",
            "ProviderTargetReceiptLedger",
            "SourceTreeStore",
            "SpineLedger",
            "EffectLeaseLedger",
        }
        & names
    )
    assert not (
        {
            "begin_effect",
            "put_bytes",
            "record_intent",
            "mark_completed",
            "retain",
            "execute",
            "commit",
            "merge_pull_request",
        }
        & calls
    )


def test_independent_review_confirms_exact_non_authority_wire_claims() -> None:
    source = inspect.getsource(contract)
    for claim in (
        '"provider_execution_allowed": False',
        '"retention_effect_started": False',
        '"primary_checkout_disjointness_verified": False',
    ):
        assert claim in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "automatic promotion" not in source.lower()


def test_independent_review_confirms_separate_least_privilege_effect() -> None:
    source = inspect.getsource(contract._validate_retention_effect_scope)
    for required in (
        "type(receipt) is not ProviderExecutableTargetVerificationReceipt",
        "type(execution) is not EffectExecutionRequest",
        "type(effect_lease) is not EffectLease",
        "RETENTION_ENTRYPOINT",
        '("filesystem_write",)',
        "execution.writable_paths",
        "effect_lease.effect_scope.writable_paths",
        "effect_lease.provenance.source_revision",
        "execution.kill_switch_generation",
        "effect_lease.kill_switch_generation",
        "not execution.kill_switch_ref",
        "not effect_lease.effect_scope.kill_switch_ref",
        "effect_lease.digest == receipt.lease_sha256",
        "execution.execution_id == receipt.execution_id",
        "execution.idempotency_key == receipt.idempotency_key",
    ):
        assert required in source


def test_independent_review_confirms_inventory_is_bound_not_trusted() -> None:
    source = inspect.getsource(contract)
    assert "retention_inventory_sha256" in source
    assert "retention_inventory_source_sha256" in source
    assert "provider_target_receipt_retention_inventory" not in source
    assert "verify the inventory artifact" in source


def test_public_authorization_api_only_returns_guard_evidence() -> None:
    signature = inspect.signature(
        contract.authorize_provider_target_receipt_retention_operation
    )
    assert list(signature.parameters) == [
        "authority",
        "expected_authority_id",
        "authority_keyring",
        "expected_subject",
        "at",
    ]
    source = inspect.getsource(
        contract.authorize_provider_target_receipt_retention_operation
    )
    assert "verify_provider_target_receipt_retention_operation_authority" in source
    assert "GuardDecision" in source
    assert "allowed=True" in source
    assert "authority_sha256=" in source
    assert "subject_sha256=" in source


def test_exports_do_not_expose_execution_or_promotion_surface() -> None:
    exported = set(contract.__all__)
    assert "ProviderTargetReceiptLedger" not in exported
    assert "EffectLeaseLedger" not in exported
    assert "OwnerApproval" not in exported
    assert "PromotionReceipt" not in exported
    assert all("merge" not in name.lower() for name in exported)
    assert all("promot" not in name.lower() for name in exported)
