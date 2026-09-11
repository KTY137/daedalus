"""Contract tests for the public architecture-memory compatibility facade."""
from __future__ import annotations

import shutil
import subprocess

import pytest

from daedalus.arch_memory import ArchMemory, is_stale, render_delta, save


@pytest.fixture
def repo_with_memory(tmp_path):
    save(
        ArchMemory(
            lines=(
                "file1.py",
                "print('hello')",
                "subdir/file2.py",
                "def foo(): pass",
            )
        ),
        tmp_path,
    )
    return tmp_path


def test_render_delta_first_call_shows_everything(repo_with_memory):
    delta = render_delta(repo_with_memory)
    assert "file1.py" in delta
    assert "file2.py" in delta
    assert "print('hello')" in delta
    assert "def foo(): pass" in delta


def test_render_delta_no_change_returns_one_liner(repo_with_memory):
    render_delta(repo_with_memory)
    delta = render_delta(repo_with_memory)
    lines = [line for line in delta.splitlines() if line.strip()]
    assert len(lines) == 1
    assert "unchanged" in delta.lower()


def test_render_delta_changed_snapshot_only_shows_moved_lines(repo_with_memory):
    render_delta(repo_with_memory)
    save(
        ArchMemory(
            lines=(
                "file1.py",
                "print('world')",
                "subdir/file2.py",
                "def foo(): pass",
                "new.txt",
                "extra",
            )
        ),
        repo_with_memory,
    )

    delta = render_delta(repo_with_memory)

    assert "print('hello')" in delta
    assert "print('world')" in delta
    assert "new.txt" in delta
    assert "file2.py" not in delta
    assert "def foo(): pass" not in delta


def test_staleness_detection_after_head_move(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git executable unavailable")

    def git(*args: str) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return completed.stdout.strip()

    git("init")
    git("config", "user.name", "Daedalus Tests")
    git("config", "user.email", "tests@daedalus.invalid")
    (tmp_path / "file.txt").write_text("v1", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-m", "initial")
    measured_head = git("rev-parse", "HEAD")
    save(ArchMemory(head=measured_head, lines=("ARCHITECTURE: measured",)), tmp_path)

    (tmp_path / "file.txt").write_text("v2", encoding="utf-8")
    git("add", "file.txt")
    git("commit", "-m", "advance")

    assert is_stale(tmp_path)
    assert "STALE" in render_delta(tmp_path)


def test_render_delta_line_budget(tmp_path):
    save(ArchMemory(lines=tuple(f"line-{index}" for index in range(50))), tmp_path)
    delta = render_delta(tmp_path, max_lines=10)
    assert len(delta.splitlines()) <= 10


def test_render_delta_char_budget(tmp_path):
    save(ArchMemory(lines=tuple("a" * 200 for _ in range(5))), tmp_path)
    delta = render_delta(tmp_path, max_chars=500)
    assert len(delta) <= 500


@pytest.mark.parametrize(
    ("keyword", "value"),
    (("max_lines", -1), ("max_lines", True), ("max_chars", -1), ("max_chars", 1.5)),
)
def test_render_delta_rejects_invalid_budgets(tmp_path, keyword, value):
    save(ArchMemory(lines=("architecture",)), tmp_path)
    with pytest.raises(ValueError):
        render_delta(tmp_path, **{keyword: value})
