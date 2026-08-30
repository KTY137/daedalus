# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Regressions for the 2026-08-25 hooks review.

Every defect covered here was green-by-absence: the code did the wrong thing
and no test asked. Each test therefore names the measurement that motivated
it, so a later reader can tell a real invariant from a guess.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus import arch_memory
from daedalus.hooks import __main__ as entry
from daedalus.hooks import _common, events


RECEIPT = entry.start_effect()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "hooks@example.invalid")
    _git(root, "config", "user.name", "Hooks Test")
    (root / "vault").mkdir()
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")
    return root


# --------------------------------------------------------------------------
# the injection budget
# --------------------------------------------------------------------------


def test_clip_block_keeps_the_head_and_says_what_it_cut() -> None:
    """A block with its own budget degrades; it does not vanish.

    [MEASURED 2026-08-25] the architecture delta is 1,299 chars and the shift
    line 251: together 50 over the 1,500 cap, and the trimmer's answer was to
    drop all 1,299.
    """
    block = "\n".join(f"line {i} " + "x" * 40 for i in range(40))
    clipped = _common.clip_block(block, 300)
    assert len(clipped) <= 300
    assert clipped.startswith("line 0 ")          # the head survives
    assert "clipped" in clipped.splitlines()[-1]  # and it admits the cut
    assert _common.clip_block("short", 300) == "short"
    assert _common.clip_block("", 300) == ""


def test_trim_lines_counts_and_trim_to_budget_stays_boolean() -> None:
    """The instrument gained a number without breaking its old callers."""
    text, dropped = _common.trim_lines(["a" * 50, "b" * 50, "c" * 50], cap=110)
    assert dropped == 1
    assert text == "a" * 50 + "\n" + "b" * 50
    assert _common.trim_lines(["ok"], cap=10) == ("ok", 0)
    # the boolean view the existing suite asserts on, unchanged
    assert _common.trim_to_budget(["ok"], cap=10) == ("ok", False)
    assert _common.trim_to_budget(["a" * 50, "b" * 50], cap=60)[1] is True


def test_the_alarm_outranks_the_catalogue(repo: Path, monkeypatch) -> None:
    """The watchdog's anomalies survive a huge architecture delta.

    [MEASURED 2026-08-25, runs/hooks/ledger.jsonl] 111 of 113 turns were
    trimmed and 98 emitted about 250 chars -- the shift line alone. The delta
    came second in the list and the watchdog line last, and trim_lines drops
    from the END, so the most alarming line this hook has was first out.
    """
    health = repo / "runs" / "watchdog"
    health.mkdir(parents=True)
    (health / "health.json").write_text(
        json.dumps({"anomalies": [{"id": "temp_bloat"}, {"id": "commit_gap"}]}),
        encoding="utf-8",
    )
    _common.update_state(repo, "sid1", lambda s: s.update({"config_changed": ["settings.json"]}))
    monkeypatch.setattr(
        arch_memory, "render_delta", lambda *a, **k: "\n".join(f"pkg {i}" for i in range(400))
    )

    result = events.user_prompt({"cwd": str(repo)}, repo, "sid1")
    text = result.text

    assert "WATCHDOG: commit_gap; temp_bloat" in text, "the alarm was dropped again"
    assert "CONFIG changed" in text
    assert len(text) <= _common.TURN_BUDGET_CHARS
    # the delta is present but last, and clipped to its own budget
    assert "pkg 0" in text
    assert text.index("WATCHDOG") < text.index("pkg 0"), "alarm must precede the catalogue"
    delta_part = text[text.index("pkg 0"):]
    assert len(delta_part) <= events.ARCH_DELTA_CHARS


def test_an_enormous_delta_cannot_starve_the_alarms(repo: Path, monkeypatch) -> None:
    """Even a delta far larger than the whole budget only costs itself."""
    health = repo / "runs" / "watchdog"
    health.mkdir(parents=True)
    (health / "health.json").write_text(
        json.dumps({"anomalies": [{"id": "disk_full"}]}), encoding="utf-8"
    )
    monkeypatch.setattr(arch_memory, "render_delta", lambda *a, **k: "z" * 50_000)
    result = events.user_prompt({"cwd": str(repo)}, repo, "sid2")
    assert "WATCHDOG: disk_full" in result.text
    assert len(result.text) <= _common.TURN_BUDGET_CHARS


# --------------------------------------------------------------------------
# the compaction marker
# --------------------------------------------------------------------------


WATCHDOG_NOTE = (
    b"---\r\ntags: [session]\r\ndate: x\r\n---\r\n\r\n# Session x\r\n\r\n"
    b"## watchdog\r\n\r\n- 02:29 [watchdog] commit_gap: none\r\n"
)


