from __future__ import annotations

import ast
from dataclasses import asdict
from pathlib import Path

from daedalus.spine import effect_boundary
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.promotion_recovery_consumption_inventory import (
    BLOCKERS,
    ENTRYPOINTS,
    GUARD_CONTRACTS,
    GUARD_CONTRACT_IMPLEMENTED,
    INVENTORY_DELTA,
    SCANNER_CLASS,
    SCANNER_METHODS,
    SCANNER_MODULE,
    recognizes_recovery_consumption_method,
)


ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = ROOT / "daedalus" / "kernel" / "promotion_recovery_consumption.py"


def _class_methods() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(TARGET_PATH.read_text(encoding="utf-8"))
    selected = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == SCANNER_CLASS
    )
    return {
        child.name: child
        for child in selected.body
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _called_names(node: ast.AST) -> list[str]:
    names: list[str] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        current = child.func
        if isinstance(current, ast.Name):
            names.append(current.id)
        elif isinstance(current, ast.Attribute):
            names.append(current.attr)
    return names


def test_delta_is_canonical_machine_readable_and_open() -> None:
    payload = INVENTORY_DELTA.payload_dict()

    assert INVENTORY_DELTA.schema == (
        "daedalus-promotion-recovery-consumption-inventory-delta/1"
    )
    assert INVENTORY_DELTA.delta_sha256 == canonical_sha(payload)
    assert INVENTORY_DELTA.to_dict() == {
        **payload,
        "delta_sha256": INVENTORY_DELTA.delta_sha256,
    }
    assert INVENTORY_DELTA.canonical_registry_integrated is False
    assert INVENTORY_DELTA.closed is False
    assert INVENTORY_DELTA.blockers == BLOCKERS


def test_delta_describes_exact_two_write_surfaces_honestly() -> None:
    assert len(ENTRYPOINTS) == 2
    initialize, consume = ENTRYPOINTS

    assert initialize.id == "kernel.promotion_recovery_consumption.initialize"
    assert initialize.target.endswith("PromotionRecoveryConsumptionLedger.__init__")
    assert initialize.effects == ("filesystem_write",)
    assert initialize.guard_contracts == ()
    assert initialize.wiring == "unguarded"
    assert set(initialize.anchors) == {"_initialize", "_connect_writer"}

    assert consume.id == "kernel.promotion_recovery_consumption.consume"
    assert consume.target.endswith("PromotionRecoveryConsumptionLedger.consume")
    assert consume.effects == ("filesystem_write",)
    assert consume.guard_contracts == ("promotion.owner_recovery_decision",)
    assert consume.wiring == "local_guards"
    assert set(consume.anchors) == {
        "verify_promotion_recovery_decision",
        "_connect_writer",
    }

    assert all(row.surface == "python" for row in ENTRYPOINTS)
    assert all("central" not in row.wiring for row in ENTRYPOINTS)


def test_proposed_guard_contract_is_implemented_but_not_fabricated() -> None:
    assert GUARD_CONTRACT_IMPLEMENTED == {
        "promotion.owner_recovery_decision": True
    }
    assert len(GUARD_CONTRACTS) == 1
    guard = GUARD_CONTRACTS[0]
    assert guard.id == "promotion.owner_recovery_decision"
    assert guard.implemented is True
    assert guard.evidence_target.endswith("verify_promotion_recovery_decision")


def test_proposed_scanner_hook_is_exact_and_rejects_near_misses() -> None:
    assert SCANNER_METHODS == ("__init__", "consume")
    for method in SCANNER_METHODS:
        assert recognizes_recovery_consumption_method(
            SCANNER_MODULE,
            SCANNER_CLASS,
            method,
        )

    assert not recognizes_recovery_consumption_method(
        SCANNER_MODULE,
        SCANNER_CLASS,
        "verify_consumption",
    )
    assert not recognizes_recovery_consumption_method(
        SCANNER_MODULE,
        "PromotionRecoveryConsumptionLedgerReplica",
        "consume",
    )
    assert not recognizes_recovery_consumption_method(
        SCANNER_MODULE + "_compat",
        SCANNER_CLASS,
        "consume",
    )


def test_target_methods_and_declared_anchors_exist_in_source() -> None:
    methods = _class_methods()
    assert set(SCANNER_METHODS) <= set(methods)

    initialize_calls = _called_names(methods["__init__"])
    schema_calls = _called_names(methods["_initialize"])
    consume_calls = _called_names(methods["consume"])

    assert initialize_calls.count("_initialize") == 1
    assert schema_calls.count("_connect_writer") == 1
    assert consume_calls.count("verify_promotion_recovery_decision") == 2
    assert consume_calls.count("_connect_writer") == 1

    declared = {anchor for row in ENTRYPOINTS for anchor in row.anchors}
    observed = set(initialize_calls + schema_calls + consume_calls)
    assert declared <= observed


def test_current_canonical_registry_and_scanner_integrate_exact_delta() -> None:
    registered = {row.target: row for row in effect_boundary.ENTRYPOINTS}
    proposed_targets = {row.target for row in ENTRYPOINTS}
    assert proposed_targets <= set(registered)
    assert effect_boundary.GUARD_CONTRACT_IMPLEMENTED[
        "promotion.owner_recovery_decision"
    ] is True

    for proposed in ENTRYPOINTS:
        installed = registered[proposed.target]
        assert installed.id == proposed.id
        assert installed.surface.value == proposed.surface
        assert tuple(effect.value for effect in installed.effects) == proposed.effects
        assert installed.guard_contracts == proposed.guard_contracts
        assert installed.wiring.value == proposed.wiring

    discoveries, findings = effect_boundary.discover_entrypoints(ROOT)
    discovered_targets = {row.target for row in discoveries}
    assert proposed_targets <= discovered_targets
    assert not any(
        row.code == "scan.source_unreadable"
        and "promotion_recovery_consumption.py" in row.target
        for row in findings
    )


def test_delta_rows_are_unique_and_preserve_declared_order() -> None:
    assert len({row.id for row in ENTRYPOINTS}) == len(ENTRYPOINTS)
    assert len({row.target for row in ENTRYPOINTS}) == len(ENTRYPOINTS)
    assert [asdict(row) for row in INVENTORY_DELTA.entrypoints] == [
        asdict(row) for row in ENTRYPOINTS
    ]
