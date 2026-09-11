from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.gates.repository.write_inventory_v2 import (
    scan_repository_write_surfaces_v2,
)
from daedalus.gates.repository.write_stdlib_delta import (
    RepositoryWriteStdlibDeltaError,
    scan_repository_write_stdlib_delta,
)


REVISION = "a" * 40


def _repository(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "surface.py").write_text(source, encoding="utf-8")
    return root


def _findings(tmp_path: Path, source: str):
    return scan_repository_write_stdlib_delta(
        _repository(tmp_path, source),
        source_revision=REVISION,
    ).findings


COMPRESSED_AND_ARCHIVE_SOURCE = """
import bz2
import gzip as compression
import lzma
import tarfile
import zipfile

compression.open('a.gz', 'wb')
bz2.open('a.bz2', mode='ab')
lzma.open('a.xz', dynamic_mode)
tarfile.open('a.tar', 'w:gz')
zipfile.ZipFile('a.zip', mode='x')
compression.open('read.gz', 'rb')
tarfile.open('read.tar')
zipfile.ZipFile('read.zip')
"""


def test_compressed_and_archive_writers_are_not_laundered_as_path_open(
    tmp_path: Path,
) -> None:
    findings = _findings(tmp_path, COMPRESSED_AND_ARCHIVE_SOURCE)

    # The canonical scanner has absorbed the compressed/archive opener family,
    # so the additive delta must no longer double-report those positions.  Only
    # the family the base scanner still misses stays in the delta.
    assert [finding.callee for finding in findings] == ["zipfile.ZipFile"]
    assert [finding.kind for finding in findings] == ["archive_or_compressed_write"]
    assert all(finding.to_dict()["blocking"] is True for finding in findings)

    # The anti-laundering property itself is now proven on the merged v2
    # inventory: every writer keeps a precise callee and stays blocking, and
    # none of them is downgraded to a generic path-open surface.
    inventory = scan_repository_write_surfaces_v2(
        _repository(tmp_path / "merged", COMPRESSED_AND_ARCHIVE_SOURCE),
        source_revision=REVISION,
    )
    writers = {
        (surface.callee, surface.kind)
        for surface in inventory.surfaces
        if surface.blocking
    }
    assert ("gzip.open", "write_mode_open") in writers
    assert ("bz2.open", "write_mode_open") in writers
    assert ("lzma.open", "write_mode_open") in writers
    assert ("tarfile.open", "write_mode_open") in writers
    assert ("zipfile.ZipFile", "archive_or_compressed_write") in writers
    assert not any(
        surface.kind == "path-open"
        for surface in inventory.surfaces
        if surface.callee
        in {"gzip.open", "bz2.open", "lzma.open", "tarfile.open", "zipfile.ZipFile"}
    )


def test_fd_temp_archive_and_stream_sinks_are_blocking(tmp_path: Path) -> None:
    findings = _findings(
        tmp_path,
        """
import csv
import json
import os
import shutil
import tempfile

os.write(fd, b'x')
os.pwrite(fd, b'x', 0)
os.ftruncate(fd, 0)
shutil.make_archive('bundle', 'zip', '.')
shutil.unpack_archive('bundle.zip', '.')
tempfile.TemporaryFile()
tempfile.SpooledTemporaryFile()
json.dump(payload, stream)
csv.writer(stream)
stream.write(b'x')
stream.writelines(lines)
stream.truncate(0)
""",
    )

    callees = [finding.callee for finding in findings]
    assert "os.write" in callees
    assert "os.pwrite" in callees
    assert "os.ftruncate" in callees
    assert "shutil.make_archive" in callees
    assert "shutil.unpack_archive" in callees
    assert "tempfile.TemporaryFile" in callees
    assert "tempfile.SpooledTemporaryFile" in callees
    assert "json.dump" in callees
    assert "csv.writer" in callees
    assert "stream.write" in callees
    assert "stream.writelines" in callees
    assert "stream.truncate" not in callees
    assert all(finding.kind != "ambiguous_stdlib_binding" for finding in findings)


