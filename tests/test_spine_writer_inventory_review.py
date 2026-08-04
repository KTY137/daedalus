from __future__ import annotations

import ast
import inspect

import daedalus.spine as spine
import daedalus.spine.writer_inventory as inventory


def test_review_exports_one_read_only_inventory_surface() -> None:
    assert spine.scan_event_store_writers is inventory.scan_event_store_writers
    assert spine.WriterInventory is inventory.WriterInventory
    assert spine.WriterCallsite is inventory.WriterCallsite
    assert "scan_event_store_writers" in spine.__all__
    assert not hasattr(inventory, "write_event_store_inventory")
    assert not hasattr(inventory, "migrate_event_store_writers")


def test_review_all_direct_and_ambiguous_kinds_are_blocking() -> None:
    assert inventory._BLOCKING_KINDS == {
        "legacy_direct",
        "ambiguous_direct",
        "ambiguous_binding",
    }
    assert "gate0_factory" not in inventory._BLOCKING_KINDS
    assert "read_only" not in inventory._BLOCKING_KINDS
    source = inspect.getsource(inventory.WriterCallsite.blocking.fget)
    assert "_BLOCKING_KINDS" in source


def test_review_report_is_bound_to_revision_and_all_scanned_file_bytes() -> None:
    scan_source = inspect.getsource(inventory.scan_event_store_writers)
    input_source = inspect.getsource(inventory._scan_input)
    payload_source = inspect.getsource(inventory.WriterInventory._payload)
    assert "_SOURCE_REVISION.fullmatch" in scan_source
    assert "path.read_bytes()" in input_source
    assert "hashlib.sha256" in input_source
    assert '"source_revision"' in payload_source
    assert '"scan_input_sha256"' in payload_source
    assert '"closed"' in payload_source
    assert "trusted" not in payload_source.lower()


def test_review_source_parser_refuses_malformed_or_escaping_inputs() -> None:
    file_source = inspect.getsource(inventory._callsites_for_file)
    production_source = inspect.getsource(inventory._production_files)
    relative_source = inspect.getsource(inventory._relative_module)
    assert "SyntaxError" in file_source
    assert "UnicodeDecodeError" in file_source
    assert "resolve(strict=True)" in production_source
    assert "relative_to(resolved_package)" in production_source
    assert relative_source.count("WriterInventoryError") >= 2


def test_review_alias_resolution_cannot_promote_shadowed_writer() -> None:
    bound_source = inspect.getsource(inventory._bound_names)
    resolve_source = inspect.getsource(inventory._resolve_name)
    callsite_source = inspect.getsource(inventory._callsites_for_file)
    assert "ast.Store" in bound_source
    assert "ast.Del" in bound_source
    assert "ast.Attribute" in bound_source
    assert "root in rebound" in resolve_source
    assert 'kind = "ambiguous_binding"' in callsite_source
    assert "tracked_alias" in callsite_source


def test_review_scanner_has_no_effectful_operations() -> None:
    tree = ast.parse(inspect.getsource(inventory))
    forbidden_calls = {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "subprocess",
        "Popen",
        "system",
    }
    observed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Attribute):
                observed.add(node.func.attr)
            elif isinstance(node.func, ast.Name):
                observed.add(node.func.id)
    assert forbidden_calls.isdisjoint(observed)


def test_review_indirect_aliases_block_instead_of_becoming_factory_evidence() -> None:
    source = inspect.getsource(inventory._assignment_aliases)
    callsite_source = inspect.getsource(inventory._callsites_for_file)
    assert "ast.Assign" in source
    assert "ast.AnnAssign" in source
    assert "ast.NamedExpr" in source
    assert "raw in indirect" in callsite_source
    assert 'kind = "ambiguous_binding"' in callsite_source
