import pytest
import subprocess
from pathlib import Path

import daedalus.kairos.worktree as worktree_module
from daedalus.kairos.worktree import GitWorktreeManager
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

def test_default_placement_uses_localappdata(temp_git_repo, tmp_path, monkeypatch):
    monkeypatch.delenv('DAEDALUS_WORKTREE_ROOT', raising=False)
    fake_localappdata = tmp_path / "fake_localappdata"
    monkeypatch.setenv('LOCALAPPDATA', str(fake_localappdata))

    manager = GitWorktreeManager(temp_git_repo)
    root = manager.worktree_root

    assert root.parent.parent == fake_localappdata / 'daedalus'
    assert root.parent == fake_localappdata / 'daedalus' / 'worktrees'
    # Repo digest namespaces distinct checkouts
    other = GitWorktreeManager(tmp_path)
    assert other.worktree_root != root

    worktree_path = manager.create_worktree("HEAD", "test-branch")
    assert worktree_path == root / "test-branch"
    assert worktree_path.exists()
    manager.cleanup_worktree(worktree_path)

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
    manager = GitWorktreeManager(temp_git_repo)
    worktree_path = manager.create_worktree("HEAD", "test-branch")

    def failing_run_git(*args, cwd=None):
        raise RuntimeError("git worktree remove failed")
    monkeypatch.setattr(manager, '_run_git', failing_run_git)

    def failing_rmtree(path, *args, **kwargs):
        raise OSError("permission denied")
    monkeypatch.setattr(worktree_module.shutil, 'rmtree', failing_rmtree)

    with pytest.raises(RuntimeError) as excinfo:
        manager.cleanup_worktree(worktree_path)

    message = str(excinfo.value)
    assert "failed to remove worktree directory" in message
    assert "git worktree remove also failed" in message

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
