from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from daedalus.spine import source_state
from daedalus.spine.source_state import InexactSourceState, fingerprint_source


def _git(repo: Path, *args: str) -> bytes:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    return proc.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "source-state@example.invalid")
    _git(root, "config", "user.name", "Source State Test")
    _git(root, "config", "core.autocrlf", "false")
    (root / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (root / "tracked.txt").write_bytes(b"committed\n")
    _git(root, "add", ".gitignore", "tracked.txt")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


def test_clean_fingerprint_is_exact_deterministic_and_read_only(repo: Path) -> None:
    index = repo / ".git" / "index"
    index_before = (index.read_bytes(), index.stat().st_mtime_ns)
    first = fingerprint_source(repo)
    second = fingerprint_source(repo / ".git" / "..")

    assert first == second
    assert first.head == _git(repo, "rev-parse", "HEAD").decode().strip()
    assert first.tree_sha == _git(
        repo, "rev-parse", "HEAD^{tree}"
    ).decode().strip()
    assert first.status_porcelain_v1_z == b""
    assert first.status_sha256 == hashlib.sha256(b"").hexdigest()
    assert first.clean is True
    assert first.exact is True
    assert first.exact_clean_head is True
    assert first.require_exact() is first
    assert first.tracked_path_count == 2
    assert first.gitlinks == ()
    assert first.untracked_files == ()
    assert len(first.tracked_tree_sha256) == 64
    assert len(first.fingerprint_sha256) == 64
    json.dumps(first.to_dict(), sort_keys=True)

    assert (index.read_bytes(), index.stat().st_mtime_ns) == index_before
    assert _git(repo, "status", "--porcelain=v1", "-z") == b""


def test_status_with_optional_locks_disabled_does_not_refresh_index(
    repo: Path,
) -> None:
    tracked = repo / "tracked.txt"
    tracked_stat = tracked.stat()
    os.utime(
        tracked,
        ns=(tracked_stat.st_atime_ns, tracked_stat.st_mtime_ns + 2_000_000_000),
    )
    index = repo / ".git" / "index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)

    status = source_state._status_porcelain_v1_z(repo)

    assert status == b""
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert not (repo / ".git" / "index.lock").exists()


def test_dirty_exact_fingerprint_binds_tracked_and_nul_safe_untracked_bytes(
    repo: Path,
) -> None:
    clean = fingerprint_source(repo)
    (repo / "tracked.txt").write_bytes(b"changed working tree\n")
    odd_name = (
        "odd name\nwith newline.txt"
        if os.name != "nt"
        else "odd name - destination.txt"
    )
    odd_bytes = b"untracked\x00payload\n"
    (repo / odd_name).write_bytes(odd_bytes)
    (repo / "ignored.log").write_bytes(b"must not enter evidence")

    first = fingerprint_source(repo)
    second = fingerprint_source(repo)
    by_path = {item.path_bytes: item for item in first.untracked_files}
    odd_path = os.fsencode(odd_name)

    assert first == second
    assert first.clean is False
    assert first.exact is True
    assert first.exact_clean_head is False
    assert first.tracked_tree_sha256 != clean.tracked_tree_sha256
    assert b" M tracked.txt\0" in first.status_porcelain_v1_z
    assert b"?? " + odd_path + b"\0" in first.status_porcelain_v1_z
    assert b"ignored.log" not in first.status_porcelain_v1_z
    assert set(by_path) == {odd_path}
    assert by_path[odd_path].kind == "regular"
    assert by_path[odd_path].sha256 == hashlib.sha256(odd_bytes).hexdigest()
    assert by_path[odd_path].size == len(odd_bytes)


def test_checked_out_gitlink_is_recursively_bound_without_becoming_inexact(
    repo: Path, tmp_path: Path
) -> None:
    upstream = tmp_path / "toml-test-upstream"
    upstream.mkdir()
    _git(upstream, "init", "-q")
    _git(upstream, "config", "user.email", "source-state@example.invalid")
    _git(upstream, "config", "user.name", "Source State Test")
    _git(upstream, "config", "core.autocrlf", "false")
    (upstream / "fixture.toml").write_bytes(b"answer = 42\n")
    _git(upstream, "add", "fixture.toml")
    _git(upstream, "commit", "-q", "-m", "pinned fixture")
    pinned_oid = _git(upstream, "rev-parse", "HEAD").decode().strip()

    _git(
        repo,
        "-c",
        "protocol.file.allow=always",
        "submodule",
        "add",
        "-q",
        os.fspath(upstream),
        "vendor/toml-test",
    )
    _git(repo, "commit", "-q", "-am", "add pinned toml-test fixture")
    assert _git(
        repo, "ls-files", "--stage", "vendor/toml-test"
    ).startswith(b"160000 ")

    clean = fingerprint_source(repo)

    assert clean.clean is True
    assert clean.exact is True
    assert len(clean.gitlinks) == 1
    gitlink = clean.gitlinks[0]
    assert gitlink.path_bytes == b"vendor/toml-test"
    assert gitlink.index_oid == pinned_oid
    assert gitlink.state == "checked-out"
    assert gitlink.initialized is True
    assert gitlink.matches_index is True
    assert gitlink.checkout is not None
    assert gitlink.checkout.exact_clean_head is True
    json.dumps(clean.to_dict(), sort_keys=True)

    checkout_file = repo / "vendor" / "toml-test" / "fixture.toml"
    checkout_file.write_bytes(b"answer = 43\n")
    dirty = fingerprint_source(repo)

    assert dirty.clean is False
    assert dirty.exact is True
    assert dirty.tracked_tree_sha256 != clean.tracked_tree_sha256
    dirty_gitlink = dirty.gitlinks[0]
    assert dirty_gitlink.matches_index is True
    assert dirty_gitlink.checkout is not None
    assert dirty_gitlink.checkout.clean is False
    assert dirty_gitlink.checkout.exact is True


def test_untracked_symlink_is_flagged_and_exact_mode_refuses(repo: Path) -> None:
    link = repo / "untracked-link"
    try:
        link.symlink_to(repo / "tracked.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"host cannot create symlinks: {exc}")

    fingerprint = fingerprint_source(repo)

    assert fingerprint.clean is False
    assert fingerprint.exact is False
    assert [(item.path_bytes, item.kind, item.sha256) for item in fingerprint.untracked_files] == [
        (b"untracked-link", "symlink", None)
    ]
    assert [issue.code for issue in fingerprint.issues] == ["untracked_symlink"]
    with pytest.raises(InexactSourceState) as excinfo:
        fingerprint.require_exact()
    assert excinfo.value.fingerprint is fingerprint


def test_unreadable_untracked_file_is_flagged_without_a_fake_digest(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = repo / "secret.txt"
    secret.write_bytes(b"not observable")
    real_digest = source_state._digest_regular_file

    def deny(path: Path, expected: os.stat_result):
        if path == secret:
            raise PermissionError("deterministic unreadable-file fixture")
        return real_digest(path, expected)

    monkeypatch.setattr(source_state, "_digest_regular_file", deny)
    fingerprint = fingerprint_source(repo)

    assert fingerprint.exact is False
    assert len(fingerprint.untracked_files) == 1
    evidence = fingerprint.untracked_files[0]
    assert evidence.path_bytes == b"secret.txt"
    assert evidence.kind == "regular"
    assert evidence.sha256 is None
    assert evidence.size is None
    assert [issue.code for issue in fingerprint.issues] == ["untracked_unreadable"]
