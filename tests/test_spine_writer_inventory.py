from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus.spine.ledger import ROOT
from daedalus.spine.writer_inventory import (
    WriterCallsite,
    WriterInventory,
    WriterInventoryError,
    scan_event_store_writers,
)


REVISION = "a" * 40


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _kinds(report: WriterInventory) -> list[str]:
    return [site.kind for site in report.callsites]


def test_inventory_classifies_factory_readers_writers_and_ambiguous_options(
    tmp_path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "daedalus/runtime.py": """
from daedalus.spine import SpineLedger, open_gate0_spine_writer


def build(path, flag, options):
    open_gate0_spine_writer(path)
    SpineLedger(path, read_only=True)
    SpineLedger(path)
    SpineLedger(path, read_only=False)
    SpineLedger(path, read_only=flag)
    SpineLedger(path, **options)
""",
        },
    )

    report = scan_event_store_writers(root, source_revision=REVISION)

    assert report.source_revision == REVISION
    assert report.package_root == "daedalus"
    assert report.files_scanned == 2
    assert _kinds(report) == [
        "gate0_factory",
        "read_only",
        "legacy_direct",
        "legacy_direct",
        "ambiguous_direct",
        "ambiguous_direct",
    ]
    assert report.closed is False
    assert len(report.blockers) == 4
    assert report.to_dict()["digest"] == report.digest
    assert len(report.digest) == 64


def test_inventory_resolves_module_absolute_relative_and_aliased_imports(
    tmp_path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "daedalus/a.py": """
import daedalus.spine as ds
import daedalus.spine.ledger as ledger


def build(path):
    ds.open_gate0_spine_writer(path)
    ds.SpineLedger(path, read_only=True)
    ledger.SpineLedger(path)
""",
            "daedalus/sub/__init__.py": "",
            "daedalus/sub/b.py": """
from ..spine import SpineLedger as Store
from ..spine.durability import open_gate0_spine_writer as admit


def build(path):
    Store(path)
    admit(path)
""",
        },
    )

    report = scan_event_store_writers(root, source_revision=REVISION)

    assert _kinds(report) == [
        "gate0_factory",
        "read_only",
        "legacy_direct",
        "legacy_direct",
        "gate0_factory",
    ]
    assert [site.path for site in report.callsites] == [
        "daedalus/a.py",
        "daedalus/a.py",
        "daedalus/a.py",
        "daedalus/sub/b.py",
        "daedalus/sub/b.py",
    ]


def test_shadowed_conflicting_and_indirect_bindings_block_instead_of_disappearing(
    tmp_path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "daedalus/shadowed.py": """
from daedalus.spine import SpineLedger, open_gate0_spine_writer

Alias = SpineLedger


def shadow(open_gate0_spine_writer, path):
    open_gate0_spine_writer(path)


def indirect(path):
    Alias(path)
""",
            "daedalus/module_shadow.py": """
import daedalus.spine as ds

ds.open_gate0_spine_writer = lambda path: None


def build(path):
    ds.open_gate0_spine_writer(path)
""",
            "daedalus/conflict.py": """
from daedalus.spine import SpineLedger as Store
from daedalus.spine.durability import open_gate0_spine_writer as Store


def build(path):
    Store(path)
""",
        },
    )

    report = scan_event_store_writers(root, source_revision=REVISION)

    assert _kinds(report) == [
        "ambiguous_binding",
        "ambiguous_binding",
        "ambiguous_binding",
        "ambiguous_binding",
    ]
    assert all(site.blocking for site in report.callsites)
    assert report.closed is False


