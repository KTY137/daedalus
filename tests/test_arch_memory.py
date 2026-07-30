"""Tests for arch_memory module."""
import os
import pytest

# Assume ArchMemory lives in daedalus.arch_memory 
# from daedalus.arch_memory import ArchMemory
# For testing purposes we mock the class here, but the intended import is above.
class ArchMemory:
    """Stub to satisfy import during test development."""
    def __init__(self, repo_path):
        self.repo_path = repo_path
    def render_delta(self, max_lines=None, max_chars=None):
        raise NotImplementedError
    def is_stale(self):
        raise NotImplementedError


@pytest.fixture
def repo_with_files(tmp_path):
    """Create a temporary directory with some files."""
    (tmp_path / 'file1.py').write_text("print('hello')")
    (tmp_path / 'subdir').mkdir()
    (tmp_path / 'subdir/file2.py').write_text("def foo(): pass")
    return tmp_path


class TestArchMemory:
    """Tests for the architectural memory model."""

    def test_render_delta_first_call_shows_everything(self, repo_with_files):
        """On the very first call, render_delta should output the entire tree."""
        am = ArchMemory(str(repo_with_files))
        delta = am.render_delta()
        # The output must include all file names and their contents.
        assert 'file1.py' in delta
        assert 'file2.py' in delta
        assert "print('hello')" in delta
        assert "def foo(): pass" in delta

    def test_render_delta_no_change_returns_one_liner(self, repo_with_files):
        """When the tree is unchanged, the delta should be exactly one line."""
        am = ArchMemory(str(repo_with_files))
        am.render_delta()  # establish a baseline
        delta = am.render_delta()
        lines = [line for line in delta.splitlines() if line.strip()]
        assert len(lines) == 1
        assert 'no change' in delta.lower()

    def test_render_delta_changed_tree_shows_only_moved(self, repo_with_files):
        """If only a subset of files change, the delta should only mention those parts."""
        am = ArchMemory(str(repo_with_files))
        am.render_delta()
        # Modify a file and add a new one
        (repo_with_files / 'file1.py').write_text("print('world')")
        (repo_with_files / 'new.txt').write_text('extra')
        delta = am.render_delta()
        # Delta should contain the changed content but not the unchanged file's full content again
        assert "print('hello')" not in delta
        assert "print('world')" in delta
        assert 'new.txt' in delta
        assert 'file2.py' not in delta  # because it didn't change

    def test_staleness_detection_after_head_move(self, tmp_path):
        """ArchMemory must detect when the underlying git HEAD has advanced."""
        pytest.importorskip('git')
        import git
        repo = git.Repo.init(tmp_path)
        (tmp_path / 'file.txt').write_text('v1')
        repo.index.add(['file.txt'])
        repo.index.commit('initial')
        am = ArchMemory(str(tmp_path))
        # Simulate external advancement: create a new branch and commit
        new_branch = repo.create_head('new_branch')
        new_branch.checkout()
        (tmp_path / 'file.txt').write_text('v2')
        repo.index.add(['file.txt'])
        repo.index.commit('v2')
        # staleness should be True because HEAD moved
        assert am.is_stale()

    def test_render_delta_line_budget(self, repo_with_files):
        """render_delta must respect a max_lines argument."""
        # Create many files to generate many lines of delta
        for i in range(50):
            (repo_with_files / f'extra{i}.py').write_text(f"# file {i}\nprint('hello')")
        am = ArchMemory(str(repo_with_files))
        delta = am.render_delta(max_lines=10)
        lines = delta.splitlines()
        # Allow one extra line for trailing newline if present
        assert len(lines) <= 11

    def test_render_delta_char_budget(self, repo_with_files):
        """render_delta must respect a max_chars argument."""
        for i in range(5):
            (repo_with_files / f'big{i}.py').write_text('a' * 200)
        am = ArchMemory(str(repo_with_files))
        delta = am.render_delta(max_chars=500)
        assert len(delta) <= 500
