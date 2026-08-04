from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.kernel.promotion_effect_entry as entry_module
from daedalus.kernel.effects import LeasedEffectStartReceipt
from daedalus.kernel.promotion_effect_entry import (
    PromotionEffectEntryMismatch,
    prepare_promotion_effect_entry,
)
from daedalus.kernel.promotion_effect_replay import PromotionEffectReplayDecision
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger


LEASE_SHA = "a" * 64
REPORT_SHA = "b" * 64
DETAIL_SHA = "c" * 64
START_SHA = "d" * 64
STARTED_AT = "2026-08-04T05:00:00.000000+00:00"


def start_receipt() -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=LEASE_SHA,
        execution_id="promotion-1",
        idempotency_key="promotion-authorization-1",
        execution_request_sha256="e" * 64,
        boundary_receipt_sha256="f" * 64,
        started_at=STARTED_AT,
        receipt_sha256=START_SHA,
    )


def pending_decision(receipt=None, *, promotion=None):
    actual = receipt or start_receipt()
    return PromotionEffectReplayDecision(
        action="pending_reconciliation",
        effect=SimpleNamespace(
            start_receipt=actual,
            terminal_receipt=None,
            state="STARTED",
        ),
        promotion=promotion,
    )


def replay_decision():
    terminal = SimpleNamespace(
        outcome="COMPLETED",
        output_digests=(REPORT_SHA,),
        detail_sha256=DETAIL_SHA,
    )
    return PromotionEffectReplayDecision(
        action="replay_promotion_report",
        effect=SimpleNamespace(
            start_receipt=start_receipt(),
            terminal_receipt=terminal,
            state="COMPLETED",
        ),
        promotion=SimpleNamespace(completion=object()),
        expected_effect_outcome="COMPLETED",
        expected_output_digests=(REPORT_SHA,),
        expected_detail_sha256=DETAIL_SHA,
    )


def terminal_without_report_decision():
    return PromotionEffectReplayDecision(
        action="replay_effect_terminal_without_report",
        effect=SimpleNamespace(
            start_receipt=start_receipt(),
            terminal_receipt=SimpleNamespace(outcome="FAILED"),
            state="FAILED",
        ),
        promotion=None,
    )


def inert_capability(tmp_path: Path) -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(
        capability,
        "authorization",
        SimpleNamespace(
            effect_ledger=SimpleNamespace(path=tmp_path / "effects.sqlite3"),
            lease=SimpleNamespace(digest=LEASE_SHA, lease_id="lease-1"),
        ),
    )
    object.__setattr__(capability, "execution", object())
    object.__setattr__(capability, "promotion", object())
    return capability


def inert_ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


def install_begin(monkeypatch, *, execute: bool, receipt=None, calls=None):
    actual = receipt or start_receipt()
    counters = calls if calls is not None else []

    def grant(self):
        counters.append("grant")

    def begin(self):
        counters.append("begin")
        return SimpleNamespace(execute=execute, receipt=actual)

    monkeypatch.setattr(PromotionEffectCapability, "grant", grant)
    monkeypatch.setattr(PromotionEffectCapability, "begin", begin)
    return counters, actual


def test_absent_lease_fresh_start_is_the_only_execute_action(
    tmp_path,
    monkeypatch,
) -> None:
    capability = inert_capability(tmp_path)
    ledger = inert_ledger()
    calls, receipt = install_begin(monkeypatch, execute=True)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: False)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_execution",
        lambda _ledger, _promotion: None,
    )
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: pending_decision(receipt),
    )

    result = prepare_promotion_effect_entry(capability, ledger)

    assert result.action == "execute_promotion"
    assert result.permits_promotion_execution is True
    assert result.start_receipt == receipt
    assert calls == ["grant", "begin"]


def test_retained_promotion_before_lease_persistence_is_refused(
    tmp_path,
    monkeypatch,
) -> None:
    capability = inert_capability(tmp_path)
    calls, _receipt = install_begin(monkeypatch, execute=True)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: False)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_execution",
        lambda _ledger, _promotion: object(),
    )

    with pytest.raises(PromotionEffectEntryMismatch, match="before exact Effect-Lease"):
        prepare_promotion_effect_entry(capability, inert_ledger())
    assert calls == []


def test_existing_pending_state_never_calls_grant_or_begin(tmp_path, monkeypatch) -> None:
    capability = inert_capability(tmp_path)
    calls, _receipt = install_begin(monkeypatch, execute=True)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: True)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: pending_decision(),
    )

    result = prepare_promotion_effect_entry(capability, inert_ledger())

    assert result.action == "pending_reconciliation"
    assert result.permits_promotion_execution is False
    assert calls == []


