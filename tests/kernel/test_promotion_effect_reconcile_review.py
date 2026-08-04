from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.promotion_effect_reconcile import (
    PromotionEffectReconciliationResult,
    reconcile_promotion_effect_terminal,
)


SOURCE = Path("daedalus/kernel/promotion_effect_reconcile.py")


def test_reconciler_cannot_start_or_repeat_promotion_effect() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "subprocess" not in source
    assert "GitWorktreeManager" not in source
    assert "promote_candidates" not in source
    assert "run_in_docker_sandbox" not in source
    assert "grant" not in called
    assert "begin" not in called
    assert "begin_effect" not in called
    assert "capability.finish" not in source
    assert "finish_effect" not in called
    assert called & {"finish"} == {"finish"}
    assert called & {"inspect_promotion_effect_replay"} == {
        "inspect_promotion_effect_replay"
    }


def test_reconciler_signature_accepts_no_caller_output_time_or_outcome() -> None:
    assert tuple(inspect.signature(reconcile_promotion_effect_terminal).parameters) == (
        "capability",
        "promotion_ledger",
    )


def test_terminal_payload_is_derived_only_from_replay_decision() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "outcome=decision.expected_effect_outcome",
        "output_digests=decision.expected_output_digests",
        "detail_sha256=decision.expected_detail_sha256",
        "promotion.completion.receipt.completed_at",
        "finished_at=finished_at",
        'decision.action != "reconcile_effect_terminal"',
        "_inspect_after_terminal_attempt(",
        'decision.action != "replay_promotion_report"',
        "effect terminal changed concurrently to a non-replayable state",
        "reconciled terminal did not become an exact report replay",
        "persisted reconciled terminal differs from returned receipt",
    )
    for fragment in required:
        assert fragment in source


def test_only_exact_reconciled_or_replayed_report_can_return_result() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert source.count("PromotionEffectReconciliationResult(") == 1
    assert 'if self.decision.action != "replay_promotion_report":' in source
    assert "self.decision.effect.terminal_receipt != self.terminal_receipt" in source


def test_result_exposes_no_execution_or_promotion_method() -> None:
    public = {
        name
        for name in dir(PromotionEffectReconciliationResult)
        if not name.startswith("_")
    }
    assert "execute" not in public
    assert "begin" not in public
    assert "finish" not in public
    assert "reconcile" not in public
    assert "promote" not in public
