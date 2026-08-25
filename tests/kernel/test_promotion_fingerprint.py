from __future__ import annotations

import os
from pathlib import Path

import pytest

from daedalus.kernel.promotion_fingerprint import (
    PrimaryCheckoutFingerprintError,
    fingerprint_primary_checkout,
)


def test_fingerprint_is_deterministic_and_tracks_source_bytes(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")

    first = fingerprint_primary_checkout(root)
    assert fingerprint_primary_checkout(root) == first

    source.write_text("value = 2\n", encoding="utf-8")
    assert fingerprint_primary_checkout(root) != first


def test_repository_control_roots_do_not_change_source_identity(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / ".git").mkdir(parents=True)
    (root / ".daedalus").mkdir()
    (root / "source.py").write_text("value = 1\n", encoding="utf-8")

    first = fingerprint_primary_checkout(root)
    (root / ".git" / "index").write_bytes(b"changed")
    (root / ".daedalus" / "spine.sqlite3").write_bytes(b"changed")
    assert fingerprint_primary_checkout(root) == first


def test_symlink_entry_and_redirected_root_are_refused(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    with pytest.raises(PrimaryCheckoutFingerprintError, match="non-regular"):
        fingerprint_primary_checkout(root)

    link.unlink()
    redirected = tmp_path / "redirected"
    redirected.symlink_to(root, target_is_directory=True)
    with pytest.raises(PrimaryCheckoutFingerprintError, match="cannot be a symlink"):
        fingerprint_primary_checkout(redirected)


def test_executable_bit_is_identity_on_posix(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Windows does not expose the POSIX executable bit contract")
    root = tmp_path / "repo"
    root.mkdir()
    executable = root / "tool.sh"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o644)
    first = fingerprint_primary_checkout(root)
    executable.chmod(0o755)
    assert fingerprint_primary_checkout(root) != first


def test_non_directory_and_missing_roots_are_refused(tmp_path: Path) -> None:
    regular = tmp_path / "file"
    regular.write_text("x", encoding="utf-8")
    with pytest.raises(PrimaryCheckoutFingerprintError, match="real directory"):
        fingerprint_primary_checkout(regular)
    with pytest.raises(PrimaryCheckoutFingerprintError, match="existing directory"):
        fingerprint_primary_checkout(tmp_path / "missing")
