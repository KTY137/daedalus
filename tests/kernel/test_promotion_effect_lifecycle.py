from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from daedalus.kairos import promotion_effect_lifecycle as lifecycle
from daedalus.kernel.promotion_effect_replay import inspect_promotion_effect_execution
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    PromotionReconciliationDisposition,
    inspect_promotion_reconciliation,
)


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_effect_lifecycle_capability_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_effect_lifecycle_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION


def _call(capability, ledger: PromotionExecutionLedger) -> dict[str, Any]:
    return lifecycle.promote_candidates_with_effect_lifecycle(
        ".",
        [object()],
        project="project-1",
        availability={},
        consumed_approval=object(),
        evidence_packet=object(),
        target_ref=capability.promotion.target_ref,
        promotion_effect_capability=capability,
        approval_ledger=object(),
        owner_keyring={("owner", "key"): b"secret"},
        promotion_execution_ledger=ledger,
    )


def _persist_success(
    capability,
    ledger: PromotionExecutionLedger,
    *,
    returned_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    effect = inspect_promotion_effect_execution(capability)
    assert effect is not None
    assert effect.state == "STARTED"
    assert effect.terminal is None
    begin = ledger.begin(
        capability.promotion,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    completion = ledger.complete(
        begin.start,
        receipt_id="promotion-receipt-1",
        outcome="succeeded",
        report=successful_report(capability.promotion),
        integration_branch="integration/promotion-1",
        integration_revision=INTEGRATION,
        primary_checkout_after_sha256=PRIMARY,
    )
    return returned_report or completion.report_dict()


def test_fresh_execution_persists_effect_start_before_delegate_and_completes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    calls = 0

    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)

    def delegate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _persist_success(capability, ledger)

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", delegate)
    try:
        report = _call(capability, ledger)
        assert calls == 1
        status = report["promotion_effect_lifecycle"]
        assert status["schema"] == "daedalus-promotion-effect-lifecycle/1"
        assert status["disposition"] == "complete"
        assert status["automatic_execution_allowed"] is False
        assert status["effect_start_receipt_sha256"]
        assert status["effect_terminal_receipt_sha256"]
        assert status["promotion_start_sha256"]
        assert status["promotion_terminal_sha256"]
        assert report["promoted"] == successful_report(auth)["promoted"]
        assert (
            inspect_promotion_reconciliation(capability, ledger).disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
    finally:
        ledger.close()


def test_complete_restart_replays_retained_report_without_delegate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)
    monkeypatch.setattr(
        lifecycle.gated_writes,
        "promote_candidates",
        lambda *args, **kwargs: _persist_success(capability, ledger),
    )
    try:
        first = _call(capability, ledger)

        def forbidden(*args, **kwargs):
            raise AssertionError("completed promotion must not execute again")

        monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", forbidden)
        second = _call(capability, ledger)
        assert second["promoted"] == first["promoted"]
        assert (
            second["promotion_effect_lifecycle"]["effect_terminal_replayed"]
            is True
        )
    finally:
        ledger.close()


def test_terminal_required_restart_terminalizes_without_delegate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    _persist_success(capability, ledger)

    def forbidden(*args, **kwargs):
        raise AssertionError("terminal reconciliation must not execute promotion")

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", forbidden)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_lifecycle"]["disposition"] == "complete"
        assert (
            inspect_promotion_reconciliation(capability, ledger).disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
    finally:
        ledger.close()


@pytest.mark.parametrize("state", ["effect-only", "promotion-pending"])
def test_pending_restart_never_calls_delegate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    if state == "promotion-pending":
        ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )

    def forbidden(*args, **kwargs):
        raise AssertionError("pending promotion must not execute automatically")

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", forbidden)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_pending_reconciliation"] is True
        assert report["promoted"] == []
        assert report["promotion_effect_lifecycle"]["automatic_execution_allowed"] is False
        assert report["promotion_effect_lifecycle"]["disposition"] == (
            "effect-only-pending-reconciliation"
            if state == "effect-only"
            else "promotion-pending-reconciliation"
        )
    finally:
        ledger.close()


def test_preauthorization_failure_occurs_before_lease_or_execution_start(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")

    def refuse(**kwargs):
        raise lifecycle.PromotionEffectLifecycleError("subject mismatch")

    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", refuse)
    try:
        with pytest.raises(lifecycle.PromotionEffectLifecycleError, match="subject mismatch"):
            _call(capability, ledger)
        assert inspect_promotion_effect_execution(capability) is None
        assert (
            inspect_promotion_reconciliation(capability, ledger).disposition
            is PromotionReconciliationDisposition.FRESH
        )
    finally:
        ledger.close()


def test_delegate_exception_leaves_effect_start_pending_without_fake_terminal(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)

    def explode(*args, **kwargs):
        raise RuntimeError("injected delegate failure")

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", explode)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_pending_reconciliation"] is True
        assert report["promotion_effect_error"]["type"] == "RuntimeError"
        projection = inspect_promotion_reconciliation(capability, ledger)
        assert (
            projection.disposition
            is PromotionReconciliationDisposition.EFFECT_ONLY_PENDING
        )
        assert projection.effect_execution is not None
        assert projection.effect_execution.terminal is None
    finally:
        ledger.close()


def test_delegate_return_cannot_replace_retained_terminal_report(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)
    forged = {
        "promoted": [{"task_id": "forged"}],
        "refused": [],
        "authorization": {"forged": True},
    }
    monkeypatch.setattr(
        lifecycle.gated_writes,
        "promote_candidates",
        lambda *args, **kwargs: _persist_success(
            capability,
            ledger,
            returned_report=forged,
        ),
    )
    try:
        report = _call(capability, ledger)
        assert report["promoted"] != forged["promoted"]
        assert report["promoted"] == successful_report(auth)["promoted"]
        assert report["authorization"] == auth.to_dict()
    finally:
        ledger.close()


def test_wrong_types_refuse_before_lifecycle_access() -> None:
    with pytest.raises(TypeError, match="PromotionEffectCapability"):
        lifecycle.promote_candidates_with_effect_lifecycle(
            ".",
            [],
            project=None,
            availability={},
            consumed_approval=object(),
            evidence_packet=object(),
            target_ref="refs-heads-main",
            promotion_effect_capability=object(),
            approval_ledger=object(),
            owner_keyring={("owner", "key"): b"secret"},
            promotion_execution_ledger=object(),
        )
