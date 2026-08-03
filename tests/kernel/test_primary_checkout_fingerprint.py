from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from daedalus.kairos.gated_writes import _primary_checkout_fingerprint
from daedalus.kernel.promotion import PromotionAuthorizationError


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
    _git(root, "add", ".gitignore", "tracked.txt")
    _git(root, "commit", "-m", "initial")
    return root


def test_repeated_clean_fingerprint_is_stable(tmp_path) -> None:
    root = _repository(tmp_path)
    first, first_clean = _primary_checkout_fingerprint(root)
    second, second_clean = _primary_checkout_fingerprint(root)
    assert first == second
    assert len(first) == 64
    assert first_clean is True
    assert second_clean is True


def test_tracked_staged_and_untracked_changes_are_never_clean(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline, clean = _primary_checkout_fingerprint(root)
    assert clean is True

    (root / "tracked.txt").write_text("beta\n", encoding="utf-8")
    modified, modified_clean = _primary_checkout_fingerprint(root)
    assert modified != baseline
    assert modified_clean is False

    _git(root, "add", "tracked.txt")
    staged, staged_clean = _primary_checkout_fingerprint(root)
    assert staged != baseline
    assert staged_clean is False

    (root / "untracked.txt").write_text("new\n", encoding="utf-8")
    untracked, untracked_clean = _primary_checkout_fingerprint(root)
    assert untracked != baseline
    assert untracked_clean is False


def test_ignored_runtime_state_and_ref_only_changes_do_not_dirty_checkout(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline = _primary_checkout_fingerprint(root)

    runtime = root / ".runtime"
    runtime.mkdir()
    (runtime / "ledger.sqlite3").write_bytes(b"runtime state")
    assert _primary_checkout_fingerprint(root) == baseline

    head = _git(root, "rev-parse", "HEAD")
    _git(root, "branch", "integration-side-ref", head)
    assert _primary_checkout_fingerprint(root) == baseline


def test_head_change_changes_clean_identity(tmp_path) -> None:
    root = _repository(tmp_path)
    baseline, baseline_clean = _primary_checkout_fingerprint(root)
    assert baseline_clean
    (root / "second.txt").write_text("second\n", encoding="utf-8")
    _git(root, "add", "second.txt")
    _git(root, "commit", "-m", "second")
    changed, changed_clean = _primary_checkout_fingerprint(root)
    assert changed != baseline
    assert changed_clean


def test_non_repository_fails_closed(tmp_path) -> None:
    empty = tmp_path / "not-a-repository"
    empty.mkdir()
    with pytest.raises(PromotionAuthorizationError, match="Git query failed"):
        _primary_checkout_fingerprint(empty)
