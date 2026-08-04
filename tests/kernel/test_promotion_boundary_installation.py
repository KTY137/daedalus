from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kairos import gated_writes
from daedalus.kernel.promotion_effect_inventory import (
    build_promotion_effect_inventory,
)
from daedalus.spine import effect_boundary
from daedalus.spine.promotion_effect_rows import install_promotion_effect_rows


ROOT = Path(__file__).resolve().parents[2]
REVISION = "a" * 40


def test_live_promotion_module_installs_typed_manager_boundaries() -> None:
    state = gated_writes.__dict__.get("_promotion_manager_boundary_state")
    replay = gated_writes.__dict__.get("_promotion_manager_replay_wrapper")

    assert state is not None
    assert replay is not None
    assert gated_writes.PromotionExecutionLedger is state.ledger_type
    assert gated_writes.promote_candidates == state.promote_candidates
    assert state.ledger_wrapper is replay
    assert "install_promotion_manager_boundary" not in gated_writes.__dict__
    assert "install_promotion_manager_replay_boundary" not in gated_writes.__dict__


def test_promotion_execution_rows_are_exact_and_still_local() -> None:
    rows = {
        row.id: row
        for row in effect_boundary.ENTRYPOINTS
        if row.id.startswith("kernel.promotion_execution.")
    }
    assert tuple(sorted(rows)) == (
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    )
    assert rows["kernel.promotion_execution.begin"].target.endswith(
        "PromotionExecutionLedger.begin"
    )
    assert rows["kernel.promotion_execution.complete"].target.endswith(
        "PromotionExecutionLedger.complete"
    )
    assert all(
        row.wiring is effect_boundary.Wiring.LOCAL_GUARDS
        for row in rows.values()
    )
    assert all(
        row.guard_contracts == ("spine.intent_ledger",)
        for row in rows.values()
    )


def test_registry_defaults_observe_the_same_installed_tuple_and_mapping() -> None:
    assert effect_boundary.registry_sha256.__defaults__ == (
        effect_boundary.ENTRYPOINTS,
    )
    assert effect_boundary.begin_effect.__kwdefaults__["registry"] is (
        effect_boundary.REGISTRY_BY_ID
    )
    assert effect_boundary.check_conformance.__kwdefaults__["registry"] is (
        effect_boundary.ENTRYPOINTS
    )
    assert tuple(effect_boundary.REGISTRY_BY_ID) == tuple(
        row.id for row in effect_boundary.ENTRYPOINTS
    )


def test_inventory_now_reports_only_the_three_deliberate_local_blockers() -> None:
    report = build_promotion_effect_inventory(
        ROOT,
        source_revision=REVISION,
    )
    assert report.closed is False
    assert {
        finding.entrypoint_id: finding.blockers for finding in report.findings
    } == {
        "python.promote_candidates": (
            "registry.not_central:local_guards",
        ),
        "kernel.promotion_execution.begin": (
            "registry.not_central:local_guards",
        ),
        "kernel.promotion_execution.complete": (
            "registry.not_central:local_guards",
        ),
    }


def test_partial_or_conflicting_registry_installation_refuses() -> None:
    begin = effect_boundary.REGISTRY_BY_ID["kernel.promotion_execution.begin"]
    fake = SimpleNamespace(
        EntrypointSpec=effect_boundary.EntrypointSpec,
        GuardAnchor=effect_boundary.GuardAnchor,
        Surface=effect_boundary.Surface,
        Effect=effect_boundary.Effect,
        Wiring=effect_boundary.Wiring,
        ENTRYPOINTS=(begin,),
    )
    with pytest.raises(RuntimeError, match="partially or incorrectly"):
        install_promotion_effect_rows(fake)


def test_source_order_installs_audit_then_replay_after_callable_definition() -> None:
    source = (ROOT / "daedalus" / "kairos" / "gated_writes.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    promote_index = next(
        index
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.FunctionDef) and node.name == "promote_candidates"
    )
    calls = [
        (index, node.func.id)
        for index, node in enumerate(tree.body)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id
        in {
            "install_promotion_manager_boundary",
            "install_promotion_manager_replay_boundary",
        }
        for node in (node.value,)
    ]
    assert calls == [
        (calls[0][0], "install_promotion_manager_boundary"),
        (calls[1][0], "install_promotion_manager_replay_boundary"),
    ]
    assert promote_index < calls[0][0] < calls[1][0]
