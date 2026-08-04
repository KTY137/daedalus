from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import PromotionReconciliationDisposition
from daedalus.kernel.promotion_terminalization import terminalize_promotion_effect


def _load(name: str, filename: str):
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_EFFECT = _load(
    "_promotion_terminalization_outcome_effect_fixture",
    "test_promotion_effect_capability.py",
)
_PROMOTION = _load(
    "_promotion_terminalization_outcome_execution_fixture",
    "test_promotion_replay_projection.py",
)
build_capability = _EFFECT.build_capability
authorization = _PROMOTION.authorization
PRIMARY = _PROMOTION.PRIMARY


def _report(auth, outcome: str) -> dict[str, object]:
    report: dict[str, object] = {
        "promoted": [],
        "refused": [],
        "not_gated": [],
        "integration_branch": None,
        "integration_revision": None,
        "authorization": auth.to_dict(),
        "cleanup_error": None,
    }
    if outcome == "refused":
        report["refused"] = [{"task_id": "task-1", "reason": "policy-refusal"}]
    elif outcome == "faulted":
        report["fault"] = {"type": "injected-test-fault"}
    else:
        raise AssertionError("unsupported test outcome")
    return report


@pytest.mark.parametrize(
    ("promotion_outcome", "effect_outcome"),
    [
        ("refused", "CANCELLED"),
        ("faulted", "FAILED"),
    ],
)
def test_terminalizer_installs_exact_non_success_mapping(
    tmp_path,
    promotion_outcome: str,
    effect_outcome: str,
) -> None:
    auth = authorization()
    capability = build_capability(tmp_path, promotion_value=auth)
    capability.grant()
    capability.begin()
    ledger = PromotionExecutionLedger(tmp_path / "spine.sqlite3")
    promotion_start = ledger.begin(
        auth,
        start_id="promotion-start-1",
        primary_checkout_before_sha256=PRIMARY,
    )
    completion = ledger.complete(
        promotion_start.start,
        receipt_id="promotion-receipt-1",
        outcome=promotion_outcome,
        report=_report(auth, promotion_outcome),
        integration_branch=None,
        integration_revision=None,
        primary_checkout_after_sha256=PRIMARY,
    )
    try:
        result = terminalize_promotion_effect(capability, ledger)
        assert result.replayed is False
        assert result.terminal.outcome == effect_outcome
        assert result.terminal.output_digests == ()
        assert result.terminal.detail_sha256 == completion.receipt.digest
        assert (
            result.reconciliation.disposition
            is PromotionReconciliationDisposition.COMPLETE
        )
    finally:
        ledger.close()
