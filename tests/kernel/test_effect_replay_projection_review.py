from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.effect_replay import inspect_effect_execution


SOURCE = Path("daedalus/kernel/effect_replay.py")


def test_projection_has_no_writer_or_external_effect_call() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
    assert "BEGIN IMMEDIATE" not in source
    assert "subprocess" not in source
    assert "GitWorktreeManager" not in source
    assert "promote_candidates" not in source
    assert "run_in_docker_sandbox" not in source
    assert "_connect" not in called
    assert "grant" not in called
    assert "begin" not in called
    assert "begin_effect" not in called
    assert "finish" not in called
    assert "finish_effect" not in called
    assert "revoke" not in called


def test_projection_signature_accepts_only_exact_authorization_and_execution() -> None:
    assert tuple(inspect.signature(inspect_effect_execution).parameters) == (
        "authorization",
        "execution",
    )


def test_historical_lease_authentication_occurs_after_strict_start_binding() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    start_index = source.index("start = _start_receipt(")
    row_digest_index = source.index(
        'if str(row["start_receipt_sha256"]) != start.receipt_sha256:'
    )
    verify_index = source.index("verify_effect_lease(", start_index)
    state_index = source.index('state = str(row["state"])')

    assert start_index < row_digest_index < verify_index < state_index
    assert 'now=_parse_utc(start.started_at, "started_at")' in source
    assert (
        "current_kill_switch_generation="
        "authorization.lease.kill_switch_generation"
    ) in source
    assert "kill_switch_generation_reader" not in source


def test_terminal_projection_is_bound_to_start_row_and_canonical_receipt() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        '"lease_sha256": (receipt.lease_sha256, start.lease_sha256)',
        '"execution_id": (receipt.execution_id, start.execution_id)',
        '"start_receipt_sha256": (',
        '"outcome": (receipt.outcome, row_state)',
        "persisted effect terminal precedes its start",
        "canonical_sha(digest_payload)",
        "canonical_json(receipt.to_dict()) != raw",
        'str(row["terminal_receipt_sha256"]) != terminal.receipt_sha256',
        'str(row["finished_at"]) != terminal.finished_at',
    )
    for fragment in required:
        assert fragment in source


def test_started_state_cannot_hide_terminal_material() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'if state == "STARTED":' in source
    assert "started effect row contains terminal material" in source
    assert "terminal effect row is missing terminal material" in source
