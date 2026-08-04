from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.kernel.promotion_effect_inventory import (
    PromotionEffectInventoryError,
    build_promotion_effect_inventory,
)
from daedalus.spine.effect_boundary import (
    Effect,
    EffectStartRefused,
    begin_effect,
)


ROOT = Path(__file__).resolve().parents[2]
_EXECUTION_ROWS = (
    "kernel.promotion_execution.open",
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
)


def _tree(relative: str) -> ast.Module:
    return ast.parse((ROOT / relative).read_text(encoding="utf-8"))


def test_counter_review_rows_cannot_claim_central_or_runtime_authority() -> None:
    source = (ROOT / "daedalus" / "spine" / "promotion_effect_rows.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assert source.count("boundary.Wiring.LOCAL_GUARDS") == 3
    assert "boundary.Wiring.CENTRAL" not in source
    assert "RuntimeConformanceReceipt" not in source
    assert "EffectLease" not in source
    forbidden = {"subprocess", "Popen", "system", "GitWorktreeManager"}
    assert not {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in forbidden
    }


def test_counter_review_live_installers_are_post_definition_and_one_shot() -> None:
    tree = _tree("daedalus/kairos/gated_writes.py")
    promote = next(
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.FunctionDef) and node.name == "promote_candidates"
    )
    calls: list[tuple[int, str]] = []
    deletes: set[str] = set()
    for index, node in enumerate(tree.body):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            function = node.value.func
            if isinstance(function, ast.Name) and function.id.startswith(
                "install_promotion_manager_"
            ):
                calls.append((index, function.id))
        if isinstance(node, ast.Delete):
            deletes.update(
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            )
    assert [name for _, name in calls] == [
        "install_promotion_manager_boundary",
        "install_promotion_manager_replay_boundary",
    ]
    assert promote < calls[0][0] < calls[1][0]
    assert {
        "install_promotion_manager_boundary",
        "install_promotion_manager_replay_boundary",
    } <= deletes


def test_local_rows_cannot_be_opened_through_generic_begin_effect() -> None:
    for entrypoint_id in _EXECUTION_ROWS:
        with pytest.raises(EffectStartRefused, match="not central"):
            begin_effect(
                entrypoint_id,
                (Effect.FILESYSTEM_WRITE,),
                (),
            )


def test_malformed_and_stale_revision_inputs_remain_fail_closed(
    tmp_path: Path,
) -> None:
    with pytest.raises(PromotionEffectInventoryError, match="40 lowercase"):
        build_promotion_effect_inventory(ROOT, source_revision="not-a-revision")
    with pytest.raises(PromotionEffectInventoryError, match="unavailable"):
        build_promotion_effect_inventory(
            tmp_path / "missing",
            source_revision="a" * 40,
        )