def test_exact_begin_race_returns_pending_not_execute(tmp_path, monkeypatch) -> None:
    capability = inert_capability(tmp_path)
    calls, receipt = install_begin(monkeypatch, execute=False)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: True)
    decisions = iter(
        [
            PromotionEffectReplayDecision(action="fresh", effect=None, promotion=None),
            pending_decision(receipt),
        ]
    )
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: next(decisions),
    )

    result = prepare_promotion_effect_entry(capability, inert_ledger())

    assert result.action == "pending_reconciliation"
    assert result.permits_promotion_execution is False
    assert calls == ["grant", "begin"]


def test_retained_terminal_is_replayed_without_entry_write(tmp_path, monkeypatch) -> None:
    capability = inert_capability(tmp_path)
    calls, _receipt = install_begin(monkeypatch, execute=True)
    decision = replay_decision()
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: True)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: decision,
    )

    result = prepare_promotion_effect_entry(capability, inert_ledger())

    assert result.action == "replay_promotion_report"
    assert result.decision is decision
    assert result.reconciliation is None
    assert calls == []


def test_terminal_reconciliation_is_routed_without_promotion_execution(
    tmp_path,
    monkeypatch,
) -> None:
    capability = inert_capability(tmp_path)
    calls, _receipt = install_begin(monkeypatch, execute=True)
    reconcile_decision = PromotionEffectReplayDecision(
        action="reconcile_effect_terminal",
        effect=SimpleNamespace(
            start_receipt=start_receipt(),
            terminal_receipt=None,
            state="STARTED",
        ),
        promotion=SimpleNamespace(completion=object()),
        expected_effect_outcome="COMPLETED",
        expected_output_digests=(REPORT_SHA,),
        expected_detail_sha256=DETAIL_SHA,
    )
    replay = replay_decision()
    reconciliation = SimpleNamespace(decision=replay)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: True)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: reconcile_decision,
    )
    monkeypatch.setattr(
        entry_module,
        "reconcile_promotion_effect_terminal",
        lambda _c, _l: reconciliation,
    )

    result = prepare_promotion_effect_entry(capability, inert_ledger())

    assert result.action == "replay_promotion_report"
    assert result.reconciliation is reconciliation
    assert result.decision is replay
    assert calls == []


def test_failed_prepromotion_terminal_replays_without_report_or_execution(
    tmp_path,
    monkeypatch,
) -> None:
    capability = inert_capability(tmp_path)
    calls, _receipt = install_begin(monkeypatch, execute=True)
    decision = terminal_without_report_decision()
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: True)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: decision,
    )

    result = prepare_promotion_effect_entry(capability, inert_ledger())

    assert result.action == "replay_effect_terminal_without_report"
    assert result.permits_promotion_execution is False
    assert calls == []


def test_fresh_start_postcheck_refuses_existing_promotion(tmp_path, monkeypatch) -> None:
    capability = inert_capability(tmp_path)
    calls, receipt = install_begin(monkeypatch, execute=True)
    monkeypatch.setattr(entry_module, "_exact_lease_is_persisted", lambda _c: False)
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_execution",
        lambda _ledger, _promotion: None,
    )
    monkeypatch.setattr(
        entry_module,
        "inspect_promotion_effect_replay",
        lambda _c, _l: pending_decision(receipt, promotion=object()),
    )

    with pytest.raises(PromotionEffectEntryMismatch, match="isolated executable"):
        prepare_promotion_effect_entry(capability, inert_ledger())
    assert calls == ["grant", "begin"]


def create_presence_db(path: Path, rows=()) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE effect_leases (lease_sha256 TEXT, lease_id TEXT)"
        )
        connection.executemany(
            "INSERT INTO effect_leases(lease_sha256, lease_id) VALUES (?, ?)",
            rows,
        )


def test_read_only_presence_distinguishes_absent_exact_and_collision(tmp_path) -> None:
    absent = inert_capability(tmp_path / "absent")
    assert entry_module._exact_lease_is_persisted(absent) is False

    exact_dir = tmp_path / "exact"
    exact_dir.mkdir()
    exact = inert_capability(exact_dir)
    create_presence_db(exact.authorization.effect_ledger.path, [(LEASE_SHA, "lease-1")])
    assert entry_module._exact_lease_is_persisted(exact) is True

    collision_dir = tmp_path / "collision"
    collision_dir.mkdir()
    collision = inert_capability(collision_dir)
    create_presence_db(
        collision.authorization.effect_ledger.path,
        [("9" * 64, "lease-1")],
    )
    with pytest.raises(PromotionEffectEntryMismatch, match="collides"):
        entry_module._exact_lease_is_persisted(collision)