def test_extended_process_creation_surfaces_remain_unknown_effects(
    tmp_path: Path,
) -> None:
    findings = _findings(
        tmp_path,
        """
import asyncio
import concurrent.futures as futures
import multiprocessing as mp
import os
import pty
import subprocess

asyncio.create_subprocess_exec('git', 'status')
asyncio.create_subprocess_shell('git status')
subprocess.getoutput('git status')
subprocess.getstatusoutput('git status')
os.execv('/bin/tool', ['tool'])
os.posix_spawn('/bin/tool', ['tool'], {})
pty.spawn(['/bin/tool'])
mp.Process(target=worker)
futures.ProcessPoolExecutor()
""",
    )

    assert len(findings) == 9
    assert all(
        finding.kind == "process_effect_unknown" for finding in findings
    )


ALIAS_AND_REBINDING_SOURCE = """
from gzip import open as compressed_open
from os import write

compressed_open('a.gz', 'wb')
write(fd, b'x')

def use(write):
    write(fd, b'x')
"""


def test_aliases_and_rebindings_fail_closed(tmp_path: Path) -> None:
    findings = _findings(tmp_path, ALIAS_AND_REBINDING_SOURCE)

    # The aliased `from gzip import open as compressed_open` callsite is now
    # owned by the canonical scanner, so only the rebound `write` names are
    # left for the additive delta to report.
    assert [finding.kind for finding in findings] == [
        "ambiguous_stdlib_binding",
        "ambiguous_stdlib_binding",
    ]

    # Fail-closed is the property under test: no aliased or rebound name may
    # escape the merged inventory, and every one of them stays blocking.
    inventory = scan_repository_write_surfaces_v2(
        _repository(tmp_path / "merged", ALIAS_AND_REBINDING_SOURCE),
        source_revision=REVISION,
    )
    assert [
        (surface.line, surface.callee, surface.kind) for surface in inventory.surfaces
    ] == [
        (5, "gzip.open", "ambiguous_binding"),
        (6, "write", "ambiguous_stdlib_binding"),
        (9, "write", "ambiguous_stdlib_binding"),
    ]
    assert len(inventory.blockers) == 3


def test_delta_is_bound_to_base_inventory_and_all_production_bytes(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path, "import gzip\ngzip.open('a.gz', 'wb')\n")
    first = scan_repository_write_stdlib_delta(
        root,
        source_revision=REVISION,
    )
    second = scan_repository_write_stdlib_delta(
        root,
        source_revision=REVISION,
    )

    assert first == second
    assert first.digest == second.digest
    assert first.base_inventory_digest == second.base_inventory_digest
    assert first.to_dict()["canonical_scanner_integrated"] is False
    assert first.to_dict()["closed"] is False
    assert "canonical-scanner-integration-missing" in first.to_dict()["blockers"]

    (root / "daedalus" / "surface.py").write_text(
        "import gzip\ngzip.open('b.gz', 'wb')\n",
        encoding="utf-8",
    )
    changed = scan_repository_write_stdlib_delta(
        root,
        source_revision=REVISION,
    )
    assert changed.scan_input_sha256 != first.scan_input_sha256
    assert changed.base_inventory_digest != first.base_inventory_digest
    assert changed.digest != first.digest


def test_malformed_revision_and_source_refuse(tmp_path: Path) -> None:
    good = _repository(tmp_path, "value = 1\n")
    for revision in ("main", "A" * 40, "f" * 39, True):
        with pytest.raises(RepositoryWriteStdlibDeltaError):
            scan_repository_write_stdlib_delta(
                good,
                source_revision=revision,  # type: ignore[arg-type]
            )

    broken = _repository(tmp_path / "broken", "def broken(:\n")
    with pytest.raises(RepositoryWriteStdlibDeltaError):
        scan_repository_write_stdlib_delta(
            broken,
            source_revision=REVISION,
        )
