# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_tree as repository_tree
from daedalus.gates.repository_tree import (
    RepositorySourceSnapshot,
    RepositoryTreePathError,
    RepositoryTreeRaceError,
    normalize_repository_path,
    read_repository_source,
    resolve_repository_root,
)


SOURCE = b"def guarded_write(path):\n    path.write_text('ok')\n"
PATH = "daedalus/example.py"


def _write(root: Path, source: bytes = SOURCE) -> Path:
    target = root / PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source)
    return target


def test_exact_repository_source_snapshot_is_deterministic(tmp_path: Path) -> None:
    _write(tmp_path)
    first = read_repository_source(tmp_path, PATH)
    second = read_repository_source(tmp_path, PATH)
    assert first == second
    assert first.path == PATH
    assert first.source == SOURCE
    assert first.size == len(SOURCE)
    assert first.to_dict() == {
        "path": PATH,
        "source_sha256": first.source_sha256,
        "size": len(SOURCE),
    }


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/absolute.py",
        "C:/drive.py",
        "../escape.py",
        "a/../escape.py",
        "./relative.py",
        "a//b.py",
        "a\\b.py",
        "a\nb.py",
    ],
)
def test_path_grammar_fails_closed(path: str) -> None:
    with pytest.raises(
        RepositoryTreePathError,
        match="repository-relative POSIX",
    ):
        normalize_repository_path(path)


def test_root_must_be_a_real_directory(tmp_path: Path) -> None:
    with pytest.raises(RepositoryTreePathError, match="pathlib.Path"):
        resolve_repository_root(str(tmp_path))
    file_root = tmp_path / "file-root"
    file_root.write_text("not a directory", encoding="utf-8", newline="\n")
    with pytest.raises(RepositoryTreePathError, match="real directory"):
        resolve_repository_root(file_root)


def test_missing_directory_and_non_regular_target_fail(tmp_path: Path) -> None:
    with pytest.raises(RepositoryTreePathError, match="unavailable"):
        read_repository_source(tmp_path, PATH)
    directory = tmp_path / "daedalus/example.py"
    directory.mkdir(parents=True)
    with pytest.raises(RepositoryTreePathError, match="not a regular file"):
        read_repository_source(tmp_path, PATH)


def test_symlink_root_file_and_parent_are_refused(tmp_path: Path) -> None:
    if not hasattr(os, "symlink"):
        pytest.skip("symlink support unavailable")
    real_root = tmp_path / "real"
    real_root.mkdir()
    _write(real_root)
    linked_root = tmp_path / "linked-root"
    try:
        linked_root.symlink_to(real_root, target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation not permitted")
    with pytest.raises(RepositoryTreePathError, match="real directory"):
        read_repository_source(linked_root, PATH)

    file_root = tmp_path / "file-case"
    target = _write(file_root)
    outside = tmp_path / "outside.py"
    outside.write_bytes(SOURCE)
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(RepositoryTreePathError, match="contains a symlink"):
        read_repository_source(file_root, PATH)

    parent_root = tmp_path / "parent-case"
    parent_root.mkdir()
    external_dir = tmp_path / "external-dir"
    external_dir.mkdir()
    (external_dir / "example.py").write_bytes(SOURCE)
    (parent_root / "daedalus").symlink_to(
        external_dir,
        target_is_directory=True,
    )
    with pytest.raises(RepositoryTreePathError, match="contains a symlink"):
        read_repository_source(parent_root, PATH)


@pytest.mark.parametrize(
    "source",
    [
        b"valid\x00suffix",
        b"\xff\xfe",
    ],
)
def test_nul_and_non_utf8_sources_are_refused(
    tmp_path: Path,
    source: bytes,
) -> None:
    _write(tmp_path, source)
    with pytest.raises(RepositoryTreePathError):
        read_repository_source(tmp_path, PATH)


def test_source_size_is_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, b"12345")
    monkeypatch.setattr(repository_tree, "_MAX_SOURCE_BYTES", 4)
    with pytest.raises(
        RepositoryTreePathError,
        match="bounded source size",
    ):
        read_repository_source(tmp_path, PATH)


def test_file_replacement_before_open_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _write(tmp_path)
    original_open = repository_tree.os.open
    replaced = False

    def replace_then_open(path, flags):
        nonlocal replaced
        if not replaced:
            replaced = True
            moved = target.with_suffix(".old")
            os.replace(target, moved)
            target.write_bytes(SOURCE + b"# replacement\n")
        return original_open(path, flags)

    monkeypatch.setattr(repository_tree.os, "open", replace_then_open)
    with pytest.raises(
        RepositoryTreeRaceError,
        match="changed before open",
    ):
        read_repository_source(tmp_path, PATH)


def test_descriptor_identity_change_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path)
    original_fstat = repository_tree.os.fstat
    calls = 0

    def changed_second_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        current = original_fstat(descriptor)
        if calls == 2:
            return SimpleNamespace(
                st_mode=current.st_mode,
                st_dev=current.st_dev,
                st_ino=current.st_ino,
                st_size=current.st_size + 1,
            )
        return current

    monkeypatch.setattr(
        repository_tree.os,
        "fstat",
        changed_second_fstat,
    )
    with pytest.raises(
        RepositoryTreeRaceError,
        match="changed while reading",
    ):
        read_repository_source(tmp_path, PATH)


def test_incomplete_descriptor_read_is_detected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path)
    monkeypatch.setattr(repository_tree.os, "read", lambda *_: b"")
    with pytest.raises(
        RepositoryTreeRaceError,
        match="read was incomplete",
    ):
        read_repository_source(tmp_path, PATH)


def test_snapshot_rejects_detached_digest_or_size() -> None:
    with pytest.raises(ValueError, match="size differs"):
        RepositorySourceSnapshot(
            path=PATH,
            source=SOURCE,
            source_sha256="0" * 64,
            size=len(SOURCE) + 1,
        )
    with pytest.raises(ValueError, match="source_sha256 differs"):
        RepositorySourceSnapshot(
            path=PATH,
            source=SOURCE,
            source_sha256="0" * 64,
            size=len(SOURCE),
        )
