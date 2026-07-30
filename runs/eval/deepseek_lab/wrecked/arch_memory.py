"""Tests for arch_memory.py

Coverage targets:
- render_delta: first call, unchanged tree, changed tree, staleness detection
- build: line/character budget enforcement
- render: staleness detection
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.arch_memory import (
    ArchMemory,
    MAX_LINE_CHARS,
    MAX_LINES,
    MEMORY_REL_PATH,
    LAST_SHOWN_REL_PATH,
    STATE_REL_PATH,
    build,
    load,
    render,
    render_delta,
    save,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_git_mock(returns: dict):
    """Return a callable that responds to 'git' args with canned strings."""

    def mock_git(root, *args):
        key = args
        return returns.get(key, "")

    return mock_git


def _write_json(root: Path, rel: str, data: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: line / character budget in build()
# ---------------------------------------------------------------------------


def test_build_respects_line_and_char_limits(tmp_path, monkeypatch):
    """The built memory never exceeds MAX_LINES or MAX_LINE_CHARS."""
    git_returns = {
        ("rev-parse", "HEAD"): "abc123def456",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    # Provide a state that would generate many lines:
    # 30 package roles (build takes at most 9), but the other sections will push us over 24.
    state = {
        "counts": {
            "modules": 100,
            "islands": 2,
            "shims": 2,
            "unreached": 1,
            "doc_drift": 1,
            "unknown": 5,
            "unparsable": 3,
        },
        "islands": ["daedalus/some_island.py", "daedalus/another_island.py"],
        "shims": ["daedalus/shim_a.py", "daedalus/shim_b.py"],
        "doc_drift": ["some_drift"],
        "repo_state": {"head": "abc123def456"},
    }
    _write_json(tmp_path, STATE_REL_PATH, state)

    # Return many long role strings to stress line and character budgets.
    def fake_roles(_root):
        return [
            "x" * 200,  # each line will be truncated to MAX_LINE_CHARS
        ] * 40

    monkeypatch.setattr("daedalus.arch_memory._package_roles", fake_roles)

    mem = build(tmp_path)

    assert len(mem.lines) == MAX_LINES
    for line in mem.lines:
        assert len(line) <= MAX_LINE_CHARS


# ---------------------------------------------------------------------------
# Tests: render_delta
# ---------------------------------------------------------------------------


def test_render_delta_first_call_shows_everything(tmp_path, monkeypatch):
    """When there is no last_shown file, render_delta returns the full snapshot."""
    git_returns = {
        ("rev-parse", "HEAD"): "abc123def456",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: [])

    # Build a memory with a known set of lines
    memory = build(tmp_path)
    expected_lines = list(memory.lines)
    # Build creates memory but does not save; we need to save and load for render_delta.
    save(memory, tmp_path)

    # Sanity: no last_shown file yet
    assert not (tmp_path / LAST_SHOWN_REL_PATH).exists()

    rendered = render_delta(tmp_path)

    assert rendered == "\n".join(expected_lines)
    # Side effect: last_shown file now contains the same lines
    stored = (tmp_path / LAST_SHOWN_REL_PATH).read_text(encoding="utf-8").splitlines()
    assert stored == expected_lines


def test_render_delta_unchanged_tree_costs_one_line(tmp_path, monkeypatch):
    """When nothing has changed since the last showing, only a one-line message is returned."""
    git_returns = {
        ("rev-parse", "HEAD"): "abc123def456",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: [])

    # Create a memory and a matching last_shown file
    memory = build(tmp_path)
    save(memory, tmp_path)
    lines = list(memory.lines)
    (tmp_path / LAST_SHOWN_REL_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / LAST_SHOWN_REL_PATH).write_text("\n".join(lines), encoding="utf-8")

    rendered = render_delta(tmp_path)

    assert rendered == "ARCHITECTURE: unchanged since the last turn"


def test_render_delta_changed_tree_shows_only_what_moved(tmp_path, monkeypatch):
    """When the snapshot differs from the last shown one, only the delta is displayed."""
    git_returns = {
        ("rev-parse", "HEAD"): "abc123def456",
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))

    # Two different sets of roles to create a change
    original_roles = ["role_a    first sentence a"]
    updated_roles = ["role_a    first sentence a", "role_b    first sentence b"]

    # Build a memory with the updated roles (this will be the "now" state)
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: updated_roles)
    memory = build(tmp_path)
    save(memory, tmp_path)

    # Fake a last_shown file with the original roles
    # To get the old snapshot, we need to build it with the original roles.
    # Build again with original roles (but don't save the memory, just get the lines)
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: original_roles)
    old_memory = build(tmp_path)
    old_lines = list(old_memory.lines)
    (tmp_path / LAST_SHOWN_REL_PATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / LAST_SHOWN_REL_PATH).write_text("\n".join(old_lines), encoding="utf-8")

    rendered = render_delta(tmp_path)

    # Check structure: starts with the banner line, then removed lines, then added lines.
    rendered_lines = rendered.splitlines()
    assert rendered_lines[0] == "ARCHITECTURE CHANGED since the last turn:"
    # There should be at least one "- " line and one "+ " line.
    assert any(line.startswith("  - ") for line in rendered_lines)
    assert any(line.startswith("  + ") for line in rendered_lines)


def test_render_delta_staleness_against_moved_head(tmp_path, monkeypatch):
    """When the stored memory's HEAD differs from the live HEAD, the staleness warning is shown."""
    live_head = "abc123def456"
    stored_head = "old_head_1"
    git_returns = {
        ("rev-parse", "HEAD"): live_head,
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: [])

    memory = build(tmp_path)
    # Override the head to be stale
    memory.head = stored_head
    save(memory, tmp_path)

    rendered = render_delta(tmp_path)

    # The staleness line must be the first line of the "now" snapshot
    assert f"ARCH MEMORY IS STALE: built at {stored_head[:8]}, HEAD is now {live_head[:8]}" in rendered
    # It should appear before the other lines
    rendered_lines = rendered.splitlines()
    assert rendered_lines[1].startswith("ARCH MEMORY IS STALE")


