from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.promotion_replay import inspect_promotion_execution


SOURCE = Path("daedalus/kernel/promotion_replay.py")


def test_projection_has_no_writer_or_external_effect_authority() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "open_gate0_spine_writer" not in imported
    assert "SpineLedger" not in imported
    assert "subprocess" not in source
    assert "sqlite3" not in source
    assert "GitWorktreeManager" not in source
    assert "promote_candidates" not in source
    assert "run_in_docker_sandbox" not in source
    assert "begin" not in called
    assert "complete" not in called
    assert "record_intent" not in called
    assert "mark_completed" not in called
    assert "mark_failed" not in called
    assert called & {"_intent_for", "_decode_start", "_decode_completion"} == {
        "_intent_for",
        "_decode_start",
        "_decode_completion",
    }


def test_projection_signature_accepts_no_caller_time_or_checkout_fingerprint() -> None:
    assert tuple(inspect.signature(inspect_promotion_execution).parameters) == (
        "ledger",
        "authorization",
    )


def test_projection_binds_every_persisted_authorization_field_before_completion() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        'expected = _authorization_payload(authorization)',
        '"promotion_id"',
        '"authorization_sha256"',
        '"approval_consumption_sha256"',
        '"candidate_artifact_sha256"',
        '"evidence_packet_sha256"',
        '"source_revision"',
        '"target_ref"',
        '"authorized_target_revision"',
        "if mismatches:",
        "completion = ledger._decode_completion(intent, start)",
        "execute=False",
    )
    for fragment in required:
        assert fragment in source

    assert source.index("if mismatches:") < source.index(
        "completion = ledger._decode_completion(intent, start)"
    )


def test_missing_subject_returns_none_instead_of_creating_a_start() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "if intent is None:\n        return None" in source
    assert "ledger.begin" not in source
