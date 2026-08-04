from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.gates.repository_write_inventory_v2 as inventory_v2


def _call_name(node: ast.Call) -> str | None:
    current: ast.expr = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def test_v2_module_has_inventory_authority_only() -> None:
    source = inspect.getsource(inventory_v2)
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                item.name.split(".", 1)[0] for item in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "subprocess",
            "sqlite3",
            "shutil",
            "tempfile",
            "docker",
        }
    )
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "EffectLease" not in source
    assert "guard_contract" not in source
    assert "trusted" not in source.lower()

    forbidden_terminals = {
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "unlink",
        "rename",
        "replace",
        "open",
        "run",
        "Popen",
        "system",
        "connect",
        "merge",
        "promote",
    }
    calls = [
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for name in [_call_name(node)]
        if name is not None
    ]
    assert not {
        name.rsplit(".", 1)[-1] for name in calls
    }.intersection(forbidden_terminals)


def test_composer_uses_stable_three_projection_order() -> None:
    source = inspect.getsource(inventory_v2.scan_repository_write_surfaces_v2)
    tree = ast.parse(source)
    calls = [
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]

    assert calls.count("scan_repository_write_surfaces") == 2
    assert calls.count("scan_repository_write_stdlib_delta") == 1
    first = source.index("base_before = scan_repository_write_surfaces")
    middle = source.index("delta = scan_repository_write_stdlib_delta")
    last = source.index("base_after = scan_repository_write_surfaces")
    validation = source.index("_validate_components(")
    assert first < middle < last < validation


def test_component_validator_binds_revision_digest_bytes_and_file_set() -> None:
    source = inspect.getsource(inventory_v2._validate_components)

    assert "base_before.source_revision" in source
    assert "delta.source_revision" in source
    assert "base_after.source_revision" in source
    assert "base_before.digest" in source
    assert "delta.base_inventory_digest" in source
    assert "base_after.digest" in source
    assert "base_before.scan_input_sha256" in source
    assert "delta.scan_input_sha256" in source
    assert "base_after.scan_input_sha256" in source
    assert "base_before.files_scanned" in source
    assert "delta.files_scanned" in source
    assert "base_after.files_scanned" in source


def test_v2_report_cannot_claim_target_guard_or_gate_closure() -> None:
    source = inspect.getsource(inventory_v2.RepositoryWriteInventoryV2._payload)

    assert '"canonical_scanner_integrated": True' in source
    assert '"inventory_only": True' in source
    assert '"primary_checkout_target_proven": False' in source
    assert "self.closed" in source
    assert '"unclassified-production-write-surfaces"' in source
    assert "guarded" not in source
    assert "GateReport" not in source


def test_schema_and_work_packet_exist_as_separate_review_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]

    assert (
        root / "configs/schemas/repository-write-inventory-v2.schema.json"
    ).is_file()
    assert (
        root
        / "docs/work-packets/G0-RWI-20B_REPOSITORY_WRITE_CANONICAL_V2.json"
    ).is_file()