# ---------------------------------------------------------------------------
# Tests: render() staleness detection
# ---------------------------------------------------------------------------


def test_render_shows_staleness_when_head_moved(tmp_path, monkeypatch):
    """render() detects staleness against the live HEAD and prepends a warning."""
    live_head = "abc123def456"
    stored_head = "xyz00000000"
    git_returns = {
        ("rev-parse", "HEAD"): live_head,
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: [])

    memory = build(tmp_path)
    memory.head = stored_head
    save(memory, tmp_path)

    rendered = render(tmp_path)

    # Should start with the staleness banner
    expected_prefix = f"ARCH MEMORY IS STALE: built at {stored_head[:8]}, HEAD is now {live_head[:8]}"
    assert rendered.startswith(expected_prefix)
    # The original memory lines should still be present after the banner
    assert "\n".join(memory.lines) in rendered


# ---------------------------------------------------------------------------
# Tests: build() staleness in the snapshot itself
# ---------------------------------------------------------------------------


def test_build_shows_staleness_when_state_head_mismatch(tmp_path, monkeypatch):
    """If the state file's head differs from live HEAD, build() marks the snapshot as STALE."""
    live_head = "abc123def456"
    state_head = "deadbeef0000"
    git_returns = {
        ("rev-parse", "HEAD"): live_head,
        ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        ("status", "--porcelain"): "",
    }
    monkeypatch.setattr("daedalus.arch_memory._git", _make_git_mock(git_returns))
    monkeypatch.setattr("daedalus.arch_memory._package_roles", lambda _: [])

    state = {
        "repo_state": {"head": state_head},
        "counts": {
            "modules": 10,
            "islands": 0,
            "shims": 0,
            "unreached": 0,
            "doc_drift": 0,
        },
    }
    _write_json(tmp_path, STATE_REL_PATH, state)

    mem = build(tmp_path)

    first_line = mem.lines[0]
    assert "STALE" in first_line
    assert state_head[:8] in first_line
    assert live_head[:8] in first_line
