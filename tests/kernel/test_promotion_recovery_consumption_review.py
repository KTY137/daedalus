from __future__ import annotations

import ast
import inspect

import daedalus.kernel.promotion_recovery_consumption as consumption


FORBIDDEN_CALLS = {
    "subprocess.run",
    "subprocess.Popen",
    "GitWorktreeManager",
    "terminalize_promotion_effect",
    "promote_candidates",
    "issue_owner_approval",
    "issue_promotion_recovery_decision",
    "grant",
    "begin",
    "finish",
}
FORBIDDEN_PARAMETERS = {
    "callback",
    "provider",
    "writer",
    "outcome",
    "terminal_receipt",
    "repo_root",
}


def _qualified_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value)
        return None if parent is None else f"{parent}.{node.attr}"
    return None


def test_consumption_ledger_has_no_repository_or_recovery_writer_authority() -> None:
    source = inspect.getsource(consumption)
    tree = ast.parse(source)
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert not (set(filter(None, calls)) & FORBIDDEN_CALLS)
    assert all(
        not name.endswith(
            (
                ".grant",
                ".begin",
                ".finish",
                ".promote_candidates",
                ".terminalize_promotion_effect",
            )
        )
        for name in filter(None, calls)
    )
    assert "cancel_effect" not in vars(consumption)
    assert "terminalize_promotion_effect" not in vars(consumption)


def test_public_methods_accept_no_smuggled_effect_authority() -> None:
    for method in (
        consumption.PromotionRecoveryConsumptionLedger.consume,
        consumption.PromotionRecoveryConsumptionLedger.verify_consumption,
        consumption.PromotionRecoveryConsumptionLedger.consumed,
    ):
        signature = inspect.signature(method)
        assert FORBIDDEN_PARAMETERS.isdisjoint(signature.parameters)
        assert all(
            parameter.kind is not inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )


def test_receipt_exposes_no_execution_methods() -> None:
    forbidden = {
        "execute",
        "begin",
        "finish",
        "grant",
        "promote",
        "cancel",
        "terminalize",
    }
    assert forbidden.isdisjoint(vars(consumption.ConsumedPromotionRecoveryDecision))


def test_receipt_parser_requires_exact_fields_without_coercion() -> None:
    source = inspect.getsource(
        consumption.ConsumedPromotionRecoveryDecision.from_dict
    )

    assert "if actual != expected" in source
    assert "if set(verified_payload) != verified_fields" in source
    assert "if set(expectation_payload) != expectation_fields" in source
    assert "str(payload" not in source
    assert "str(verified_payload" not in source
    assert "str(expectation_payload" not in source


def test_consumption_inspection_uses_only_strict_read_only_connections() -> None:
    connector = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger._connect_read_only
    )
    verifier = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger.verify_consumption
    )
    probe = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger.consumed
    )

    assert "?mode=ro" in connector
    assert "uri=True" in connector
    assert 'connection.execute("PRAGMA query_only=ON")' in connector
    assert 'connection.execute("PRAGMA query_only").fetchone()' in connector
    assert "resolve(strict=True)" in connector
    assert "is_symlink()" in connector
    assert "_connect_read_only()" in verifier
    assert "_connect_writer()" not in verifier
    assert "_connect_read_only()" in probe
    assert "_connect_writer()" not in probe


def test_consume_revalidates_before_and_inside_immediate_transaction() -> None:
    source = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger.consume
    )
    tree = ast.parse(source)
    calls = [
        _qualified_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("verify_promotion_recovery_decision") == 2
    preflight_offset = source.index("preflight = verify_promotion_recovery_decision")
    begin_offset = source.index('connection.execute("BEGIN IMMEDIATE")')
    transaction_verify_offset = source.index(
        "verified = verify_promotion_recovery_decision"
    )
    insert_offset = source.index(
        "INSERT INTO promotion_recovery_consumptions_v1"
    )
    commit_offset = source.index('connection.execute("COMMIT")')

    assert preflight_offset < begin_offset
    assert begin_offset < transaction_verify_offset < insert_offset < commit_offset
    assert "verified != preflight" in source
    assert "expectation != preflight_expectation" in source
    assert "persistence_at < transaction_at" in source
    assert "consumed_at >= verified.expires_at" in source


def test_schema_has_independent_one_use_subject_constraints() -> None:
    source = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger._initialize
    )

    assert "decision_sha256 TEXT PRIMARY KEY" in source
    assert "decision_id TEXT NOT NULL UNIQUE" in source
    assert "promotion_authorization_sha256 TEXT NOT NULL UNIQUE" in source
    assert "recovery_plan_sha256 TEXT NOT NULL UNIQUE" in source
    assert "effect_start_receipt_sha256 TEXT NOT NULL UNIQUE" in source
    assert "UNIQUE(owner_id, key_id, nonce)" in source


def test_verify_consumption_checks_every_redundant_security_column() -> None:
    source = inspect.getsource(
        consumption.PromotionRecoveryConsumptionLedger.verify_consumption
    )
    required = {
        'row["decision_sha256"]',
        'row["decision_id"]',
        'row["owner_id"]',
        'row["key_id"]',
        'row["nonce"]',
        'row["operation"]',
        'row["promotion_authorization_sha256"]',
        'row["recovery_plan_sha256"]',
        'row["effect_start_receipt_sha256"]',
        'row["source_revision"]',
        'row["issued_at"]',
        'row["expires_at"]',
        'row["signature_sha256"]',
        'row["expectation_sha256"]',
        'row["verified_sha256"]',
        'row["consumed_at"]',
        'row["consumption_sha256"]',
        'row["decision_json"]',
        'row["expectation_json"]',
        'row["consumption_json"]',
    }

    assert all(name in source for name in required)
    assert source.count("hmac.compare_digest") == 1
    assert "_MAX_RECOVERY_DECISION_TTL" in source
