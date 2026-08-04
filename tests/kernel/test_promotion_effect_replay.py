from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayError,
    inspect_promotion_effect_execution,
)

_FIXTURE_PATH = Path(__file__).with_name("test_promotion_effect_capability.py")
_SPEC = importlib.util.spec_from_file_location(
    "_promotion_effect_capability_fixture",
    _FIXTURE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
build_capability = _FIXTURE.build_capability


def _write(capability, sql: str, parameters: tuple[object, ...] = ()) -> None:
    with sqlite3.connect(capability.authorization.effect_ledger.path) as conn:
        conn.execute(sql, parameters)
        conn.commit()


def test_absent_and_granted_without_execution_return_none(tmp_path) -> None:
    capability = build_capability(tmp_path)
    assert inspect_promotion_effect_execution(capability) is None

    capability.grant()
    assert inspect_promotion_effect_execution(capability) is None


def test_pending_and_terminal_execution_are_projected_exactly(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    started = capability.begin()

    pending = inspect_promotion_effect_execution(capability)
    assert pending is not None
    assert pending.start == started.receipt
    assert pending.state == "STARTED"
    assert pending.terminal is None
    assert pending.pending_reconciliation is True

    terminal = capability.finish(
        started.receipt,
        outcome="completed",
        output_digests=("2" * 64,),
        detail_sha256="3" * 64,
    )
    replay = inspect_promotion_effect_execution(capability)
    assert replay is not None
    assert replay.start == started.receipt
    assert replay.state == "COMPLETED"
    assert replay.terminal == terminal
    assert replay.pending_reconciliation is False


def test_projection_never_calls_writer_connection_factory(tmp_path, monkeypatch) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    started = capability.begin()

    def forbidden_writer_connection():
        raise AssertionError("writer connection factory must not be called")

    monkeypatch.setattr(
        capability.authorization.effect_ledger,
        "_connect",
        forbidden_writer_connection,
    )
    replay = inspect_promotion_effect_execution(capability)
    assert replay is not None
    assert replay.start == started.receipt
    assert replay.state == "STARTED"


def test_changed_execution_request_bytes_are_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    _write(
        capability,
        "UPDATE effect_executions SET request_json='{}' WHERE execution_id=?",
        (capability.execution.execution_id,),
    )

    with pytest.raises(PromotionEffectReplayError, match="row.request_json"):
        inspect_promotion_effect_execution(capability)


def test_changed_lease_bytes_are_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    _write(
        capability,
        "UPDATE effect_leases SET lease_json='{}' WHERE lease_sha256=?",
        (capability.authorization.lease.digest,),
    )

    with pytest.raises(PromotionEffectReplayError, match="lease_json"):
        inspect_promotion_effect_execution(capability)


def test_pending_row_cannot_retain_terminal_material(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    _write(
        capability,
        "UPDATE effect_executions SET finished_at=? WHERE execution_id=?",
        (
            "2026-08-04T00:00:00.000000+00:00",
            capability.execution.execution_id,
        ),
    )

    with pytest.raises(PromotionEffectReplayError, match="pending effect"):
        inspect_promotion_effect_execution(capability)


def test_duplicate_terminal_json_key_is_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    started = capability.begin()
    terminal = capability.finish(started.receipt, outcome="failed")
    path = capability.authorization.effect_ledger.path
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT terminal_receipt_json FROM effect_executions WHERE execution_id=?",
            (capability.execution.execution_id,),
        ).fetchone()[0]
        duplicate = (
            raw[:-1]
            + ',"receipt_sha256":"'
            + terminal.receipt_sha256
            + '"}'
        )
        conn.execute(
            "UPDATE effect_executions SET terminal_receipt_json=? WHERE execution_id=?",
            (duplicate, capability.execution.execution_id),
        )
        conn.commit()

    with pytest.raises(PromotionEffectReplayError, match="duplicate key"):
        inspect_promotion_effect_execution(capability)


def test_terminal_state_substitution_is_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    started = capability.begin()
    capability.finish(started.receipt, outcome="failed")
    _write(
        capability,
        "UPDATE effect_executions SET state='COMPLETED' WHERE execution_id=?",
        (capability.execution.execution_id,),
    )

    with pytest.raises(PromotionEffectReplayError, match="state"):
        inspect_promotion_effect_execution(capability)


def test_unknown_state_is_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    _write(
        capability,
        "UPDATE effect_executions SET state='RETRY' WHERE execution_id=?",
        (capability.execution.execution_id,),
    )

    with pytest.raises(PromotionEffectReplayError, match="unknown state"):
        inspect_promotion_effect_execution(capability)


def test_non_capability_is_refused_before_database_access() -> None:
    with pytest.raises(TypeError, match="PromotionEffectCapability"):
        inspect_promotion_effect_execution(object())