def test_inventory_is_deterministic_and_bound_to_all_production_bytes(tmp_path) -> None:
    files = {
        "daedalus/a.py": "from daedalus.spine import SpineLedger\nSpineLedger('a')\n",
        "daedalus/b.py": "VALUE = 1\n",
    }
    first = _repository(tmp_path / "first", files)
    second = _repository(tmp_path / "second", dict(reversed(tuple(files.items()))))

    first_report = scan_event_store_writers(first, source_revision=REVISION)
    second_report = scan_event_store_writers(second, source_revision=REVISION)
    assert first_report == second_report
    assert first_report.digest == second_report.digest

    (second / "daedalus" / "b.py").write_text("VALUE = 2\n", encoding="utf-8")
    changed = scan_event_store_writers(second, source_revision=REVISION)
    assert changed.callsites == second_report.callsites
    assert changed.scan_input_sha256 != second_report.scan_input_sha256
    assert changed.digest != second_report.digest


def test_revision_and_repository_shape_are_fail_closed(tmp_path) -> None:
    root = _repository(tmp_path, {"daedalus/app.py": "VALUE = 1\n"})
    for revision in ("", "A" * 40, "a" * 39, "g" * 40, "a" * 64):
        with pytest.raises(WriterInventoryError, match="source_revision"):
            scan_event_store_writers(root, source_revision=revision)

    with pytest.raises(WriterInventoryError, match="does not exist"):
        scan_event_store_writers(tmp_path / "missing", source_revision=REVISION)

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(WriterInventoryError, match="daedalus package"):
        scan_event_store_writers(empty, source_revision=REVISION)


def test_malformed_source_and_relative_import_escape_are_refused(tmp_path) -> None:
    malformed = _repository(
        tmp_path / "malformed",
        {"daedalus/bad.py": "def broken(:\n"},
    )
    with pytest.raises(WriterInventoryError, match="cannot parse"):
        scan_event_store_writers(malformed, source_revision=REVISION)

    escaping = _repository(
        tmp_path / "escaping",
        {
            "daedalus/sub/__init__.py": "",
            "daedalus/sub/bad.py": "from ...outside import SpineLedger\n",
        },
    )
    with pytest.raises(WriterInventoryError, match="relative import escapes"):
        scan_event_store_writers(escaping, source_revision=REVISION)


def test_production_python_symlink_escape_is_refused(tmp_path) -> None:
    root = _repository(tmp_path, {"daedalus/app.py": "VALUE = 1\n"})
    outside = tmp_path / "outside.py"
    outside.write_text("VALUE = 2\n", encoding="utf-8")
    link = root / "daedalus" / "escape.py"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(WriterInventoryError, match="escapes"):
        scan_event_store_writers(root, source_revision=REVISION)


def test_records_validate_canonical_shape() -> None:
    site = WriterCallsite(
        path="daedalus/app.py",
        line=1,
        column=0,
        kind="legacy_direct",
        callee="daedalus.spine.SpineLedger",
    )
    report = WriterInventory(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="b" * 64,
        files_scanned=1,
        callsites=(site,),
    )
    assert report.blockers == (site,)
    assert report.to_dict()["blocker_count"] == 1
    with pytest.raises(ValueError, match="package_root"):
        WriterInventory(
            source_revision=REVISION,
            package_root="..\\daedalus",
            scan_input_sha256="b" * 64,
            files_scanned=1,
            callsites=(site,),
        )
    with pytest.raises(ValueError, match="sorted"):
        WriterInventory(
            source_revision=REVISION,
            package_root="daedalus",
            scan_input_sha256="b" * 64,
            files_scanned=1,
            callsites=(
                WriterCallsite(
                    path="daedalus/z.py",
                    line=2,
                    column=0,
                    kind="read_only",
                    callee="daedalus.spine.SpineLedger",
                ),
                site,
            ),
        )


def test_current_repository_scan_is_revision_bound_and_finds_selected_factory() -> None:
    report = scan_event_store_writers(ROOT, source_revision=REVISION)
    attempt_sites = [
        site
        for site in report.callsites
        if site.path == "daedalus/kernel/attempt_ledger.py"
    ]
    assert any(site.kind == "gate0_factory" for site in attempt_sites)
    assert report.files_scanned > 1
    assert report.source_revision == REVISION
    encoded = json.dumps(report.to_dict(), sort_keys=True)
    assert "scan_input_sha256" in encoded
    assert "source_revision" in encoded
    assert os.path.isabs(str(ROOT))