def _daily_note(repo: Path) -> Path:
    return repo / "vault" / "Sessions" / f"{events._local_now():%Y-%m-%d}.md"


def test_marker_creates_its_section_in_a_note_someone_else_opened(repo: Path) -> None:
    """[MEASURED 2026-08-25] against the real shape of the day's vault note:
    the watchdog opens it at about 02:29 under its own heading, hours before
    any compaction, so every marker landed under the watchdog's heading and
    the compaction section was never created at all."""
    note = _daily_note(repo)
    note.parent.mkdir(parents=True)
    note.write_bytes(WATCHDOG_NOTE)

    assert events.pre_compact({"trigger": "auto"}, repo, "abcd1234").note == "precompact:auto"
    assert events.pre_compact({"trigger": "manual"}, repo, "abcd1234").note == "precompact:manual"

    text = note.read_bytes().decode("utf-8")
    assert "## watchdog" in text, "the other writer's section must survive"
    assert text.count(events.COMPACTION_SECTION) == 1, "one section, created once"
    assert text.index(events.COMPACTION_SECTION) < text.index("[compaction:auto]")
    assert text.count("[compaction:") == 2, "both markers, append-only"
    assert "- 02:29 [watchdog]" in text, "the watchdog's own line is untouched"


def test_marker_follows_the_files_line_endings(repo: Path) -> None:
    """A CRLF vault note stayed CRLF; appending LF left a mixed-ending file."""
    note = _daily_note(repo)
    note.parent.mkdir(parents=True)
    note.write_bytes(WATCHDOG_NOTE)
    events.pre_compact({"trigger": "auto"}, repo, "abcd1234")
    raw = note.read_bytes()
    assert b"\r\n" in raw
    assert raw.replace(b"\r\n", b"").count(b"\n") == 0, "mixed line endings"


def test_marker_survives_a_note_without_a_trailing_newline(repo: Path) -> None:
    note = _daily_note(repo)
    note.parent.mkdir(parents=True)
    note.write_bytes(b"# Session x\r\n\r\n## watchdog\r\n\r\n- 02:29 no trailing newline")
    events.pre_compact({"trigger": "auto"}, repo, "abcd1234")
    lines = note.read_bytes().decode("utf-8").splitlines()
    assert "- 02:29 no trailing newline" in lines, "the last line must not be glued to"
    assert any(line.startswith("- ") and "[compaction:" in line for line in lines)


def test_a_note_the_hook_creates_still_gets_its_section(repo: Path) -> None:
    events.pre_compact({"trigger": "auto"}, repo, "abcd1234")
    text = _daily_note(repo).read_text(encoding="utf-8")
    assert text.startswith("---")
    assert text.count(events.COMPACTION_SECTION) == 1


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------


def _ledger(repo: Path) -> list[dict]:
    path = repo / "runs" / "hooks" / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_an_unusable_payload_leaves_a_row_where_the_hooks_keep_state(repo: Path) -> None:
    """Being fed garbage used to look exactly like never being called."""
    (repo / "runs" / "hooks").mkdir(parents=True)
    result = entry.dispatch("turn", {"cwd": str(repo)}, RECEIPT, stdout=io.StringIO())
    assert result.note == "unusable-payload"
    rows = _ledger(repo)
    assert [r["note"] for r in rows] == ["unusable-payload"]
    assert rows[0]["event"] == "turn"


def test_an_unusable_payload_invents_no_state_outside_a_hooks_tree(repo: Path) -> None:
    """The limit on the fix: no runs/hooks/ in a directory that had none."""
    stdout = io.StringIO()
    result = entry.dispatch("turn", {"cwd": str(repo)}, RECEIPT, stdout=stdout)
    assert result.note == "unusable-payload"
    assert stdout.getvalue() == ""
    assert not (repo / "runs" / "hooks").exists()


# --------------------------------------------------------------------------
# the wire
# --------------------------------------------------------------------------


