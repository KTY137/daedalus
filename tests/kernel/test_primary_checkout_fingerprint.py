from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from daedalus.kairos.gated_writes import _primary_checkout_fingerprint


def _git(root: Path, *args: str) -> str:
    process = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} failed: {process.stderr.strip()}"
        )
    return process.stdout.strip()


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init")
    _git(root, "config", "user.name", "Daedalus Test")
    _git(root, "config", "user.email", "daedalus@example.invalid")
    (root / ".gitignore").write_text(".runtime/\n", encoding="utf-8")
    (root / "tracked.txt").write_text("alpha\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "data.bin").write_bytes(b"\x00\x01\x02")
    _git(root, "add", ".gitignore", "tracked.txt", "nested/data.bin")
    _git(root, "commit", "-m", "initial")
    return root


def test_repeated_fingerprint_is_stable_for_an_idle_checkout(tmp_path) -> None:
    root = _repository(tmp_path)
    first = _primary_checkout_fingerprint(root)
    second = _primary_checkout_fingerprint(root)
    assert first == second
    assert len(first) == 64


def test_tracked_bytes_index_and_nonignored_untracked_files_change_identity(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline = _primary_checkout_fingerprint(root)

    (root / "tracked.txt").write_text("beta\n", encoding="utf-8")
    modified = _primary_checkout_fingerprint(root)
    assert modified != baseline

    _git(root, "add", "tracked.txt")
    staged = _primary_checkout_fingerprint(root)
    assert staged != baseline
    assert staged != modified

    (root / "untracked.txt").write_text("new\n", encoding="utf-8")
    untracked = _primary_checkout_fingerprint(root)
    assert untracked not in {baseline, modified, staged}


def test_ignored_runtime_state_and_ref_only_changes_do_not_mutate_primary_identity(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline = _primary_checkout_fingerprint(root)

    runtime = root / ".runtime"
    runtime.mkdir()
    (runtime / "ledger.sqlite3").write_bytes(b"runtime state")
    assert _primary_checkout_fingerprint(root) == baseline

    head = _git(root, "rev-parse", "HEAD")
    _git(root, "branch", "integration-side-ref", head)
    assert _primary_checkout_fingerprint(root) == baseline


def test_head_change_changes_identity_even_when_worktree_bytes_match(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline = _primary_checkout_fingerprint(root)
    (root / "second.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "second.txt")
    _git(root, "commit", "-m", "second")
    assert _primary_checkout_fingerprint(root) != baseline


def test_symlink_target_is_part_of_identity_when_supported(tmp_path) -> None:
    root = _repository(tmp_path)
    link = root / "link.txt"
    try:
        os.symlink("tracked.txt", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    first = _primary_checkout_fingerprint(root)
    link.unlink()
    os.symlink("nested/data.bin", link)
    assert _primary_checkout_fingerprint(root) != first


def test_non_repository_and_unstable_inventory_fail_closed(tmp_path, monkeypatch) -> None:
    empty = tmp_path / "not-a-repository"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="git rev-parse"):
        _primary_checkout_fingerprint(empty)

    root = _repository(tmp_path / "unstable")
    import daedalus.kairos.gated_writes as gated_writes

    original = gated_writes._primary_inventory
    calls = 0

    def unstable(repo):
        nonlocal calls
        calls += 1
        value = original(repo)
        if calls == 2:
            return (value[0], value[1], value[2] + b"changed", value[3])
        return value

    monkeypatch.setattr(gated_writes, "_primary_inventory", unstable)
    with pytest.raises(RuntimeError, match="changed during fingerprint"):
        gated_writes._primary_checkout_fingerprint(root)
