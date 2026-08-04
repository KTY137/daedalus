from __future__ import annotations

from types import SimpleNamespace

import pytest

from daedalus.kernel.effects import (
    EffectLeaseStateError,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger
from daedalus.kernel.promotion_reconciliation import (
    ExpectedPromotionEffectTerminal,
    PromotionReconciliationDisposition,
    PromotionReconciliationError,
    PromotionReconciliationProjection,
)
from daedalus.kernel.promotion_terminalization import (
    PromotionTerminalizationError,
    reconcile_promotion_effect_terminal,
)


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def _start() -> LeasedEffectStartReceipt:
    return LeasedEffectStartReceipt(
        lease_sha256=DIGEST_A,
        execution_id="promotion-1",
        idempotency_key="promotion-key",
        execution_request_sha256=DIGEST_B,
        boundary_receipt_sha256=DIGEST_C,
        started_at="2026-08-04T04:00:00.000000+00:00",
        receipt_sha256=DIGEST_D,
    )


def _terminal(*, receipt_sha256: str = DIGEST_C) -> EffectTerminalReceipt:
    return EffectTerminalReceipt(
        lease_sha256=DIGEST_A,
        execution_id="promotion-1",
        start_receipt_sha256=DIGEST_D,
        outcome="COMPLETED",
        output_digests=(DIGEST_A, DIGEST_B),
        detail_sha256=DIGEST_B,
        finished_at="2026-08-04T04:00:02.000000+00:00",
        receipt_sha256=receipt_sha256,
    )


class _EffectLedger:
    def __init__(self, result: EffectTerminalReceipt | BaseException):
        self.result = result
        self.calls: list[dict[str, object]] = []

    def finish(self, start, **kwargs):
        self.calls.append({"start": start, **kwargs})
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def _capability(effect_ledger: _EffectLedger) -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(
        capability,
        "authorization",
        SimpleNamespace(effect_ledger=effect_ledger),
    )
    return capability


def _promotion_ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


def _projection(
    disposition: PromotionReconciliationDisposition,
    *,
    terminal: EffectTerminalReceipt | None = None,
) -> PromotionReconciliationProjection:
    start = _start()
    effect = None
    promotion = None
    expected = None
    if disposition is not PromotionReconciliationDisposition.FRESH:
        effect = SimpleNamespace(start=start, terminal=terminal)
    if disposition in {
        PromotionReconciliationDisposition.PROMOTION_PENDING,
        PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
        PromotionReconciliationDisposition.COMPLETE,
    }:
        completion = None
        if disposition in {
            PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED,
            PromotionReconciliationDisposition.COMPLETE,
        }:
            completion = SimpleNamespace(receipt=SimpleNamespace())
            expected = ExpectedPromotionEffectTerminal(
                outcome="COMPLETED",
                output_digests=(DIGEST_A, DIGEST_B),
                detail_sha256=DIGEST_B,
            )
        promotion = SimpleNamespace(completion=completion)
    return PromotionReconciliationProjection(
        disposition=disposition,
        effect_execution=effect,
        promotion_execution=promotion,
        expected_effect_terminal=expected,
    )


def test_terminalizes_only_exact_material_and_rechecks_retained_state(monkeypatch):
    written = _terminal()
    effect_ledger = _EffectLedger(written)
    projections = iter(
        [
            _projection(PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED),
            _projection(
                PromotionReconciliationDisposition.COMPLETE,
                terminal=written,
            ),
        ]
    )
    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        lambda *_args: next(projections),
    )

    retained = reconcile_promotion_effect_terminal(
        _capability(effect_ledger),
        _promotion_ledger(),
    )

    assert retained == written
    assert len(effect_ledger.calls) == 1
    call = effect_ledger.calls[0]
    assert call["start"] == _start()
    assert call["outcome"] == "COMPLETED"
    assert call["output_digests"] == (DIGEST_A, DIGEST_B)
    assert call["detail_sha256"] == DIGEST_B
    assert call["finished_at"].tzinfo is not None


def test_complete_state_replays_without_writing(monkeypatch):
    retained = _terminal()
    effect_ledger = _EffectLedger(AssertionError("writer must not run"))
    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        lambda *_args: _projection(
            PromotionReconciliationDisposition.COMPLETE,
            terminal=retained,
        ),
    )

    assert (
        reconcile_promotion_effect_terminal(
            _capability(effect_ledger),
            _promotion_ledger(),
        )
        == retained
    )
    assert effect_ledger.calls == []


@pytest.mark.parametrize(
    "disposition",
    [
        PromotionReconciliationDisposition.FRESH,
        PromotionReconciliationDisposition.EFFECT_ONLY_PENDING,
        PromotionReconciliationDisposition.PROMOTION_PENDING,
    ],
)
def test_nonterminal_states_refuse_without_writing(monkeypatch, disposition):
    effect_ledger = _EffectLedger(AssertionError("writer must not run"))
    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        lambda *_args: _projection(disposition),
    )

    with pytest.raises(PromotionTerminalizationError, match="not eligible"):
        reconcile_promotion_effect_terminal(
            _capability(effect_ledger),
            _promotion_ledger(),
        )
    assert effect_ledger.calls == []


def test_concurrent_exact_terminal_is_idempotent(monkeypatch):
    retained = _terminal()
    effect_ledger = _EffectLedger(EffectLeaseStateError("already terminal"))
    projections = iter(
        [
            _projection(PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED),
            _projection(
                PromotionReconciliationDisposition.COMPLETE,
                terminal=retained,
            ),
        ]
    )
    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        lambda *_args: next(projections),
    )

    assert (
        reconcile_promotion_effect_terminal(
            _capability(effect_ledger),
            _promotion_ledger(),
        )
        == retained
    )
    assert len(effect_ledger.calls) == 1


def test_contradictory_terminal_after_write_refuses(monkeypatch):
    effect_ledger = _EffectLedger(_terminal())
    calls = iter([0, 1])

    def inspect(*_args):
        if next(calls) == 0:
            return _projection(
                PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED
            )
        raise PromotionReconciliationError("terminal substitution")

    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        inspect,
    )

    with pytest.raises(
        PromotionTerminalizationError,
        match="does not reconcile",
    ):
        reconcile_promotion_effect_terminal(
            _capability(effect_ledger),
            _promotion_ledger(),
        )


def test_written_receipt_must_match_retained_receipt(monkeypatch):
    written = _terminal(receipt_sha256=DIGEST_C)
    retained = _terminal(receipt_sha256=DIGEST_D)
    effect_ledger = _EffectLedger(written)
    projections = iter(
        [
            _projection(PromotionReconciliationDisposition.EFFECT_TERMINAL_REQUIRED),
            _projection(
                PromotionReconciliationDisposition.COMPLETE,
                terminal=retained,
            ),
        ]
    )
    monkeypatch.setattr(
        "daedalus.kernel.promotion_terminalization.inspect_promotion_reconciliation",
        lambda *_args: next(projections),
    )

    with pytest.raises(PromotionTerminalizationError, match="differs"):
        reconcile_promotion_effect_terminal(
            _capability(effect_ledger),
            _promotion_ledger(),
        )


def test_malformed_authority_types_refuse_before_projection():
    with pytest.raises(TypeError, match="PromotionEffectCapability"):
        reconcile_promotion_effect_terminal(object(), _promotion_ledger())
    with pytest.raises(TypeError, match="PromotionExecutionLedger"):
        reconcile_promotion_effect_terminal(
            _capability(_EffectLedger(_terminal())),
            object(),
        )
