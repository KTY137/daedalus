from __future__ import annotations

from types import SimpleNamespace

import pytest

import daedalus.kernel.promotion_effect_replay as replay_module
from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayDecision,
    PromotionEffectReplayMismatch,
    inspect_promotion_effect_replay,
)
from daedalus.kernel.promotion_effects import PromotionEffectCapability
from daedalus.kernel.promotion_execution import PromotionExecutionLedger


EFFECT_STARTED = "2026-08-04T05:00:00.000000+00:00"
PROMOTION_STARTED = "2026-08-04T05:00:01.000000+00:00"
PROMOTION_FINISHED = "2026-08-04T05:00:02.000000+00:00"
EFFECT_FINISHED = "2026-08-04T05:00:03.000000+00:00"
REPORT_SHA = "a" * 64
RECEIPT_SHA = "b" * 64


def inert_capability() -> PromotionEffectCapability:
    capability = object.__new__(PromotionEffectCapability)
    object.__setattr__(capability, "authorization", object())
    object.__setattr__(capability, "execution", object())
    object.__setattr__(capability, "promotion", object())
    return capability


def inert_ledger() -> PromotionExecutionLedger:
    return object.__new__(PromotionExecutionLedger)


def effect_snapshot(state: str, *, terminal: bool):
    return SimpleNamespace(
        state=state,
        start_receipt=SimpleNamespace(started_at=EFFECT_STARTED),
        terminal_receipt=(
            SimpleNamespace(
                output_digests=(REPORT_SHA,),
                detail_sha256=RECEIPT_SHA,
                finished_at=EFFECT_FINISHED,
            )
            if terminal
            else None
        ),
    )


def promotion_result(outcome: str):
    return SimpleNamespace(
        start=SimpleNamespace(started_at=PROMOTION_STARTED),
        completion=SimpleNamespace(
            receipt=SimpleNamespace(
                outcome=outcome,
                report_sha256=REPORT_SHA,
                digest=RECEIPT_SHA,
                completed_at=PROMOTION_FINISHED,
            )
        ),
    )


def install_projection_results(monkeypatch, *, effect, promotion) -> None:
    monkeypatch.setattr(
        replay_module,
        "inspect_effect_execution",
        lambda _authorization, _execution: effect,
    )
    monkeypatch.setattr(
        replay_module,
        "inspect_promotion_execution",
        lambda _ledger, _authorization: promotion,
    )


@pytest.mark.parametrize(
    ("promotion_outcome", "expected_effect_outcome"),
    [
        ("succeeded", "COMPLETED"),
        ("refused", "COMPLETED"),
        ("faulted", "FAILED"),
    ],
)
def test_pending_effect_reconciliation_carries_exact_outcome_mapping(
    monkeypatch,
    promotion_outcome,
    expected_effect_outcome,
) -> None:
    install_projection_results(
        monkeypatch,
        effect=effect_snapshot("STARTED", terminal=False),
        promotion=promotion_result(promotion_outcome),
    )

    decision = inspect_promotion_effect_replay(
        inert_capability(),
        inert_ledger(),
    )

    assert decision.action == "reconcile_effect_terminal"
    assert decision.expected_effect_outcome == expected_effect_outcome
    assert decision.expected_output_digests == (REPORT_SHA,)
    assert decision.expected_detail_sha256 == RECEIPT_SHA


@pytest.mark.parametrize(
    ("promotion_outcome", "effect_state"),
    [
        ("succeeded", "COMPLETED"),
        ("refused", "COMPLETED"),
        ("faulted", "FAILED"),
    ],
)
def test_exact_terminal_outcome_mapping_replays_report(
    monkeypatch,
    promotion_outcome,
    effect_state,
) -> None:
    install_projection_results(
        monkeypatch,
        effect=effect_snapshot(effect_state, terminal=True),
        promotion=promotion_result(promotion_outcome),
    )

    decision = inspect_promotion_effect_replay(
        inert_capability(),
        inert_ledger(),
    )

    assert decision.action == "replay_promotion_report"
    assert decision.expected_effect_outcome == effect_state


@pytest.mark.parametrize(
    ("promotion_outcome", "wrong_effect_state"),
    [
        ("succeeded", "FAILED"),
        ("refused", "FAILED"),
        ("faulted", "COMPLETED"),
    ],
)
def test_terminal_outcome_substitution_is_refused(
    monkeypatch,
    promotion_outcome,
    wrong_effect_state,
) -> None:
    install_projection_results(
        monkeypatch,
        effect=effect_snapshot(wrong_effect_state, terminal=True),
        promotion=promotion_result(promotion_outcome),
    )

    with pytest.raises(PromotionEffectReplayMismatch, match="outcome"):
        inspect_promotion_effect_replay(
            inert_capability(),
            inert_ledger(),
        )


def test_unknown_promotion_terminal_outcome_is_refused(monkeypatch) -> None:
    install_projection_results(
        monkeypatch,
        effect=effect_snapshot("STARTED", terminal=False),
        promotion=promotion_result("invented"),
    )

    with pytest.raises(PromotionEffectReplayMismatch, match="unknown promotion"):
        inspect_promotion_effect_replay(
            inert_capability(),
            inert_ledger(),
        )


def test_report_action_requires_explicit_effect_outcome() -> None:
    with pytest.raises(ValueError, match="effect outcome"):
        PromotionEffectReplayDecision(
            action="replay_promotion_report",
            effect=None,
            promotion=None,
            expected_output_digests=(REPORT_SHA,),
            expected_detail_sha256=RECEIPT_SHA,
        )
