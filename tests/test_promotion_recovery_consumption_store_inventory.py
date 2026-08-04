from __future__ import annotations

import ast
from dataclasses import asdict
from pathlib import Path

from daedalus.spine import effect_boundary
from daedalus.spine.envelope import canonical_sha
from daedalus.spine.promotion_recovery_consumption_store_inventory import (
    BLOCKERS,
    ENTRYPOINTS,
    INVENTORY_DELTA,
    SCANNER_FUNCTION,
    SCANNER_MODULE,
    recognizes_recovery_consumption_store_initializer,
)


ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = (
    ROOT
    / "daedalus"
    / "kernel"
    / "promotion_recovery_consumption_store.py"
)


def _aliases(tree: ast.Module) -> dict[str, str]:
    result: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                result[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom):
            prefix = node.module or ""
            for alias in node.names:
                result[alias.asname or alias.name] = (
                    f"{prefix}.{alias.name}" if prefix else alias.name
                )
    return result


def _name(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _initializer_calls() -> list[str]:
    tree = ast.parse(TARGET_PATH.read_text(encoding="utf-8"))
    aliases = _aliases(tree)
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == SCANNER_FUNCTION
    )
    calls = sorted(
        (node for node in ast.walk(function) if isinstance(node, ast.Call)),
        key=lambda node: (node.lineno, node.col_offset),
    )
    return [_name(node.func, aliases) for node in calls]


def test_delta_is_canonical_machine_readable_and_open() -> None:
    payload = INVENTORY_DELTA.payload_dict()

    assert INVENTORY_DELTA.schema == (
        "daedalus-promotion-recovery-consumption-store-inventory-delta/1"
    )
    assert INVENTORY_DELTA.delta_sha256 == canonical_sha(payload)
    assert INVENTORY_DELTA.to_dict() == {
        **payload,
        "delta_sha256": INVENTORY_DELTA.delta_sha256,
    }
    assert INVENTORY_DELTA.canonical_registry_integrated is False
    assert INVENTORY_DELTA.canonical_scanner_integrated is False
    assert INVENTORY_DELTA.closed is False
    assert INVENTORY_DELTA.blockers == BLOCKERS


def test_delta_describes_exact_initializer_without_fabricated_guard() -> None:
    assert len(ENTRYPOINTS) == 1
    row = ENTRYPOINTS[0]

    assert row.id == "kernel.promotion_recovery_consumption_store.initialize"
    assert row.target == (
        "daedalus.kernel.promotion_recovery_consumption_store:"
        "initialize_promotion_recovery_consumption_store"
    )
    assert row.surface == "python"
    assert row.effects == ("filesystem_write",)
    assert row.guard_contracts == ()
    assert row.wiring == "unguarded"
    assert row.anchors == (
        "tempfile.mkstemp",
        "sqlite3.connect",
        "os.link",
        "_fsync_file",
        "_fsync_directory",
    )
    assert "Effect Lease" in row.migration
    assert "RuntimeConformanceReceipt" in row.migration
    assert "Docker sandbox" in row.migration


def test_proposed_scanner_hook_is_exact_and_rejects_near_misses() -> None:
    assert recognizes_recovery_consumption_store_initializer(
        SCANNER_MODULE,
        SCANNER_FUNCTION,
    )
    assert not recognizes_recovery_consumption_store_initializer(
        SCANNER_MODULE + "_compat",
        SCANNER_FUNCTION,
    )
    assert not recognizes_recovery_consumption_store_initializer(
        SCANNER_MODULE,
        SCANNER_FUNCTION + "_unsafe",
    )
    assert not recognizes_recovery_consumption_store_initializer(
        SCANNER_MODULE,
        "inspect_promotion_recovery_consumption_store",
    )


def test_initializer_and_all_declared_effect_anchors_exist() -> None:
    calls = _initializer_calls()
    row = ENTRYPOINTS[0]

    for anchor in row.anchors:
        assert calls.count(anchor) >= 1
    assert calls.count("tempfile.mkstemp") == 1
    assert calls.count("os.link") == 1
    assert calls.count("sqlite3.connect") == 1
    assert calls.index("tempfile.mkstemp") < calls.index("os.link")


def test_current_registry_and_scanner_still_expose_exact_gap() -> None:
    row = ENTRYPOINTS[0]
    assert row.id not in effect_boundary.REGISTRY_BY_ID
    assert row.target not in {item.target for item in effect_boundary.ENTRYPOINTS}

    discoveries, findings = effect_boundary.discover_entrypoints(ROOT)
    assert row.target not in {item.target for item in discoveries}
    assert not any(
        item.code == "scan.source_unreadable"
        and "promotion_recovery_consumption_store.py" in item.target
        for item in findings
    )


def test_delta_rows_are_unique_and_preserve_declared_order() -> None:
    assert len({row.id for row in ENTRYPOINTS}) == len(ENTRYPOINTS)
    assert len({row.target for row in ENTRYPOINTS}) == len(ENTRYPOINTS)
    assert [asdict(row) for row in INVENTORY_DELTA.entrypoints] == [
        asdict(row) for row in ENTRYPOINTS
    ]