def test_the_answer_is_valid_utf8_even_from_a_legacy_console(tmp_path: Path) -> None:
    """Whatever the hook says, the harness must be able to read it.

    [MEASURED 2026-08-25] the real turn hook's stdout was NOT decodable: the
    architecture delta carries U+00B7 and Windows wrote it as the single cp1252
    byte 0xB7, while the harness reads UTF-8. The repository name is the one
    non-ASCII source this test can control exactly, so it drives the same path
    deterministically on any machine.
    """
    root = tmp_path / "repo-büße-·"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "hooks@example.invalid")
    _git(root, "config", "user.name", "Hooks Test")
    (root / "README.md").write_text("# fixture\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "fixture")

    payload = json.dumps(
        {"hook_event_name": "SessionStart", "cwd": str(root), "session_id": "utf8probe"}
    )
    proc = subprocess.run(
        [sys.executable, "-m", "daedalus.hooks", "session"],
        input=payload.encode("utf-8"),
        capture_output=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        timeout=120,
    )
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8")  # the assertion: it decodes at all
    assert "repo-büße-·" in text, "the name must survive the wire intact"


# --------------------------------------------------------------------------
# "could not measure" must be distinguishable from "measured, nothing found"
# --------------------------------------------------------------------------


def test_git_reports_failure_separately_from_empty_output(repo: Path, tmp_path: Path) -> None:
    """[MEASURED 2026-08-25] git diff HEAD over the source scopes ran 400 ms at
    best and 5,372 ms at worst against a 5,000 ms timeout, so the failure
    branch is reachable in ordinary operation -- and it used to be spelled
    exactly like success with no output."""
    ok = _common.git(repo, "status", "--porcelain")
    assert ok.ok is True and str(ok) == "", "a clean tree: ran, said nothing"

    not_a_repo = tmp_path / "elsewhere"
    not_a_repo.mkdir()
    bad = _common.git(not_a_repo, "status", "--porcelain")
    assert bad.ok is False, "a git that could not run must not look like a clean tree"
    assert str(bad) == ""
    assert not bad, "still falsy, so every existing caller behaves as before"


def test_an_unreadable_git_is_named_in_the_tree_line(repo: Path, monkeypatch) -> None:
    """A dropped dirty count and a dropped archive tag read as a clean,
    unarchived tree. That is the reading the 2026-08-22 incident punished."""
    from daedalus.hooks import _tree

    monkeypatch.setattr(_tree, "git", lambda *a, **k: _common.GitOut("", ok=False))
    facts = _tree.tree_facts(repo)
    assert facts.dirty_count == 0          # unchanged shape...
    line = facts.tree_line()
    assert "git unreadable" in line, "silence would claim a clean tree"
    assert "status" in line and "tag" in line
    assert "MISSING, not absent" in line


def test_an_unreadable_fingerprint_refuses_to_report_no_changes(repo: Path, monkeypatch) -> None:
    from daedalus.hooks import _tree

    monkeypatch.setattr(_tree, "git", lambda *a, **k: _common.GitOut("", ok=False))
    fp = _tree.source_fingerprint(repo)
    assert _tree.UNREADABLE_KEY in fp

    monkeypatch.setattr(events, "source_fingerprint", lambda _root: dict(fp))
    line = events._changed_line(repo, {"base_fp": {}})
    assert line, "an empty line here reads as 'nothing changed'"
    assert "cannot say" in line
    assert "NOT a report that the tree is unchanged" in line


def test_the_marker_never_shows_up_as_a_changed_source_file(repo: Path, monkeypatch) -> None:
    """The marker travels inside the fingerprint, so it must be excluded from
    the comparison or it would be reported as a source file that changed."""
    from daedalus.hooks import _tree

    stored = {"daedalus/x.py": "aaaa", _tree.UNREADABLE_KEY: "diff"}
    monkeypatch.setattr(events, "source_fingerprint", lambda _root: {"daedalus/x.py": "aaaa"})
    line = events._changed_line(repo, {"last_test": {"fp": stored, "at": "11:00", "cmd": "pytest"}})
    assert line == "", f"nothing changed, yet the hook said: {line!r}"


def test_with_deadline_gives_up_and_says_which_answer_that_is() -> None:
    """[MEASURED 2026-08-25] one turn row in the ledger reads 139,592 ms while
    every git call is capped at 5 s: the unbounded part was the Python side."""
    import time as _time

    assert _common.with_deadline(lambda: "fast", 5.0, "default") == "fast"
    assert _common.with_deadline(lambda: _time.sleep(30), 0.05, "gave-up") == "gave-up"
    # an exception is the caller's default too, not a crash in the turn
    assert _common.with_deadline(lambda: 1 / 0, 5.0, "gave-up") == "gave-up"


def test_a_hanging_clock_costs_the_budget_and_not_the_prompt(repo: Path, monkeypatch) -> None:
    import time as _time

    from daedalus import shift as shift_mod

    monkeypatch.setattr(events, "SHIFT_BUDGET_S", 0.05)
    monkeypatch.setattr(shift_mod, "load", lambda *a, **k: _time.sleep(30))
    started = _time.perf_counter()
    line = events._shift_line(repo)
    elapsed = _time.perf_counter() - started
    assert line == "[clock timed out]", "and NOT '[clock unavailable]' -- different failures"
    assert elapsed < 5.0, f"the prompt waited {elapsed:.1f}s for a hung dependency"
