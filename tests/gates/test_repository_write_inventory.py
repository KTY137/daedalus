from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus.gates.repository.write_inventory import (
    RepositoryWriteCallsite,
    RepositoryWriteInventory,
    RepositoryWriteInventoryError,
    scan_repository_write_surfaces,
)


REVISION = "a" * 40


def _repository(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for relative, source in files.items():
        path = package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    return root


def _sites(tmp_path: Path, source: str) -> tuple[RepositoryWriteCallsite, ...]:
    root = _repository(tmp_path, {"surface.py": source})
    return scan_repository_write_surfaces(
        root,
        source_revision=REVISION,
    ).callsites


def test_inventory_is_deterministic_and_bound_to_all_production_bytes(
    tmp_path: Path,
) -> None:
    root = _repository(
        tmp_path,
        {
            "a.py": "from pathlib import Path\nPath('x').write_text('x')\n",
            "nested/b.py": "value = 1\n",
        },
    )

    first = scan_repository_write_surfaces(root, source_revision=REVISION)
    second = scan_repository_write_surfaces(root, source_revision=REVISION)

    assert first == second
    assert first.digest == second.digest
    assert first.files_scanned == 3
    assert first.closed is False
    assert first.blockers == first.callsites
    assert first.to_dict()["primary_checkout_target_proven"] is False
    assert first.to_dict()["scope"] == "potential_repository_write_surface"

    (root / "daedalus" / "nested" / "b.py").write_text(
        "value = 2\n",
        encoding="utf-8",
    )
    changed = scan_repository_write_surfaces(root, source_revision=REVISION)
    assert changed.scan_input_sha256 != first.scan_input_sha256
    assert changed.digest != first.digest


def test_filesystem_path_and_open_writes_are_blocking(tmp_path: Path) -> None:
    sites = _sites(
        tmp_path,
        """
import os
import shutil as copy_api
from pathlib import Path
from tempfile import mkstemp

os.replace('a', 'b')
copy_api.copy2('a', 'b')
Path('x').write_bytes(b'x')
mkstemp()
open('a', 'wb')
open('b', mode='a')
open('read-only')
""",
    )

    kinds = [site.kind for site in sites]
    operations = [site.operation for site in sites]
    assert kinds.count("filesystem_mutation") == 3
    assert "path_mutation" in kinds
    assert kinds.count("write_mode_open") == 2
    assert "replace" in operations
    assert "copy2" in operations
    assert "write_bytes" in operations
    assert not any(site.operation == "read-only" for site in sites)
    assert all(site.blocking for site in sites)


def test_dynamic_open_and_os_open_flags_fail_closed(tmp_path: Path) -> None:
    sites = _sites(
        tmp_path,
        """
import os

def use(path, mode, flags):
    open(path, mode)
    os.open(path, os.O_RDONLY)
    os.open(path, os.O_WRONLY | os.O_CREAT)
    os.open(path, flags)
""",
    )

    assert [site.kind for site in sites] == [
        "ambiguous_open_mode",
        "os_open_write",
        "ambiguous_os_open_flags",
    ]


def test_sqlite_modes_are_projected_without_laundering_dynamic_paths(
    tmp_path: Path,
) -> None:
    sites = _sites(
        tmp_path,
        """
import sqlite3

sqlite3.connect('file:state.db?mode=ro', uri=True)
sqlite3.connect('file:state.db?mode=rw', uri=True)
sqlite3.connect('state.db')

def dynamic(path):
    sqlite3.connect(path, uri=True)
""",
    )

    assert [site.kind for site in sites] == [
        "sqlite_read_only",
        "sqlite_write_or_create",
        "sqlite_write_or_create",
        "ambiguous_sqlite_mode",
    ]
    assert sites[0].blocking is False
    assert all(site.blocking for site in sites[1:])


def test_process_surfaces_never_become_trusted_by_literal_parsing(
    tmp_path: Path,
) -> None:
    sites = _sites(
        tmp_path,
        """
import subprocess as sp

sp.run(['git', 'apply', 'candidate.patch'])
sp.check_output(['git', 'rev-parse', 'HEAD'])
sp.Popen(command)
""",
    )

    assert [site.kind for site in sites] == [
        "git_mutation_process",
        "process_effect_unknown",
        "process_effect_unknown",
    ]
    assert sites[0].operation == "git apply"
    assert sites[1].operation == "git rev-parse"
    assert sites[2].operation == "dynamic-command"
    assert all(site.blocking for site in sites)


def test_rebound_and_indirect_mutators_are_ambiguous_blockers(
    tmp_path: Path,
) -> None:
    sites = _sites(
        tmp_path,
        """
from os import unlink
from pathlib import Path

remove_file = unlink
remove_file('x')

def write(path):
    path.write_text('x')
""",
    )

    assert [site.kind for site in sites] == [
        "ambiguous_binding",
        "ambiguous_binding",
    ]
    assert all(site.blocking for site in sites)


def test_malformed_source_and_revision_refuse(tmp_path: Path) -> None:
    root = _repository(tmp_path, {"broken.py": "def broken(:\n"})
    with pytest.raises(RepositoryWriteInventoryError):
        scan_repository_write_surfaces(root, source_revision=REVISION)

    good = _repository(tmp_path / "other", {"ok.py": "value = 1\n"})
    for revision in ("main", "A" * 40, "f" * 39, True):
        with pytest.raises(RepositoryWriteInventoryError):
            scan_repository_write_surfaces(
                good,
                source_revision=revision,  # type: ignore[arg-type]
            )


def test_symlinked_package_and_python_files_refuse(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink unsupported")
    root = tmp_path / "repo"
    root.mkdir()
    real = root / "real_daedalus"
    real.mkdir()
    (real / "__init__.py").write_text("", encoding="utf-8")
    try:
        os.symlink(real, root / "daedalus", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")
    with pytest.raises(RepositoryWriteInventoryError):
        scan_repository_write_surfaces(root, source_revision=REVISION)


def test_contract_objects_reject_coercible_or_inconsistent_values() -> None:
    site = RepositoryWriteCallsite(
        path="daedalus/a.py",
        line=1,
        column=0,
        kind="filesystem_mutation",
        callee="os.unlink",
        operation="unlink",
    )
    report = RepositoryWriteInventory(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="b" * 64,
        files_scanned=1,
        callsites=(site,),
    )
    payload = report.to_dict()
    assert payload["blocker_count"] == 1
    assert payload["closed"] is False
    assert json.loads(json.dumps(payload))["digest"] == report.digest

    with pytest.raises(ValueError):
        RepositoryWriteCallsite(
            path="../escape.py",
            line=1,
            column=0,
            kind="filesystem_mutation",
            callee="os.unlink",
            operation="unlink",
        )
    with pytest.raises(ValueError):
        RepositoryWriteInventory(
            source_revision=REVISION,
            package_root="daedalus",
            scan_input_sha256="b" * 64,
            files_scanned=1,
            callsites=(site, site),
        )
