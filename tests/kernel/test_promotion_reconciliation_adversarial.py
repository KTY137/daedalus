from __future__ import annotations

import pytest

from daedalus.kernel.promotion_reconciliation import (
    ExpectedPromotionEffectTerminal,
    PromotionReconciliationDisposition,
    PromotionReconciliationProjection,
)


def test_expected_terminal_refuses_malformed_digest() -> None:
    with pytest.raises(ValueError, match="malformed digest"):
        ExpectedPromotionEffectTerminal(
            outcome="FAILED",
            output_digests=(),
            detail_sha256="not-a-digest",
        )


def test_expected_terminal_refuses_unsorted_or_duplicate_outputs() -> None:
    with pytest.raises(ValueError, match="sorted and unique"):
        ExpectedPromotionEffectTerminal(
            outcome="COMPLETED",
            output_digests=("b" * 64, "a" * 64, "a" * 64),
            detail_sha256="c" * 64,
        )


def test_projection_refuses_disposition_state_substitution() -> None:
    with pytest.raises(ValueError, match="contradicts retained state"):
        PromotionReconciliationProjection(
            disposition=PromotionReconciliationDisposition.COMPLETE,
            effect_execution=None,
            promotion_execution=None,
            expected_effect_terminal=ExpectedPromotionEffectTerminal(
                outcome="FAILED",
                output_digests=(),
                detail_sha256="d" * 64,
            ),
        )


def test_fresh_projection_cannot_smuggle_terminal_material() -> None:
    with pytest.raises(ValueError, match="contradicts retained state"):
        PromotionReconciliationProjection(
            disposition=PromotionReconciliationDisposition.FRESH,
            effect_execution=None,
            promotion_execution=None,
            expected_effect_terminal=ExpectedPromotionEffectTerminal(
                outcome="CANCELLED",
                output_digests=(),
                detail_sha256="e" * 64,
            ),
        )


def test_raw_string_disposition_is_refused() -> None:
    with pytest.raises(ValueError, match="disposition is invalid"):
        PromotionReconciliationProjection(
            disposition="fresh",  # type: ignore[arg-type]
            effect_execution=None,
            promotion_execution=None,
            expected_effect_terminal=None,
        )
