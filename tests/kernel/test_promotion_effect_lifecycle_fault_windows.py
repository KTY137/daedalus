from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from daedalus.kairos import promotion_effect_lifecycle as lifecycle
from daedalus.kernel.promotion_effect_replay import inspect_promotion_effect_execution
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import PromotionReconciliationDisposition


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_effect_lifecycle_window_capability_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_effect_lifecycle_window_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
successful_report = _PROMOTION.successful_report
PRIMARY = _PROMOTION.PRIMARY
INTEGRATION = _PROMOTION.INTEGRATION


def _call(capability, ledger: PromotionExecutionLedger):
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


def test_grant_only_crash_window_can_continue_with_exact_lease_replay(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    assert inspect_promotion_effect_execution(capability) is None
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    monkeypatch.setattr(lifecycle, "_preauthorize_exact_subject", lambda **_: None)

    def delegate(*args, **kwargs):
        effect = inspect_promotion_effect_execution(capability)
        assert effect is not None and effect.state == "STARTED"
        begin = ledger.begin(
            auth,
            start_id="promotion-start-1",
            primary_checkout_before_sha256=PRIMARY,
        )
        completion = ledger.complete(
            begin.start,
            receipt_id="promotion-receipt-1",
            outcome="succeeded",
            report=successful_report(auth),
            integration_branch="integration/promotion-1",
            integration_revision=INTEGRATION,
            primary_checkout_after_sha256=PRIMARY,
        )
        return completion.report_dict()

    monkeypatch.setattr(lifecycle.gated_writes, "promote_candidates", delegate)
    try:
        report = _call(capability, ledger)
        assert report["promotion_effect_lifecycle"]["disposition"] == (
            PromotionReconciliationDisposition.COMPLETE.value
        )
        assert report["promotion_effect_lifecycle"]["automatic_execution_allowed"] is False
    finally:
        ledger.close()
