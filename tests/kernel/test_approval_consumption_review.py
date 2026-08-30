# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect

from daedalus.kernel import approvals


SOURCE = inspect.getsource(approvals)
TREE = ast.parse(SOURCE)


def _class_method(class_name: str, method_name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for member in node.body:
                if isinstance(member, ast.FunctionDef) and member.name == method_name:
                    return member
    raise AssertionError(f"missing {class_name}.{method_name}")


def _source(node: ast.AST) -> str:
    segment = ast.get_source_segment(SOURCE, node)
    assert segment is not None
    return segment


def test_consumption_api_cannot_accept_verified_or_caller_clock() -> None:
    consume = _class_method("ApprovalLedger", "consume")
    positional = [arg.arg for arg in consume.args.args]
    keyword_only = [arg.arg for arg in consume.args.kwonlyargs]
    assert positional == ["self", "approval"]
    assert keyword_only == ["keyring", "expectation", "promotion_id"]
    assert "now" not in positional + keyword_only
    assert "consumed_at" not in positional + keyword_only
    approval_arg = consume.args.args[1]
    assert isinstance(approval_arg.annotation, ast.Name)
    assert approval_arg.annotation.id == "OwnerApproval"
    text = _source(consume)
    assert "isinstance(approval, OwnerApproval)" in text


def test_transaction_reauthenticates_before_persisting_receipt() -> None:
    text = _source(_class_method("ApprovalLedger", "consume"))
    begin = text.index('connection.execute("BEGIN IMMEDIATE")')
    first_verify = text.index("verify_owner_approval(")
    second_verify = text.index("verify_owner_approval(", first_verify + 1)
    persistence_clock = text.index("persistence_at = self._now()")
    insert = text.index("INSERT INTO owner_approval_consumptions_v2")
    commit = text.index('connection.execute("COMMIT")')
    assert first_verify < begin < second_verify < persistence_clock < insert < commit
    assert "if persistence_at < transaction_at:" in text
    assert "if consumed_at >= verified.expires_at:" in text


def test_persisted_verifier_reauthenticates_bytes_and_exact_row_identity() -> None:
    text = _source(_class_method("ApprovalLedger", "verify_consumption"))
    required = (
        "OwnerApproval.from_dict",
        "ApprovalExpectation(**expectation_payload)",
        "hmac.compare_digest",
        "canonical_json(receipt.to_dict())",
        'row["approval_sha256"]',
        'row["expectation_sha256"]',
        'row["promotion_id"]',
        'row["capability_sha256"]',
    )
    for seam in required:
        assert seam in text


def test_approval_authority_has_no_git_provider_or_promotion_effects() -> None:
    forbidden_import_roots = {
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".")[0] for alias in node.names}
            assert not (roots & forbidden_import_roots)
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden_import_roots
            assert not node.module.startswith("daedalus.providers")
            assert not node.module.startswith("daedalus.kairos")
    lowered = SOURCE.lower()
    assert "gitworktreemanager" not in lowered
    assert "promote_candidates" not in lowered
    assert "promotionreceipt" not in lowered


def test_legacy_authority_is_detected_after_v2_schema_creation() -> None:
    text = _source(_class_method("ApprovalLedger", "_initialize"))
    assert text.index("CREATE TABLE IF NOT EXISTS owner_approval_consumptions_v2") < text.index(
        "legacy_count"
    )
    assert "legacy approval consumptions require explicit migration" in text
