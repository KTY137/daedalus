from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayDecision,
    inspect_promotion_effect_replay,
)


SOURCE = Path("daedalus/kernel/promotion_effect_replay.py")


def test_decision_layer_is_read_only_and_has_no_effect_callback() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }

    assert "subprocess" not in source
    assert "sqlite3" not in source
    assert "GitWorktreeManager" not in source
    assert "promote_candidates" not in source
    assert "run_in_docker_sandbox" not in source
    assert "grant" not in called
    assert "begin" not in called
    assert "begin_effect" not in called
    assert "finish" not in called
    assert "finish_effect" not in called
    assert "complete" not in called
    assert called & {
        "inspect_effect_execution",
        "inspect_promotion_execution",
    } == {
        "inspect_effect_execution",
        "inspect_promotion_execution",
    }


def test_public_signature_accepts_only_exact_capability_and_promotion_ledger() -> None:
    assert tuple(inspect.signature(inspect_promotion_effect_replay).parameters) == (
        "capability",
        "promotion_ledger",
    )


def test_only_both_absent_can_produce_fresh_authority_decision() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    fresh_marker = 'action="fresh"'
    assert source.count(fresh_marker) == 1
    fresh_index = source.index(fresh_marker)
    assert source.index("if effect is None:") < fresh_index
    assert source.index("if promotion is not None:") < fresh_index
    assert "permits_fresh_execution" in source
    assert 'return self.action == "fresh"' in source


def test_report_replay_requires_outcome_outputs_detail_and_chronology() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        '"succeeded": "COMPLETED"',
        '"refused": "COMPLETED"',
        '"faulted": "FAILED"',
        "completion.receipt.report_sha256",
        "completion.receipt.digest",
        "effect.state != expected_outcome",
        'mismatches.append("outcome")',
        "terminal.output_digests != outputs",
        "terminal.detail_sha256 != detail",
        "_enforce_terminal_order(effect, promotion)",
        "top-level Effect-Lease terminal precedes promotion terminal",
        'action="replay_promotion_report"',
    )
    for fragment in required:
        assert fragment in source


def test_decision_object_contains_no_execute_or_reconcile_method() -> None:
    public = {
        name
        for name in dir(PromotionEffectReplayDecision)
        if not name.startswith("_")
    }
    assert "execute" not in public
    assert "begin" not in public
    assert "finish" not in public
    assert "reconcile" not in public
    assert "promote" not in public
    assert {
        "permits_fresh_execution",
        "requires_reconciliation",
        "expected_effect_outcome",
    } <= public
