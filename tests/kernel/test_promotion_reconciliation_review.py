from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus" / "kernel" / "promotion_reconciliation.py"


def test_reconciliation_projection_has_no_effect_or_git_authority() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(text)
    forbidden: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in {
            "grant",
            "begin",
            "complete",
            "finish",
            "begin_effect",
            "finish_effect",
            "revoke",
        }:
            forbidden.append(function.attr)
    assert forbidden == []
    assert "subprocess" not in text
    assert "GitWorktree" not in text
    assert "automatic_execution_allowed" in text
    assert "return False" in text


def test_effect_projection_is_read_before_promotion_projection() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    effect = text.index("effect = inspect_promotion_effect_execution(capability)")
    promotion = text.index("promotion = inspect_promotion_execution(")
    classification = text.index("if effect is None and promotion is None")
    assert effect < promotion < classification


def test_cross_lifecycle_order_and_terminal_bindings_are_explicit() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "effect_started > promotion_started" in text
    assert "effect_finished < promotion_finished" in text
    assert '"outcome": (actual.outcome, expected.outcome)' in text
    assert '"output_digests": (actual.output_digests, expected.output_digests)' in text
    assert '"detail_sha256": (actual.detail_sha256, expected.detail_sha256)' in text
    assert "promotion execution exists without a top-level effect start" in text
    assert "effect terminal exists while promotion execution is pending" in text


def test_all_dispositions_are_reconciliation_only() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    for value in (
        "fresh",
        "effect-only-pending-reconciliation",
        "promotion-pending-reconciliation",
        "effect-terminalization-required",
        "complete",
    ):
        assert value in text
    assert "execute=True" not in text
    assert "automatic_execution_allowed(self)" in text
