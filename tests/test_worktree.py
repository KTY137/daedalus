# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

import json
import os
import shutil
import stat
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import daedalus.kairos.worktree as worktree_module
from daedalus.kairos.worktree import (
    ALLOC_SCHEMA,
    GitWorktreeManager,
    WorktreeContainmentError,
    WorktreeRemovalRace,
)
from daedalus.storage import StorageUnavailable

@pytest.fixture
def worktree_root(tmp_path, monkeypatch):
    """Pin worktree placement to an isolated temp root for deterministic tests."""
    root = tmp_path / "wt_root"
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(root))
    return root

@pytest.fixture
def temp_git_repo(tmp_path):
    """Creates a temporary git repository with an initial commit."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def run_git(*args):
        subprocess.run(['git', *args], cwd=repo_path, check=True, capture_output=True)

    run_git('init')

    # Configure git for tests
    run_git('config', 'user.name', 'Test User')
    run_git('config', 'user.email', 'test@example.com')

    # Create an initial commit
    test_file = repo_path / "test.txt"
    test_file.write_text("initial content")
    run_git('add', 'test.txt')
    run_git('commit', '-m', 'Initial commit')

    return repo_path

def test_create_worktree(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)

    worktree_path = manager.create_worktree("HEAD", "test-branch")

    assert worktree_path.exists()
    assert worktree_path.is_dir()

    # Verify it has the file from the initial commit
    assert (worktree_path / "test.txt").read_text() == "initial content"

    # Verify we are on the new branch
    result = subprocess.run(['git', 'branch', '--show-current'], cwd=worktree_path, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "test-branch"

def test_placement_is_outside_repo(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)

    worktree_path = manager.create_worktree("HEAD", "test-branch")

    resolved = worktree_path.resolve()
    repo_resolved = temp_git_repo.resolve()
    assert repo_resolved not in resolved.parents
    assert not (repo_resolved / '.daedalus_worktrees').exists()

    # The primary checkout's status must stay clean (no pollution)
    result = subprocess.run(['git', 'status', '--porcelain'], cwd=temp_git_repo, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == ""

def test_default_placement_is_the_os_profile_not_localappdata(
        temp_git_repo, tmp_path, monkeypatch):
    """The root follows the kill switch's control root: the OS-reported profile
    directory, which no environment variable can redirect. Setting
    ``LOCALAPPDATA`` -- the old base, Store-virtualised and 15 characters
    longer -- changes nothing (MEASURED 2026-08-23: the first armed loop run
    died in ``git worktree add`` with ``Filename too long`` under it)."""
    from daedalus.spine.killswitch import OS_PROFILE_DIR, control_root

    monkeypatch.delenv('DAEDALUS_WORKTREE_ROOT', raising=False)
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / "fake_localappdata"))

    manager = GitWorktreeManager(temp_git_repo)
    root = manager.worktree_root

    assert root.parent == OS_PROFILE_DIR / '.daedalus' / 'worktrees'
    assert str(tmp_path) not in str(root)
    # one parent with the control root, a sibling of it, never inside it
    assert root.parent.parent == control_root(temp_git_repo).parent.parent
    assert control_root(temp_git_repo) not in root.parents
    # Repo digest namespaces distinct checkouts
    other = GitWorktreeManager(tmp_path)
    assert other.worktree_root != root


def test_default_placement_creates_and_cleans_a_worktree(temp_git_repo, tmp_path,
                                                          monkeypatch):
    """The behavioural half of the placement test, kept under an override so
    the suite never litters the real profile directory."""
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(tmp_path / "wt"))
    manager = GitWorktreeManager(temp_git_repo)
    root = manager.worktree_root
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    assert worktree_path == root / "test-branch"
    assert worktree_path.exists()
    manager.cleanup_worktree(worktree_path)


def _half_done_worktree_add(manager, repo_path):
    """Make ``git worktree add -b`` fail the way it failed on 2026-08-23: the
    ref is written, the directory is half-populated, then git gives up
    (``Filename too long`` at 70% of the checkout)."""
    real_run_git = manager._run_git

    def run_git(*args, cwd=None):
        if args[:2] == ('worktree', 'add'):
            branch, path, base = args[3], Path(args[4]), args[5]
            real_run_git('branch', branch, base)             # ref first ...
            path.mkdir(parents=True, exist_ok=True)          # ... dir second
            (path / "half.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("git worktree add: Filename too long")
        return real_run_git(*args, cwd=cwd)

    manager._run_git = run_git


def test_a_failed_worktree_add_keeps_its_ref_until_reap(temp_git_repo,
                                                        worktree_root):
    """The 2026-08-23 leak, pinned the way Codex ruled it (room 56). A
    half-done ``git worktree add -b`` leaves a ref, a registration and a
    partial directory. Directory and registration are cleaned at once; the
    REF survives the exception -- it is the attempt's effect key and the
    intent that names it is resolved only after the caller sees the error --
    and falls to ``reap_branches`` afterwards under the usual two proofs."""
    manager = GitWorktreeManager(temp_git_repo)
    _half_done_worktree_add(manager, temp_git_repo)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=temp_git_repo,
                          capture_output=True, text=True, check=True).stdout.strip()

    with pytest.raises(RuntimeError, match="Filename too long"):
        manager.create_worktree("HEAD", "partial-branch")

    path = manager.worktree_root / "partial-branch"
    assert not path.exists(), "the half-filled directory must not survive"
    listed = subprocess.run(['git', 'worktree', 'list', '--porcelain'],
                            cwd=temp_git_repo, capture_output=True, text=True).stdout
    assert "partial-branch" not in listed, "the registration must be pruned"
    branches = subprocess.run(['git', 'branch', '--list', 'partial-branch'],
                              cwd=temp_git_repo, capture_output=True, text=True).stdout
    assert "partial-branch" in branches, "the ref is kept until the ledger is terminal"

    report = manager.reap_branches()
    mine = [r for r in report if r["branch"] == "partial-branch"]
    assert mine and mine[0]["action"] == "deleted", report
    branches = subprocess.run(['git', 'branch', '--list', 'partial-branch'],
                              cwd=temp_git_repo, capture_output=True, text=True).stdout
    assert "partial-branch" not in branches
    assert subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=temp_git_repo,
                          capture_output=True, text=True).stdout.strip() == head


def test_a_failed_worktree_add_that_never_wrote_the_ref_reaps_nothing(
        temp_git_repo, worktree_root):
    """git can also fail BEFORE the ref exists (bad base, refused path). Then
    there is nothing to reap and the report must say ``absent``, never
    ``deleted``."""
    manager = GitWorktreeManager(temp_git_repo)
    with pytest.raises(RuntimeError):
        manager.create_worktree("not-a-revision", "never-born")
    report = manager.reap_branches()
    mine = [r for r in report if r["branch"] == "never-born"]
    assert mine and mine[0]["action"] == "absent", report


def test_git_is_told_long_paths_on_windows(temp_git_repo, worktree_root,
                                           monkeypatch):
    """``-c core.longpaths=true`` rides on every git call on Windows and on
    none elsewhere; it is a per-command flag, so no config file changes."""
    seen = []
    real_run = worktree_module.subprocess.run

    def spy(cmd, **kwargs):
        seen.append(list(cmd))
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(worktree_module.subprocess, "run", spy)
    manager = GitWorktreeManager(temp_git_repo)
    manager._run_git("rev-parse", "HEAD")
    assert seen, "no git call was made"
    cmd = seen[-1]
    assert cmd[0] == "git"
    if os.name == "nt":
        assert cmd[1:3] == ["-c", "core.longpaths=true"]
        assert cmd[3:] == ["rev-parse", "HEAD"]
    else:
        assert cmd[1:] == ["rev-parse", "HEAD"]
    assert subprocess.run(["git", "config", "--get", "core.longpaths"],
                          cwd=temp_git_repo, capture_output=True,
                          text=True).stdout.strip() == ""

def test_env_override_controls_placement(temp_git_repo, tmp_path, monkeypatch):
    override_root = tmp_path / "custom_root"
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(override_root))

    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    assert override_root in worktree_path.parents
    assert worktree_path.exists()

def test_storage_check_consulted_and_fail_closed(temp_git_repo, worktree_root, monkeypatch):
    manager = GitWorktreeManager(temp_git_repo)

    consulted = []
    def failing_require_storage(path, min_free_gib=None):
        consulted.append(path)
        raise StorageUnavailable("storage_unavailable: test")
    monkeypatch.setattr(worktree_module, 'require_storage', failing_require_storage)

    with pytest.raises(StorageUnavailable):
        manager.create_worktree("HEAD", "test-branch")

    assert consulted == [str(manager.worktree_root)]
    # Fail-closed: no worktree was created anywhere
    assert not (manager.worktree_root / "test-branch").exists()
    result = subprocess.run(['git', 'worktree', 'list'], cwd=temp_git_repo, capture_output=True, text=True, check=True)
    assert "test-branch" not in result.stdout

def test_cleanup_worktree(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    manager.cleanup_worktree(worktree_path)

    assert not worktree_path.exists()

    # Verify the worktree is removed from git's list
    result = subprocess.run(['git', 'worktree', 'list'], cwd=temp_git_repo, capture_output=True, text=True, check=True)
    assert str(worktree_path) not in result.stdout

def test_cleanup_failure_surfaces(temp_git_repo, worktree_root, monkeypatch):
    """A removal that fails is reported, never swallowed into a silent skip."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    def failing_remove(path, guarded_ancestors=()):
        raise OSError("permission denied")
    monkeypatch.setattr(worktree_module, '_remove_tree_no_follow', failing_remove)

    with pytest.raises(RuntimeError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    message = str(excinfo.value)
    assert "failed to remove worktree directory" in message
    assert str(worktree_path) in message
    assert not isinstance(excinfo.value, WorktreeContainmentError)


def test_deregistration_failure_surfaces(temp_git_repo, worktree_root, monkeypatch):
    """The directory is gone but git could not be told: still loud."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    def failing_run_git(*args, cwd=None):
        raise RuntimeError("git worktree prune exploded")
    monkeypatch.setattr(manager, '_run_git', failing_run_git)

    with pytest.raises(RuntimeError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "git worktree prune exploded" in str(excinfo.value)
    assert not worktree_path.exists()

def test_commit_candidate(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    # Make a change in the worktree
    (worktree_path / "new_file.txt").write_text("new stuff")

    manager.commit_candidate(worktree_path, "Add new file", author="Agent <agent@daedalus.ai>")

    # Verify the commit exists and has the right message and author
    result = subprocess.run(
        ['git', 'log', '-1', '--format=%s|%an|%ae'],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=True
    )

    stdout = result.stdout.strip()
    assert stdout == "Add new file|Agent|agent@daedalus.ai"


def test_has_changes_tracks_candidate_worktree_only(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    assert manager.has_changes(worktree_path) is False
    (worktree_path / "new_file.txt").write_text("candidate")
    assert manager.has_changes(worktree_path) is True


# --------------------------------------------------------------------------- #
# containment: cleanup_worktree must never be steerable onto another directory #
#                                                                              #
# The threat model is concrete: candidate code runs INSIDE the worktree, knows  #
# its own path, and cleanup runs unattended in a ``finally:`` block. Every test #
# below builds the real artefact (a real junction, a real symlink, a real       #
# rename) and asserts a SENTINEL in the decoy "primary repository" survives --  #
# asserting that a helper returns False would prove nothing.                    #
# --------------------------------------------------------------------------- #
def _init_git_repo(path: Path) -> Path:
    """A second, independent git repo to stand in for the user's checkout."""
    path.mkdir(parents=True, exist_ok=True)

    def run_git(*args):
        subprocess.run(['git', *args], cwd=path, check=True, capture_output=True)

    run_git('init')
    run_git('config', 'user.name', 'Primary User')
    run_git('config', 'user.email', 'primary@example.com')
    (path / "SENTINEL.txt").write_text("the user's primary repository")
    (path / "src").mkdir()
    (path / "src" / "deep.txt").write_text("years of work")
    run_git('add', '-A')
    run_git('commit', '-m', 'primary work')
    return path


def _make_junction(link: Path, target: Path) -> bool:
    """Create a Windows directory junction (``mklink /J``) -- no admin needed.

    This is the attacker's tool of choice precisely because ``os.path.islink``
    does not see it.
    """
    result = subprocess.run(
        ['cmd', '/c', 'mklink', '/J', str(link), str(target)],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.exists(link)


def _assert_decoy_intact(decoy: Path) -> None:
    assert (decoy / "SENTINEL.txt").exists(), "the primary repository was DELETED"
    assert (decoy / "src" / "deep.txt").exists()
    assert (decoy / ".git").exists()


class _PosixShapedStat:
    """A stat result with the Windows-only fields GENUINELY ABSENT.

    Exactly the shape CPython produces on Linux/macOS, where
    ``st_file_attributes`` and ``st_reparse_tag`` do not exist as members at
    all, so ``getattr(st, ..., 0)`` in ``_is_reparse_point`` yields 0 for both
    and the ``S_ISLNK``/``islink`` branch is the WHOLE of reparse detection.

    Deliberately NOT ``os.stat_result((mode, 0, ...))``: on a Windows CPython
    that keeps the ``st_file_attributes`` SLOT and fills it with ``None``,
    which is a Windows artefact and not the platform condition under test
    (measured: ``getattr`` returns None, not 0). Simulating the wrong shape
    would test a configuration no platform ever produces.
    """

    __slots__ = ('st_mode',)

    def __init__(self, mode: int):
        self.st_mode = mode


def test_reparse_detection_off_windows_rests_on_the_symlink_branch(monkeypatch,
                                                                   tmp_path):
    """The most load-bearing untested line in the module, given a dying test.

    ``_is_reparse_point`` is the primitive the entire no-follow walk is built
    on. On Windows it has three independent ways to say yes (``S_ISLNK`` /
    ``islink``, ``FILE_ATTRIBUTE_REPARSE_POINT``, a non-zero reparse tag), and
    the junction tests in this file exercise the last two. On EVERY OTHER
    PLATFORM the last two do not exist, so deleting the first line turns this
    function into ``return False`` for everything -- every symlink followed,
    every guard in the file silently open -- and no test noticed.

    The platform is simulated rather than skipped, because a test that only
    runs on a machine nobody runs the suite on is not a test. What is simulated
    is exactly one thing: the SHAPE of the stat result, which is a property of
    the platform, not of this module. The function under test is the shipped
    one, unmodified, and it is the shipped function that every guard calls.
    """
    link = tmp_path / "a_symlink"
    plain = tmp_path / "a_directory"
    plain.mkdir()
    shapes = {
        str(link): _PosixShapedStat(stat.S_IFLNK | 0o777),
        str(plain): _PosixShapedStat(stat.S_IFDIR | 0o755),
    }
    real_lstat = os.lstat

    def posix_shaped_lstat(path, *args, **kwargs):
        return shapes.get(str(path)) or real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(worktree_module.os, 'lstat', posix_shaped_lstat)

    # The precondition that makes this line load-bearing: with no Windows
    # fields, the other two ways to say yes are both blind.
    st = worktree_module.os.lstat(link)
    assert getattr(st, 'st_file_attributes', 0) == 0
    assert getattr(st, 'st_reparse_tag', 0) == 0
    assert stat.S_ISLNK(st.st_mode)

    assert worktree_module._is_reparse_point(link) is True, (
        "off Windows this is the only reparse detection there is")
    # ...and it is a real classification, not a constant: a plain directory of
    # the same shape must still be safe to walk into.
    assert worktree_module._is_reparse_point(plain) is False


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_junction_swap_cannot_delete_the_primary_repo(temp_git_repo, worktree_root, tmp_path):
    """THE exploit: swap the worktree for a junction aimed at the real checkout.

    ``git worktree remove`` fails (git refuses to remove a main working tree),
    and that failure must not become permission to ``rmtree`` whatever the
    junction resolved to.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    decoy = _init_git_repo(tmp_path / "primary_checkout")

    # Candidate code replaces its own worktree directory with a junction.
    shutil.rmtree(worktree_path)
    assert _make_junction(worktree_path, decoy), "could not stage the attack"
    assert not os.path.islink(worktree_path), (
        "precondition: os.path.islink must NOT see a junction, which is why a "
        "reparse-point check is required"
    )

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    _assert_decoy_intact(decoy)
    assert "refusing to operate" in str(excinfo.value)


def test_symlink_swap_cannot_delete_the_primary_repo(temp_git_repo, worktree_root, tmp_path):
    """Same attack via a POSIX-style symlink (Windows: needs the privilege)."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    decoy = _init_git_repo(tmp_path / "primary_checkout")

    shutil.rmtree(worktree_path)
    try:
        os.symlink(str(decoy), str(worktree_path), target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlink creation not permitted here: {e}")

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    _assert_decoy_intact(decoy)
    assert "refusing to operate" in str(excinfo.value)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_junction_at_the_worktree_root_is_refused(temp_git_repo, worktree_root, tmp_path):
    """The reparse check covers the ROOT too, not just the leaf.

    Otherwise a junction one level up redirects every allocated path at once.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    real_root = manager.worktree_root

    # Move the whole root -- allocation records included -- somewhere else, and
    # junction the root's NAME at it. Every other check still passes (the leaf
    # is a real directory, the record is present, the path is lexically under
    # the root), so the reparse check on the ROOT is the only thing standing
    # between cleanup and a directory that is no longer where we put it.
    staging = tmp_path / "staging"
    shutil.move(str(real_root), str(staging))
    (staging / "test-branch" / "SENTINEL.txt").write_text("not ours to delete")
    assert _make_junction(real_root, staging), "could not stage the attack"

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert (staging / "test-branch" / "SENTINEL.txt").exists()
    assert "reparse point" in str(excinfo.value)


def test_cleanup_refuses_a_path_outside_the_worktree_root(temp_git_repo, worktree_root, tmp_path):
    manager = GitWorktreeManager(temp_git_repo)
    manager.create_worktree("HEAD", "test-branch")
    outsider = tmp_path / "not_ours"
    outsider.mkdir()
    (outsider / "keep.txt").write_text("keep")

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(outsider)

    assert (outsider / "keep.txt").exists()
    assert "worktree root" in str(excinfo.value)


def test_cleanup_refuses_the_repo_root(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(temp_git_repo)

    assert (temp_git_repo / "test.txt").exists()
    assert (temp_git_repo / ".git").exists()
    assert "refusing to operate" in str(excinfo.value)


def test_cleanup_refuses_the_repo_parent(temp_git_repo, worktree_root, tmp_path):
    """An ancestor of the checkout is worse than the checkout itself."""
    manager = GitWorktreeManager(temp_git_repo)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(tmp_path)

    assert (temp_git_repo / "test.txt").exists()
    assert "refusing to operate" in str(excinfo.value)


def test_cleanup_refuses_a_renamed_worktree(temp_git_repo, worktree_root):
    """Moved out from under the manager: refuse, loudly, from either name."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    moved = manager.worktree_root / "moved-aside"
    worktree_path.rename(moved)

    # The allocated name no longer exists -- a silent skip would leak the tree.
    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)
    assert "no longer exists" in str(excinfo.value)

    # The new name was never allocated, so it is not ours to delete either.
    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(moved)
    assert "allocation record" in str(excinfo.value)
    assert (moved / "test.txt").exists()


def test_cleanup_refuses_a_directory_the_manager_never_allocated(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    manager.create_worktree("HEAD", "test-branch")
    squatter = manager.worktree_root / "not-allocated"
    squatter.mkdir()
    (squatter / "keep.txt").write_text("keep")

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(squatter)

    assert (squatter / "keep.txt").exists()
    assert "allocation record" in str(excinfo.value)


def test_cleanup_refuses_the_worktree_root_itself(temp_git_repo, worktree_root):
    """The container of every candidate is not itself a candidate."""
    manager = GitWorktreeManager(temp_git_repo)
    manager.create_worktree("HEAD", "test-branch")

    for target in (manager.worktree_root, worktree_root):
        with pytest.raises(WorktreeContainmentError) as excinfo:
            manager.cleanup_worktree(target)
        assert "worktree root" in str(excinfo.value)

    assert manager.worktree_root.exists()
    assert (manager.worktree_root / "test-branch").exists()


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_removal_does_not_descend_into_a_nested_junction(temp_git_repo, worktree_root, tmp_path):
    """Variant: the junction is planted INSIDE an otherwise legitimate worktree.

    Cleanup is allowed to proceed here -- the worktree really is ours -- but the
    recursive delete must unlink the junction, not follow it.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    assert _make_junction(worktree_path / "trap", decoy), "could not stage the attack"

    # git refuses a worktree with a reparse point in it on some versions; either
    # way the sentinel is the assertion that matters.
    try:
        manager.cleanup_worktree(worktree_path)
    except RuntimeError:
        pass

    _assert_decoy_intact(decoy)


# --------------------------------------------------------------------------- #
# the STALE-CLASSIFICATION defect: a check that happened earlier is not a check #
# that holds now. The test above plants its junction BEFORE cleanup starts, so  #
# it structurally cannot catch this -- the walk never classified the directory  #
# as safe, it saw the junction on first contact. The tests below plant the      #
# junction with a live process, AFTER the walk has already classified and       #
# queued the directory, which is the only version a real candidate can mount.   #
# --------------------------------------------------------------------------- #
_RACE_DIRS = 40
_RACE_FILES = 40


def _build_race_tree(tmp_path: Path):
    """A tree big enough that the walk takes ~a second, plus a swap target.

    ``d000`` is emptied so the attacker can ``rmdir`` it in one syscall, and a
    junction is PRE-BUILT outside the tree so the swap is a single ``rename``.
    That is the fastest swap candidate code can perform, and therefore the
    right adversary to measure against.
    """
    tree = tmp_path / "tree"
    tree.mkdir()
    names = [f"d{i:03d}" for i in range(_RACE_DIRS)]
    for name in names:
        (tree / name).mkdir()
        for j in range(_RACE_FILES):
            (tree / name / f"f{j:03d}.txt").write_text("payload")
    for j in range(_RACE_FILES):        # the swap target must be cheap to rmdir
        (tree / names[0] / f"f{j:03d}.txt").unlink()
    return tree, names[0], tree / names[-1] / "f000.txt"


def _swapper(tree: Path, target: str, canary: Path, prepared: Path, done: dict):
    """Live candidate: wait for the walk to be underway, then swap ``target``.

    The canary is a file in the LAST directory of the parent, which a LIFO walk
    visits FIRST -- so its disappearance proves the walk has already enumerated
    the parent and classified ``target`` as an ordinary directory.
    """
    deadline = time.monotonic() + 30.0
    while canary.exists() and time.monotonic() < deadline:
        time.sleep(0.0005)
    try:
        os.rmdir(tree / target)
        os.rename(prepared, tree / target)
        done["swapped"] = True
    except OSError as e:
        done["error"] = str(e)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_removal_does_not_follow_a_junction_swapped_in_mid_walk(tmp_path):
    """CRITICAL: the classification that queued a directory goes stale.

    Measured against the unfixed walker this destroyed the victim 3/3; against
    ``shutil.rmtree`` (whose junction check reads the Windows scandir stat
    cache) the same attack aimed at the LAST entry destroys it 3/3 too. The
    fix is re-classifying every directory with a fresh ``lstat`` when it is
    POPPED, not when it was queued.
    """
    tree, target, canary = _build_race_tree(tmp_path)
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    attacker = threading.Thread(
        target=_swapper, args=(tree, target, canary, prepared, done), daemon=True)
    attacker.start()
    try:
        worktree_module._remove_tree_no_follow(tree)
    finally:
        attacker.join(timeout=30)

    # If the swap never landed the test proved nothing, so say so out loud
    # rather than reporting a green that was never earned.
    assert done.get("swapped"), f"the attack never landed: {done}"
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_removal_refuses_when_a_guarded_ancestor_becomes_a_reparse_point(tmp_path):
    """A reparse point ABOVE the walk redirects every path it is still holding.

    Staged directly rather than raced, because the attacker's move here is to
    ``rename`` the whole worktree root aside and junction its NAME -- a rename
    does not need the directory to be empty, so it can be done mid-walk. The
    walk cannot repair this by unlinking (the link is not its to delete), so it
    refuses and reports a PARTIAL removal instead of finishing through it.
    """
    tree = tmp_path / "holder" / "tree"
    tree.mkdir(parents=True)
    (tree / "keep.txt").write_text("still here")
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    link = tmp_path / "link"
    assert _make_junction(link, decoy), "could not stage the attack"

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        worktree_module._remove_tree_no_follow(tree, guarded_ancestors=[link])

    assert "reparse point" in str(excinfo.value)
    assert (tree / "keep.txt").exists(), "it refused, so it must not have deleted"
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_removal_unlinks_a_reparse_point_root_instead_of_following_it(tmp_path):
    """The removal root itself is a junction: unlink the LINK, keep the target.

    Called directly, because ``cleanup_worktree`` refuses this case long before
    the walker sees it. The walker still has to be right on its own, since it
    is the thing holding the delete.
    """
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    link = tmp_path / "link"
    assert _make_junction(link, decoy), "could not stage the attack"

    worktree_module._remove_tree_no_follow(link)

    assert not os.path.lexists(link), "the link itself should be gone"
    _assert_decoy_intact(decoy)


def test_removal_of_a_plain_file_removes_the_file(tmp_path):
    """A non-directory target must be unlinked, never handed to ``scandir``."""
    victim = tmp_path / "a_file.txt"
    victim.write_text("payload")

    worktree_module._remove_tree_no_follow(victim)

    assert not victim.exists()


def test_removal_unlinks_a_nested_directory_symlink(tmp_path):
    """A directory symlink is not reported as a directory, so it takes the
    other branch out of the scan loop -- and must still not be followed."""
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "f.txt").write_text("payload")
    try:
        os.symlink(str(decoy), str(tree / "trap"), target_is_directory=True)
    except (OSError, NotImplementedError) as e:
        pytest.skip(f"symlink creation not permitted here: {e}")

    worktree_module._remove_tree_no_follow(tree)

    assert not tree.exists()
    _assert_decoy_intact(decoy)


# --------------------------------------------------------------------------- #
# THE SAME DEFECT, TWICE MORE, IN THE SAME FUNCTION. The pop-time re-check      #
# above covers os.scandir. It does NOT cover the other two destructive loops,   #
# and both of those were shipped green:                                         #
#                                                                               #
#   * the per-child unlink loop ran N unlinks after ONE verification of the     #
#     parent -- and os.unlink deletes FILE CONTENT, not just empty directories; #
#   * the rmdir drain ran M rmdirs after NONE, which was measured end to end    #
#     through cleanup_worktree: 3000 directories removed inside a stand-in      #
#     primary checkout, 3/3, reported as success.                               #
#                                                                               #
# Both tests below stage the swap from a HOOK on the walker's own primitive     #
# rather than from a thread: no sleep, no canary, no "the attack never landed"  #
# flake. The hook is the attacker's rename, fired at the exact instant the      #
# defect needs it -- which is the strongest form of the attack, not a weaker    #
# one, since a real candidate gets to try continuously.                         #
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_the_pop_refuses_when_an_ancestor_was_swapped_after_the_child_was_queued(
        tmp_path, monkeypatch):
    """``_verify_reachable(current)`` at the pop, isolated so it can die.

    ``test_removal_does_not_follow_a_junction_swapped_in_mid_walk`` above does
    NOT cover this: it swaps the popped path ITSELF, which the pop-time
    ``_is_reparse_point`` catches. Deleting the pop-time ``_verify_reachable``
    left that test green (mutation-measured), so the case it really guards --
    a swap strictly ABOVE a path that is already queued -- is staged here.

    The teeth are the ``not S_ISDIR`` branch a few lines below the check: a path
    queued as a directory that reads back as a FILE is unlinked on the spot,
    with nothing else standing in front of it. So the decoy holds a FILE where
    the queued directory's name lands, and an unverified pop deletes it.
    """
    tree = tmp_path / "tree"
    mid = tree / "mid"
    leaf = mid / "staging"
    leaf.mkdir(parents=True)
    (leaf / "candidate.txt").write_text("candidate payload")
    # A sibling that sorts AFTER the directory, so it is the last thing handled
    # in `mid`'s entry loop -- the swap fires from its unlink, which is after
    # `staging` was queued and before anything pops it. Triggering on
    # `staging`'s own classification instead would couple this test to the
    # branch that does the classifying, and a test that dies because its
    # TRIGGER was removed proves nothing about the guard.
    (mid / "zz_last.txt").write_text("candidate payload")

    decoy = _init_git_repo(tmp_path / "primary_checkout")
    (decoy / "staging").write_text("years of work")   # a FILE where `leaf` lands
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    real_unlink = worktree_module._force_unlink

    def swapping_unlink(path):
        result = real_unlink(path)
        if not done:
            os.rename(mid, tmp_path / "aside")
            os.rename(prepared, mid)
            done["swapped"] = True
        return result

    monkeypatch.setattr(worktree_module, '_force_unlink', swapping_unlink)

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        worktree_module._remove_tree_no_follow(tree)

    assert done.get("swapped"), f"the attack never landed: {done}"
    assert "reparse point" in str(excinfo.value)
    assert (decoy / "staging").read_text() == "years of work", (
        "a queued path was acted on through a swapped ancestor")
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_the_rmdir_drain_refuses_a_junction_swapped_over_a_drained_subtree(
        tmp_path, monkeypatch):
    """CRITICAL: every path in the drain was classified when it was POPPED.

    For the first directory drained that is the entire walk ago. ``os.rmdir``
    resolves its path argument through a reparse point in an intermediate
    component exactly as ``os.scandir`` does, so a junction renamed over an
    already-drained sibling redirects every remaining rmdir out of the tree.

    Two subtrees are used and the swap picks whichever one is NOT an ancestor
    of the first directory drained, so the attack lands whatever order
    ``scandir`` returned -- a LIFO walk drains one subtree completely before it
    starts the other, so the untouched one always still has directories queued.
    """
    tree = tmp_path / "tree"
    subs = [tree / "s1", tree / "s2"]
    for sub in subs:
        sub.mkdir(parents=True)
        for i in range(3):
            (sub / f"c{i:03d}").mkdir()

    decoy = _init_git_repo(tmp_path / "primary_checkout")
    for i in range(3):                  # what the redirected rmdirs reach for
        (decoy / f"c{i:03d}").mkdir()
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    real_rmdir = worktree_module._force_rmdir

    def swapping_rmdir(path):
        if not done:
            victim_sub = next(
                s for s in subs
                if not worktree_module._is_within(Path(path), s))
            os.rename(victim_sub, tmp_path / "aside")
            os.rename(prepared, victim_sub)
            done["swapped"] = str(victim_sub)
        return real_rmdir(path)

    monkeypatch.setattr(worktree_module, '_force_rmdir', swapping_rmdir)

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        worktree_module._remove_tree_no_follow(tree)

    assert done.get("swapped"), f"the attack never landed: {done}"
    assert "reparse point" in str(excinfo.value)
    assert "PARTIALLY REMOVED" in str(excinfo.value), (
        "a partial delete must be reported as one, not returned as success")
    for i in range(3):
        assert (decoy / f"c{i:03d}").is_dir(), (
            "an rmdir was redirected out of the tree")
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_the_drain_refuses_a_directory_that_became_a_junction_after_it_emptied(
        tmp_path, monkeypatch):
    """The other half of the drain check, isolated so it can die on its own.

    ``_verify_reachable`` only looks ABOVE a path, so it cannot see the drained
    directory itself being swapped. ``os.rmdir`` does not follow a reparse point
    that is the FINAL component -- it removes the link -- so this is not a
    delete of the target; it is the walk silently consuming a link it does not
    own and reporting the tree as fully removed when what it emptied is no
    longer what it deleted. Refusing is the fail-closed answer: a swapped
    directory means everything the walk is still holding is suspect.

    The swap is fired from the rmdir of the LAST child, which is the only
    instant at which the parent is both empty (so the attacker can rmdir it)
    and not yet drained.
    """
    tree = tmp_path / "tree"
    sub = tree / "sub"
    sub.mkdir(parents=True)
    children = 3
    for i in range(children):
        (sub / f"c{i:03d}").mkdir()

    decoy = _init_git_repo(tmp_path / "primary_checkout")
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    real_rmdir = worktree_module._force_rmdir

    def swapping_rmdir(path):
        result = real_rmdir(path)
        done["calls"] = done.get("calls", 0) + 1
        if done["calls"] == children:   # `sub` is empty now, and still queued
            os.rmdir(sub)
            os.rename(prepared, sub)
            done["swapped"] = True
        return result

    monkeypatch.setattr(worktree_module, '_force_rmdir', swapping_rmdir)

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        worktree_module._remove_tree_no_follow(tree)

    assert done.get("swapped"), f"the attack never landed: {done}"
    assert "no longer the directory this walk emptied" in str(excinfo.value)
    assert os.path.lexists(sub), (
        "the walk consumed a reparse point it did not create instead of "
        "refusing to touch it")
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_the_child_unlinks_refuse_a_junction_swapped_over_their_parent(
        tmp_path, monkeypatch):
    """Worse than the drain: this one deletes FILE CONTENT outside the tree.

    The directory being emptied is verified once, when it is popped, and then N
    files are unlinked through it. A ``rename`` does not require a directory to
    be empty, so a live candidate can swap that parent for a junction between
    any two of those unlinks and every remaining one lands in the target.
    """
    tree = tmp_path / "tree"
    files_dir = tree / "files"
    files_dir.mkdir(parents=True)
    for j in range(6):
        (files_dir / f"f{j:03d}.txt").write_text("candidate payload")

    decoy = _init_git_repo(tmp_path / "primary_checkout")
    for j in range(6):                  # what the redirected unlinks reach for
        (decoy / f"f{j:03d}.txt").write_text("years of work")
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    real_unlink = worktree_module._force_unlink

    def swapping_unlink(path):
        result = real_unlink(path)      # the first unlink is legitimate
        if not done:
            os.rename(files_dir, tmp_path / "aside")
            os.rename(prepared, files_dir)
            done["swapped"] = True
        return result

    monkeypatch.setattr(worktree_module, '_force_unlink', swapping_unlink)

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        worktree_module._remove_tree_no_follow(tree)

    assert done.get("swapped"), f"the attack never landed: {done}"
    assert "reparse point" in str(excinfo.value)
    for j in range(6):
        victim_file = decoy / f"f{j:03d}.txt"
        assert victim_file.exists() and victim_file.read_text() == "years of work", (
            f"an unlink was redirected out of the tree: {victim_file} is gone")
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_hands_the_walker_the_ancestors_ABOVE_the_worktree(
        temp_git_repo, worktree_root, tmp_path, monkeypatch):
    """The WIRING of ``guarded_ancestors``, which had no test at all.

    ``test_removal_refuses_when_a_guarded_ancestor_becomes_a_reparse_point``
    passes the argument itself, so deleting ``guarded_ancestors=guarded`` from
    ``cleanup_worktree`` left the entire suite green. This one goes through the
    public API and stages the one attack the argument exists for: the worktree
    ROOT is ABOVE the walk's own root, so no chain the walker computes for
    itself contains it, and only what ``cleanup_worktree`` hands over can make
    it visible. The root is renamed aside and a junction renamed into its place
    while the removal is underway -- available to a candidate at any moment,
    because renaming a directory does not require it to be empty.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    (worktree_path / "candidate.txt").write_text("candidate output")
    real_root = manager.worktree_root

    decoy = _init_git_repo(tmp_path / "primary_checkout")
    # Mirror the shape the redirected paths reach for, so an unguarded walk
    # destroys something real instead of failing on a missing name.
    mirror = decoy / "test-branch"
    mirror.mkdir()
    (mirror / "candidate.txt").write_text("years of work")
    (mirror / "test.txt").write_text("years of work")
    prepared = tmp_path / "prepared_junction"
    assert _make_junction(prepared, decoy), "could not stage the attack"

    done: dict = {}
    real_unlink = worktree_module._force_unlink

    def swapping_unlink(path):
        result = real_unlink(path)      # the first unlink is legitimate
        if not done:
            os.rename(real_root, tmp_path / "aside")
            os.rename(prepared, real_root)
            done["swapped"] = True
        return result

    monkeypatch.setattr(worktree_module, '_force_unlink', swapping_unlink)

    with pytest.raises(WorktreeRemovalRace) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert done.get("swapped"), f"the attack never landed: {done}"
    assert "reparse point" in str(excinfo.value)
    for name in ("candidate.txt", "test.txt"):
        assert (mirror / name).read_text() == "years of work", (
            f"the walk was redirected through the worktree root: {name} is gone")
    _assert_decoy_intact(decoy)


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_still_refuses_a_junction_swap_if_reparse_detection_goes_blind(
        temp_git_repo, worktree_root, tmp_path, monkeypatch):
    """Defence in depth, tested by removing the layer in front of it.

    Step 3 normally catches this swap, which is why the resolved-path check
    behind it never fires in the suite. A layer nobody has ever seen work is a
    layer nobody knows works -- so reparse detection is blinded here (a new
    reparse tag, a new Python, a network filesystem) and the check behind it
    has to hold on its own.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    decoy = _init_git_repo(tmp_path / "primary_checkout")
    shutil.rmtree(worktree_path)
    assert _make_junction(worktree_path, decoy), "could not stage the attack"
    monkeypatch.setattr(worktree_module, '_is_reparse_point', lambda p: False)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    _assert_decoy_intact(decoy)
    assert "outside the worktree root" in str(excinfo.value)


def test_cleanup_refuses_a_target_that_is_not_a_directory(temp_git_repo, worktree_root):
    """A file wearing an allocated worktree's name is not that worktree."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    manager.cleanup_worktree(worktree_path)
    worktree_path.write_text("a file wearing the worktree's name")

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "not a directory" in str(excinfo.value)
    assert worktree_path.read_text() == "a file wearing the worktree's name"


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_commit_candidate_refuses_a_worktree_reached_through_a_junction(
        temp_git_repo, worktree_root, tmp_path):
    """``commit_candidate`` never reaches the removal walker.

    So the chain check in ``_require_allocated_worktree`` is the only reparse
    check between ``git add -A && git commit`` and a tree that is no longer
    where the manager put it. The resolved-path checks do not catch this one:
    the target still resolves INSIDE the resolved worktree root, because the
    junction moved the root itself.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    real_root = manager.worktree_root
    staging = tmp_path / "staging"
    shutil.move(str(real_root), str(staging))
    (staging / "test-branch" / "NOT_OURS.txt").write_text("someone else's file")
    assert _make_junction(real_root, staging), "could not stage the attack"

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.commit_candidate(worktree_path, "should never have happened")

    assert "reparse point" in str(excinfo.value)
    log = subprocess.run(['git', 'log', '--oneline'], cwd=staging / "test-branch",
                         capture_output=True, text=True)
    assert "should never have happened" not in log.stdout
    assert (staging / "test-branch" / "NOT_OURS.txt").exists()


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_refuses_a_worktree_that_only_RESOLVES_into_the_checkout(
        temp_git_repo, tmp_path, monkeypatch):
    """Every LEXICAL check passes; only repo-adjacency on the RESOLVED path fires.

    The worktree root is placed under a junction that lands inside the
    developer's checkout. The target is textually under the configured root, it
    does not textually overlap the repo, and no component FROM THE ROOT DOWN is
    a reparse point -- the junction is above the root, where step 3 does not
    look. This is the test that makes ``_refuse_if_repo_adjacent`` load-bearing:
    without it the resolved target is still inside the resolved root, so every
    other check says yes and cleanup deletes inside the checkout.
    """
    link = tmp_path / "link"
    assert _make_junction(link, temp_git_repo), "could not stage the attack"
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(link / "wt_root"))

    manager = GitWorktreeManager(temp_git_repo)
    target = manager.worktree_root / "test-branch"
    target.mkdir(parents=True)
    (target / "PRECIOUS.txt").write_text("a real file inside the checkout")
    manager._record_allocation(target, "test-branch")
    # where those bytes REALLY live -- inside the developer's checkout
    real = Path(os.path.realpath(target))
    assert temp_git_repo.resolve() in real.parents, "the attack was not staged"

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(target)

    assert "primary checkout" in str(excinfo.value)
    assert (real / "PRECIOUS.txt").exists(), "cleanup deleted inside the checkout"


def test_create_worktree_refuses_a_branch_name_that_escapes_the_root(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.create_worktree("HEAD", "../escapee")

    assert "escapes the worktree root" in str(excinfo.value)
    assert not (worktree_root.parent / "escapee").exists()


def test_create_worktree_refuses_an_allocation_path_inside_the_checkout(
        temp_git_repo, tmp_path, monkeypatch):
    """DAEDALUS_WORKTREE_ROOT aimed straight into the developer's checkout.

    That env var is the only thing that decides where candidate worktrees land,
    and it is read from the ambient environment -- so this guard is what stands
    between a stray ``set DAEDALUS_WORKTREE_ROOT=.`` and candidate code (plus,
    later, a recursive delete) running inside the repo being worked on.

    Refused at CREATION, before anything exists: cleanup's own containment
    checks are no help here, because by the time they run the candidate's files
    are already in the developer's ``git status``.
    """
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(temp_git_repo / ".daedalus"))
    manager = GitWorktreeManager(temp_git_repo)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.create_worktree("HEAD", "test-branch")

    assert "the allocation path is the primary checkout" in str(excinfo.value)
    assert not (temp_git_repo / ".daedalus").exists(), "nothing may be created"
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=temp_git_repo,
                            capture_output=True, text=True, check=True)
    assert status.stdout == "", "the checkout was dirtied by a refused allocation"


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_create_worktree_refuses_a_root_that_only_RESOLVES_into_the_checkout(
        temp_git_repo, tmp_path, monkeypatch):
    """Every LEXICAL check passes; only the resolved root fires.

    ``_worktree_root_for`` is pure text -- an env var plus a digest -- so one
    junction anywhere in ``DAEDALUS_WORKTREE_ROOT`` puts the whole worktree root
    inside the checkout while the path spelling stays innocent. ``cleanup``
    catches this (there is a test for that), but only when it is time to delete;
    by then the candidate has already been created inside the repo.
    """
    link = tmp_path / "link"
    assert _make_junction(link, temp_git_repo), "could not stage the attack"
    monkeypatch.setenv('DAEDALUS_WORKTREE_ROOT', str(link / "wt_root"))

    manager = GitWorktreeManager(temp_git_repo)
    # precondition: nothing lexical can see this -- the spelling is outside the
    # repo and it is the junction ABOVE the root that lands it inside.
    assert not str(manager.worktree_root).startswith(str(temp_git_repo))

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.create_worktree("HEAD", "test-branch")

    assert "resolved worktree root" in str(excinfo.value)
    assert not (temp_git_repo / "wt_root").exists(), (
        "a candidate worktree was created inside the developer's checkout")
    status = subprocess.run(['git', 'status', '--porcelain'], cwd=temp_git_repo,
                            capture_output=True, text=True, check=True)
    assert status.stdout == "", "the checkout was dirtied by a refused allocation"


def test_cleanup_refuses_when_the_primary_checkout_was_moved_into_the_worktree(
        temp_git_repo, worktree_root):
    """The move-in attack: no reparse point, so no reparse check can ever fire.

    The candidate renames the whole checkout into its own worktree. Every
    containment check then passes HONESTLY -- what the walker finds is a real
    directory in a place it really is entitled to delete -- and the checkout is
    destroyed with cleanup returning success. Measured 3/3 before this guard.

    This is a mitigation and is documented as one: the manager knows the
    identity of exactly one directory, so a candidate that moves anything else
    in is still unstopped. What it converts is the worst case -- silent total
    loss reported as success -- into a loud refusal with the checkout alive.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    (temp_git_repo / "SENTINEL.txt").write_text("the primary repository")

    moved_in = worktree_path / "moved_in"
    os.rename(temp_git_repo, moved_in)

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "no longer at its own path" in str(excinfo.value)
    assert (moved_in / "SENTINEL.txt").exists(), "the checkout was DELETED"
    assert (moved_in / ".git").exists()
    assert (moved_in / "test.txt").read_text() == "initial content"


def test_cleanup_refuses_a_decoy_wearing_the_primary_checkouts_name(
        temp_git_repo, worktree_root, tmp_path):
    """Same guard, other half: the path is back but it is a different directory.

    Restoring *a* directory at the checkout's name is the obvious way to make an
    existence check say yes, so the check is on identity, not on existence.

    "On identity, not on existence" is true and, on its own, was NOT ENOUGH: it
    says nothing about whether the identity can be FORGED. It could -- see
    ``test_cleanup_refuses_a_junction_wearing_the_primary_checkouts_name``
    below, where a decoy that is a LINK to the moved checkout made the identity
    check answer through the attacker's own junction and agree with itself.
    This test covers the real-directory decoy only.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    os.rename(temp_git_repo, worktree_path / "moved_in")
    temp_git_repo.mkdir()               # a decoy wearing the checkout's name

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "something else now wears its name" in str(excinfo.value)
    assert (worktree_path / "moved_in" / "test.txt").read_text() == "initial content"


def _work_files(directory: Path, count: int = 40) -> int:
    return sum(1 for i in range(count) if (directory / f"work{i:02d}.txt").exists())


def _fill_with_work(repo: Path, count: int = 40) -> None:
    """Enough tracked files that a destroyed checkout is countable, not binary."""
    (repo / "SENTINEL.txt").write_text("the primary repository")
    for i in range(count):
        (repo / f"work{i:02d}.txt").write_text("YEARS OF WORK")


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_refuses_a_junction_wearing_the_primary_checkouts_name(
        temp_git_repo, worktree_root):
    """THE FORGERY: the decoy is a LINK to the checkout it replaced.

    The identity check above compares ``(st_dev, st_ino)``. It read ``os.stat``,
    which FOLLOWS a reparse point, so pointing the decoy AT the moved checkout
    made the manager read the moved checkout's own identity and agree that
    nothing had changed. Measured on this box against the manager's own
    ``repo_path``, before ``_path_identity`` was made no-follow:

        os.stat  (junction) ino == os.stat (target) ino   -> identity MATCHED
        40/40 tracked work files destroyed, SENTINEL.txt gone, .git gone,
        and the only error raised was `git worktree prune` afterwards
        noticing that the repository had disappeared.

    Nothing is monkeypatched here: a real ``mklink /J`` junction, the shipped
    ``cleanup_worktree``, the shipped guard.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    _fill_with_work(temp_git_repo)
    before = _work_files(temp_git_repo)
    assert before == 40

    moved_in = worktree_path / "moved_in"
    os.rename(temp_git_repo, moved_in)
    assert _make_junction(temp_git_repo, moved_in), "could not stage the attack"
    # The precondition that made this work: os.stat cannot tell them apart.
    assert os.stat(temp_git_repo).st_ino == os.stat(moved_in).st_ino, (
        "precondition: a following stat must read the junction's TARGET, which "
        "is why the identity was forgeable")

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "reparse point" in str(excinfo.value)
    assert _work_files(moved_in) == before, "the checkout was DESTROYED"
    assert (moved_in / "SENTINEL.txt").exists()
    assert (moved_in / ".git").exists()
    assert (moved_in / "test.txt").read_text() == "initial content"


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_refuses_a_junction_wearing_the_name_of_an_ANCESTOR_of_the_checkout(
        worktree_root, tmp_path):
    """The same forgery one component up, which a leaf-only check cannot see.

    The candidate moves the checkout's PARENT into the worktree and junctions
    the PARENT's name. ``repo_path`` itself is then a perfectly real directory
    -- it is just being read THROUGH a junction -- so the leaf reparse check
    says no, and ``lstat`` on the leaf follows the junctioned parent as an
    intermediate component and returns the MOVED checkout's own identity, so the
    leaf identity check agrees too. Measured with only the leaf checks in place:
    40/40 work files destroyed, ``SENTINEL.txt`` gone, both ``stat`` and
    ``lstat`` reporting the recorded identity, and the only error a
    ``NotADirectoryError`` raised after the damage.

    Real junction, shipped ``cleanup_worktree``, shipped guard.
    """
    holder = tmp_path / "holder"
    repo = _init_git_repo(holder / "checkout")
    _fill_with_work(repo)
    manager = GitWorktreeManager(repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    before = _work_files(repo)
    assert before == 40

    moved_in = worktree_path / "moved_in"
    os.rename(holder, moved_in)
    assert _make_junction(holder, moved_in), "could not stage the attack"
    # The precondition: the LEAF looks untouched by every leaf-local test.
    assert not worktree_module._is_reparse_point(manager.repo_path)
    assert worktree_module._path_identity(manager.repo_path) == manager._repo_identity

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "reached THROUGH" in str(excinfo.value)
    assert _work_files(moved_in / "checkout") == before, "the checkout was DESTROYED"
    _assert_decoy_intact(moved_in / "checkout")


@pytest.mark.skipif(os.name != 'nt', reason="directory junctions are Windows-only")
def test_cleanup_refuses_a_junction_decoy_with_no_inode_numbers_to_compare(
        temp_git_repo, worktree_root):
    """Why the reparse check is not decoration next to the identity check.

    ``_path_identity`` returns ``st_ino == 0`` on a filesystem that exposes no
    inode numbers (FAT, some network mounts), and the SHIPPED guard treats a
    zero inode as no identity -- ``recorded[1] and ...`` -- because comparing
    zeroes would make every directory equal to every other. On such a
    filesystem the identity checks switch themselves off and the reparse check
    is the ONLY thing between the junction decoy and the checkout.

    That filesystem is simulated by writing the identities the shipped
    ``_path_identity`` would have returned on it. Everything else is the shipped
    path: a real junction, the shipped guard, the shipped zero-inode branch.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    _fill_with_work(temp_git_repo)
    before = _work_files(temp_git_repo)

    # What this manager would have recorded on an inode-less filesystem.
    device = manager._repo_identity[0]
    manager._repo_identity = (device, 0)
    manager._repo_ancestor_identity = [(p, (device, 0))
                                       for p, _ in manager._repo_ancestor_identity]

    moved_in = worktree_path / "moved_in"
    os.rename(temp_git_repo, moved_in)
    assert _make_junction(temp_git_repo, moved_in), "could not stage the attack"

    with pytest.raises(WorktreeContainmentError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    assert "reparse point" in str(excinfo.value)
    assert _work_files(moved_in) == before, "the checkout was DESTROYED"
    assert (moved_in / "SENTINEL.txt").exists()
    assert (moved_in / ".git").exists()


def test_a_legitimate_cleanup_survives_the_ancestor_identity_check(
        temp_git_repo, worktree_root):
    """The allow case for the ancestor check, stated next to the block cases.

    The chain above a checkout is recorded as it is found and only ever
    compared against itself, so a checkout living under a redirected profile
    folder, a OneDrive placeholder or a developer's own junction is normal and
    must clean up normally. A guard that refuses a machine's layout would leak
    a worktree on every attempt.
    """
    manager = GitWorktreeManager(temp_git_repo)
    assert manager._repo_ancestor_identity, "no ancestors were recorded at all"
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    manager.cleanup_worktree(worktree_path)

    assert not worktree_path.exists()
    assert (temp_git_repo / "test.txt").read_text() == "initial content"


def test_legitimate_cleanup_still_succeeds_after_containment(temp_git_repo, worktree_root):
    """The allow case, stated once more next to the block cases."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "feature/nested-name")

    manager.cleanup_worktree(worktree_path)

    assert not worktree_path.exists()
    result = subprocess.run(['git', 'worktree', 'list'], cwd=temp_git_repo,
                            capture_output=True, text=True, check=True)
    assert "feature/nested-name" not in result.stdout


# --------------------------------------------------------------------------- #
# the branch ref leak: `git worktree add -b` writes into the SHARED .git and    #
# nothing removed it, so an overnight loop accumulates one ref per attempt.     #
# Reaping is a SEPARATE step on purpose -- see GitWorktreeManager.reap_branches #
# --------------------------------------------------------------------------- #
def _branches(repo_path):
    return subprocess.run(['git', 'branch', '--list'], cwd=repo_path,
                          capture_output=True, text=True, check=True).stdout


def test_cleanup_deliberately_leaves_the_branch_findable(temp_git_repo, worktree_root):
    """Cleanup must NOT delete the branch: in spine/attempt.py it is the effect
    key, and cleanup runs in a finally: that precedes ledger resolution."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    manager.cleanup_worktree(worktree_path)

    assert "test-branch" in _branches(temp_git_repo)


def test_reap_deletes_a_candidate_branch_that_holds_no_work(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    manager.cleanup_worktree(worktree_path)

    report = manager.reap_branches()

    assert [(r["branch"], r["action"]) for r in report] == [("test-branch", "deleted")]
    assert "test-branch" not in _branches(temp_git_repo)
    # the repo's own branch is untouched
    assert _branches(temp_git_repo).strip()
    # and reaping again is a no-op, not an error
    assert manager.reap_branches() == []


def test_reap_refuses_to_delete_a_branch_that_holds_commits(temp_git_repo, worktree_root):
    """The kairos/shadow_shell flow commits candidate work ONTO the branch.
    That work is the deliverable; the reaper must not touch it."""
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    (worktree_path / "candidate.txt").write_text("the only copy of this work")
    manager.commit_candidate(worktree_path, "candidate work")

    manager.cleanup_worktree(worktree_path)
    report = manager.reap_branches()

    assert [r["action"] for r in report] == ["retained"]
    assert "would destroy work" in report[0]["reason"]
    assert "test-branch" in _branches(temp_git_repo)
    kept = subprocess.run(['git', 'show', 'test-branch:candidate.txt'],
                          cwd=temp_git_repo, capture_output=True, text=True, check=True)
    assert kept.stdout.strip() == "the only copy of this work"


def test_reap_does_not_touch_a_branch_whose_worktree_is_still_in_use(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    manager.create_worktree("HEAD", "test-branch")

    report = manager.reap_branches()

    assert [r["action"] for r in report] == ["pending"]
    assert "test-branch" in _branches(temp_git_repo)


def test_reap_ignores_branches_this_manager_never_allocated(temp_git_repo, worktree_root):
    manager = GitWorktreeManager(temp_git_repo)
    subprocess.run(['git', 'branch', 'a-human-branch'], cwd=temp_git_repo,
                   check=True, capture_output=True)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    manager.cleanup_worktree(worktree_path)

    manager.reap_branches()

    assert "a-human-branch" in _branches(temp_git_repo)


def test_reap_failure_is_reported_not_swallowed(temp_git_repo, worktree_root, monkeypatch):
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    manager.cleanup_worktree(worktree_path)

    def refuse_delete(branch, proven_tip):
        raise RuntimeError("git said no")
    monkeypatch.setattr(manager, '_delete_unused_branch', refuse_delete)

    with pytest.raises(RuntimeError) as excinfo:
        manager.reap_branches()

    assert "failed to reap candidate branches" in str(excinfo.value)
    assert "git said no" in str(excinfo.value)
    assert "test-branch" in _branches(temp_git_repo)


# --------------------------------------------------------------------------- #
# reap's TRUST MODEL. The allocation directory is one `.parent` away from the   #
# worktree path a candidate is handed, so every byte in it is attacker-written. #
# These tests forge records the way candidate code can, and assert that the     #
# branches they name survive.                                                   #
# --------------------------------------------------------------------------- #
def _forge_allocation(manager, worktree_path: Path, branch: str, tip: str,
                      removed: bool = True) -> Path:
    """Write the record candidate code would write. Nothing here is secret."""
    record = {
        "schema": ALLOC_SCHEMA,
        "path": str(worktree_path),
        "repo": str(manager.repo_path),
        "branch": branch,
        "created_ts": datetime.now(timezone.utc).isoformat(),
        "branch_tip_at_creation": tip,
    }
    if removed:
        record["worktree_removed_ts"] = datetime.now(timezone.utc).isoformat()
    manager._alloc_dir().mkdir(parents=True, exist_ok=True)
    path = manager._alloc_file(worktree_path)
    path.write_text(json.dumps(record), encoding='utf-8')
    return path


def _git_out(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, capture_output=True,
                          text=True, check=True).stdout.strip()


def test_reap_ignores_forged_allocation_records(temp_git_repo, worktree_root):
    """CRITICAL: forged records named real branches at their real tips.

    Both halves of "the tip matches what was recorded at allocation" came from
    the same forged file, so the comparison proved nothing and the printed
    reason ("no work") was false. Nothing on disk may authorise a delete.
    """
    manager = GitWorktreeManager(temp_git_repo)
    subprocess.run(['git', 'checkout', '-b', 'feature/six-months-of-work'],
                   cwd=temp_git_repo, check=True, capture_output=True)
    (temp_git_repo / "irreplaceable.txt").write_text("the only copy")
    subprocess.run(['git', 'add', '-A'], cwd=temp_git_repo, check=True,
                   capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'months of work'], cwd=temp_git_repo,
                   check=True, capture_output=True)
    subprocess.run(['git', 'checkout', '-'], cwd=temp_git_repo, check=True,
                   capture_output=True)

    tip = _git_out(temp_git_repo, 'rev-parse', '--verify',
                   'refs/heads/feature/six-months-of-work')
    _forge_allocation(manager, manager.worktree_root / "anything",
                      'feature/six-months-of-work', tip)

    report = manager.reap_branches()

    assert "feature/six-months-of-work" in _branches(temp_git_repo)
    assert [r["action"] for r in report] == ["unverifiable"]
    # and the report does not repeat the forgery's own claims back at us
    assert report[0]["branch"] is None


def test_a_fresh_manager_does_not_reap_records_it_did_not_create(
        temp_git_repo, worktree_root):
    """The crash-recovery path is deliberately closed. A leaked ref is cheap."""
    first = GitWorktreeManager(temp_git_repo)
    worktree_path = first.create_worktree("HEAD", "test-branch")
    first.cleanup_worktree(worktree_path)

    report = GitWorktreeManager(temp_git_repo).reap_branches()

    assert [r["action"] for r in report] == ["unverifiable"]
    assert "test-branch" in _branches(temp_git_repo)
    # the manager that DID allocate it can still reap it
    assert [r["action"] for r in first.reap_branches()] == ["deleted"]


def test_reap_ignores_a_forged_removal_timestamp_for_a_live_worktree(
        temp_git_repo, worktree_root):
    """Candidate code marking its own worktree "removed" must not free the ref.

    The branch is the effect key while the worktree is live; deleting it there
    strands an OPEN intent with no findable effect.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    record = manager._read_allocation(worktree_path)
    record["worktree_removed_ts"] = datetime.now(timezone.utc).isoformat()
    manager._write_allocation(worktree_path, record)

    report = manager.reap_branches()

    assert [r["action"] for r in report] == ["pending"]
    assert "test-branch" in _branches(temp_git_repo)


def test_reap_refuses_a_branch_whose_tip_no_other_ref_contains(
        temp_git_repo, worktree_root):
    """"Deletes no work" means "orphans no commit", and git is the only witness.

    The allocation tip matches -- nothing was committed to the branch -- but the
    commit it was BASED on is referenced by nothing else, so the branch is the
    only thing holding that history.
    """
    manager = GitWorktreeManager(temp_git_repo)
    (temp_git_repo / "extra.txt").write_text("work about to lose its ref")
    subprocess.run(['git', 'add', '-A'], cwd=temp_git_repo, check=True,
                   capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'extra'], cwd=temp_git_repo,
                   check=True, capture_output=True)
    unreferenced = _git_out(temp_git_repo, 'rev-parse', 'HEAD')
    subprocess.run(['git', 'reset', '--hard', 'HEAD~1'], cwd=temp_git_repo,
                   check=True, capture_output=True)

    worktree_path = manager.create_worktree(unreferenced, "orphan-branch")
    manager.cleanup_worktree(worktree_path)

    report = manager.reap_branches()

    assert [r["action"] for r in report] == ["retained"]
    assert "would orphan" in report[0]["reason"]
    assert "orphan-branch" in _branches(temp_git_repo)
    assert _git_out(temp_git_repo, 'rev-parse',
                    'refs/heads/orphan-branch') == unreferenced


def test_reap_retains_a_branch_when_git_cannot_say_who_contains_its_tip(
        temp_git_repo, worktree_root, monkeypatch):
    """A git failure is NOT a yes. Fail closed, or the reaper orphans commits.

    ``_refs_containing`` asks git the one question in the reap decision that no
    candidate can forge: "does any OTHER ref still contain this tip?". An empty
    answer means the branch is the only thing holding that history, and reap
    retains it. If the CALL ITSELF fails -- git missing, repository locked,
    ``.git`` being written by something else, a candidate that exhausted the
    handle table -- the guard returns the empty list, which lands on exactly the
    same retain path.

    Deleting that ``except`` lets the RuntimeError escape ``reap_branches``
    instead, and this test goes red on the exception. But the interesting damage
    is what it does to the branch it was called about:
    ``test_reap_deletes_a_candidate_branch_that_holds_no_work`` is this same
    setup with git answering, and it ends in ``deleted``.

    What is simulated is a git invocation failing, which is the only condition
    this guard exists for. ``reap_branches``, ``_refs_containing`` and the
    retain path are all the shipped ones.
    """
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")
    tip = _git_out(temp_git_repo, 'rev-parse', 'refs/heads/test-branch')
    manager.cleanup_worktree(worktree_path)

    real_run_git = manager._run_git

    def git_that_cannot_answer(*args, **kwargs):
        if args and args[0] == 'for-each-ref':
            raise RuntimeError(
                "Git command failed: git for-each-ref\nError: simulated failure")
        return real_run_git(*args, **kwargs)

    monkeypatch.setattr(manager, '_run_git', git_that_cannot_answer)

    report = manager.reap_branches()

    assert [r["action"] for r in report] == ["retained"]
    assert "would orphan" in report[0]["reason"]
    assert "test-branch" in _branches(temp_git_repo)
    assert _git_out(temp_git_repo, 'rev-parse', 'refs/heads/test-branch') == tip


def test_force_delete_refuses_when_the_branch_tip_moved(temp_git_repo, worktree_root):
    """The re-taken sha is what authorises ``-D``; a stale proof authorises nothing.

    Called directly, because that is the only way to pin THIS guard: reap's own
    checks would refuse first, and then the force path would never be reached.
    """
    manager = GitWorktreeManager(temp_git_repo)
    subprocess.run(['git', 'checkout', '-b', 'sidework'], cwd=temp_git_repo,
                   check=True, capture_output=True)
    (temp_git_repo / "side.txt").write_text("unmerged work")
    subprocess.run(['git', 'add', '-A'], cwd=temp_git_repo, check=True,
                   capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'side'], cwd=temp_git_repo,
                   check=True, capture_output=True)
    subprocess.run(['git', 'checkout', '-'], cwd=temp_git_repo, check=True,
                   capture_output=True)

    with pytest.raises(RuntimeError) as excinfo:
        manager._delete_unused_branch('sidework', '0' * 40)

    assert "tip moved" in str(excinfo.value)
    assert "sidework" in _branches(temp_git_repo)
    assert _git_out(temp_git_repo, 'show', 'sidework:side.txt') == "unmerged work"


def test_cleanup_is_repeatable_by_a_fresh_manager(temp_git_repo, worktree_root):
    """A crashed run leaks a worktree; a NEW process must still be able to
    clean it up (spine/attempt.py does exactly this after a failed cleanup)."""
    worktree_path = GitWorktreeManager(temp_git_repo).create_worktree("HEAD", "test-branch")

    GitWorktreeManager(temp_git_repo).cleanup_worktree(worktree_path)

    assert not worktree_path.exists()
