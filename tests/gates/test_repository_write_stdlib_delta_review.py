# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.gates.repository_write_stdlib_delta as delta


def _source_tree() -> tuple[str, ast.Module]:
    source = inspect.getsource(delta)
    return source, ast.parse(source)


def test_delta_has_no_registry_patch_or_effect_authority() -> None:
    source, tree = _source_tree()

    assert "canonical_scanner_integrated\": False" in source
    assert "\"closed\": False" in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "EffectLease" not in source
    assert "sqlite3" not in source
    assert "git " not in source.lower()

    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(
                item.name.split(".", 1)[0] for item in node.names
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])
    assert "subprocess" not in imported_roots
    assert "sqlite3" not in imported_roots

    forbidden_calls = {
        "write_text",
        "write_bytes",
        "unlink",
        "replace",
        "rename",
        "mkdir",
        "rmdir",
        "run",
        "Popen",
        "system",
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called_attributes.intersection(forbidden_calls)


def test_false_negative_families_are_explicit_and_blocking() -> None:
    assert {
        "gzip.open",
        "bz2.open",
        "lzma.open",
        "tarfile.open",
        "zipfile.ZipFile",
    } <= set(delta._MODE_OPENERS)
    assert {
        "os.write",
        "os.pwrite",
        "os.ftruncate",
        "shutil.make_archive",
        "shutil.unpack_archive",
        "tempfile.TemporaryFile",
        "tempfile.SpooledTemporaryFile",
    } <= delta._UNCONDITIONAL_FILESYSTEM
    assert {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "os.execv",
        "os.posix_spawn",
        "pty.spawn",
        "multiprocessing.Process",
        "concurrent.futures.ProcessPoolExecutor",
    } <= delta._PROCESS_SURFACES
    assert {
        "write",
        "writelines",
        "writerow",
        "writerows",
        "truncate",
    } == delta._GENERIC_SINK_METHODS

    source, _ = _source_tree()
    assert '"blocking": True' in source
    assert "sqlite_read_only" not in source
    assert "trusted" in delta.__doc__.lower()


def test_delta_is_bound_to_base_digest_and_source_bytes_before_return() -> None:
    _, tree = _source_tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "scan_repository_write_stdlib_delta"
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    names = []
    for call in calls:
        if isinstance(call.func, ast.Name):
            names.append(call.func.id)
        elif isinstance(call.func, ast.Attribute):
            names.append(call.func.attr)

    assert names.count("scan_repository_write_surfaces") == 1
    assert names.count("_production_files") == 1
    assert names.count("_scan_input") == 1
    assert names.count("RepositoryWriteStdlibDelta") == 1

    returned = next(
        node.value
        for node in ast.walk(function)
        if isinstance(node, ast.Return)
    )
    assert isinstance(returned, ast.Call)
    keywords = {keyword.arg for keyword in returned.keywords}
    assert {
        "source_revision",
        "base_inventory_digest",
        "scan_input_sha256",
        "files_scanned",
        "findings",
    } == keywords


def test_repository_relative_path_contract_rejects_normalization_aliases() -> None:
    assert delta._safe_relative_posix("daedalus/a.py") is True
    for value in (
        "../a.py",
        "daedalus/../a.py",
        "./daedalus/a.py",
        "/daedalus/a.py",
        "daedalus\\a.py",
        "",
    ):
        assert delta._safe_relative_posix(value) is False


def test_module_path_is_inside_expected_strangler_boundary() -> None:
    path = Path(inspect.getsourcefile(delta) or "").as_posix()
    assert path.endswith("daedalus/gates/repository_write_stdlib_delta.py")
