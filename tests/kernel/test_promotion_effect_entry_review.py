from __future__ import annotations

import ast
import inspect
from pathlib import Path

from daedalus.kernel.promotion_effect_entry import (
    PromotionEffectEntryResult,
    prepare_promotion_effect_entry,
)


SOURCE = Path("daedalus/kernel/promotion_effect_entry.py")


def test_entry_protocol_has_no_promotion_callback_or_external_effect_call() -> None:
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
    assert "callback" not in source
    assert "provider" not in source
    assert called & {"grant", "begin"} == {"grant", "begin"}
    assert "finish" not in called
    assert "finish_effect" not in called
    assert "complete" not in called
    assert "record_intent" not in called


def test_entry_signature_accepts_no_report_time_path_or_callable() -> None:
    assert tuple(inspect.signature(prepare_promotion_effect_entry).parameters) == (
        "capability",
        "promotion_ledger",
    )


def test_execute_action_requires_this_calls_exact_poststart_receipt() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    required = (
        "capability.grant()",
        "begun = capability.begin()",
        "if not begun.execute:",
        'after.action != "pending_reconciliation"',
        "after.promotion is not None",
        "after.effect.start_receipt != begun.receipt",
        'action="execute_promotion"',
        "start_receipt=begun.receipt",
    )
    for fragment in required:
        assert fragment in source
    assert source.index("capability.grant()") < source.index("begun = capability.begin()")
    assert source.index("begun = capability.begin()") < source.index(
        'action="execute_promotion"'
    )


def test_unpersisted_lease_cannot_hide_retained_promotion() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "retained_promotion = inspect_promotion_execution(" in source
    assert "if retained_promotion is not None:" in source
    assert "promotion execution exists before exact Effect-Lease persistence" in source


def test_presence_probe_is_read_only_and_collision_sensitive() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "mode=ro" in source
    assert "PRAGMA query_only=ON" in source
    assert "INSERT " not in source
    assert "UPDATE " not in source
    assert "DELETE " not in source
    assert "lease_sha256=? OR lease_id=?" in source
    assert "collides with another authority" in source


def test_entry_result_exposes_only_one_boolean_execution_permission() -> None:
    public = {
        name
        for name in dir(PromotionEffectEntryResult)
        if not name.startswith("_")
    }
    assert "execute" not in public
    assert "begin" not in public
    assert "finish" not in public
    assert "promote" not in public
    assert "permits_promotion_execution" in public
