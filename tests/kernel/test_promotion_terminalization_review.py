from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus" / "kernel" / "promotion_terminalization.py"


def test_terminalizer_has_no_external_effect_or_authority_minting_calls() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden: list[str] = []
    finish_calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute):
            if function.attr in {
                "grant",
                "begin",
                "begin_effect",
                "issue",
                "promote",
                "promote_candidates",
                "execute",
            }:
                forbidden.append(function.attr)
            if function.attr == "finish":
                finish_calls.append(ast.unparse(function.value))
    assert forbidden == []
    assert finish_calls == ["capability.authorization.effect_ledger"]
    assert "subprocess" not in text
    assert "GitWorktree" not in text
    assert "OwnerApproval" not in text


def test_terminalizer_reprojects_before_and_after_single_accounting_write() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    first_projection = text.index(
        "before = inspect_promotion_reconciliation(capability, promotion_ledger)"
    )
    write = text.index("capability.authorization.effect_ledger.finish(")
    post_projection = text.index(
        "after = inspect_promotion_reconciliation(capability, promotion_ledger)"
    )
    assert first_projection < write < post_projection
    assert "EFFECT_TERMINAL_REQUIRED" in text
    assert "PromotionReconciliationDisposition.COMPLETE" in text
    assert "result.terminal != written" in text


def test_race_replay_is_narrow_and_requires_exact_complete_reprojection() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)]
    assert len(handlers) == 1
    assert isinstance(handlers[0].type, ast.Name)
    assert handlers[0].type.id == "EffectLeaseStateError"
    assert "after_race = inspect_promotion_reconciliation" in text
    assert "lost a non-idempotent race" in text
    assert "except Exception" not in text
    assert "except BaseException" not in text


def test_expired_lease_reconciliation_is_documented_as_terminal_only() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "external effect is already terminal" in text
    assert "sole missing transition" in text
    assert "does not permit effect terminalization" in text
    assert "does not grant a lease" in text
