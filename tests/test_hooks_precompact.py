"""Gate-0 regression tests for the canonical Hooks-v2 PreCompact path."""
from __future__ import annotations

import concurrent.futures
import datetime
import io
import json
import subprocess
from pathlib import Path

import pytest

from daedalus.hooks import __main__ as entry
from daedalus.hooks import _common, events


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = entry.start_effect()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
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


def _payload(repo: Path, **extra: object) -> dict:
    payload = {
        "session_id": "abcdef123456",
        "cwd": str(repo),
        "hook_event_name": "PreCompact",
        "transcript_path": "traces/session.jsonl",
    }
    payload.update(extra)
    return payload


def _run(repo: Path, **extra: object) -> tuple[_common.HookResult, str]:
    stdout = io.StringIO()
    result = entry.dispatch(
        "pre_compact",
        _payload(repo, **extra),
        RECEIPT,
        stdout=stdout,
    )
    return result, stdout.getvalue()


def test_every_project_hook_is_an_exact_registered_dispatch() -> None:
    settings = json.loads(
        (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
    )
    dispatcher = 'python "${CLAUDE_PROJECT_DIR}/daedalus/hooks/__main__.py"'
    expected = {
        "SessionStart": [f"{dispatcher} session"],
        "UserPromptSubmit": [f"{dispatcher} turn"],
        "PreToolUse": [f"{dispatcher} pre_tool"],
        "PostToolUse": [f"{dispatcher} post_tool"],
        "SubagentStart": [f"{dispatcher} subagent_start"],
        "SubagentStop": [f"{dispatcher} subagent_stop"],
        "ConfigChange": [f"{dispatcher} config_change"],
        "PreCompact": [f"{dispatcher} pre_compact"],
    }
    actual: dict[str, list[str]] = {}
    for event, groups in settings["hooks"].items():
        for group in groups:
            for hook in group["hooks"]:
                assert hook.get("type") == "command", (
                    f"project hook {event} must enter through the registered "
                    "command dispatcher"
                )
                actual.setdefault(event, []).append(hook["command"])

    assert actual == expected
    assert not (ROOT / ".claude" / "proposals" / "hook_precompact_vault.py").exists()


def test_documented_trigger_writes_marker_and_ledger_row(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime.datetime(2026, 8, 23, 16, 7)
    monkeypatch.setattr(events, "_local_now", lambda: fixed)

    result, stdout = _run(repo, trigger="manual")

    note = repo / "vault" / "Sessions" / "2026-08-23.md"
    text = note.read_text(encoding="utf-8")
    assert stdout == ""
    assert result.note == "precompact:manual"
    assert "[compaction:manual]" in text
    assert "Session abcdef12" in text
    assert "`traces/session.jsonl`" in text
    rows = [
        json.loads(line)
        for line in (_common.hooks_dir(repo) / "ledger.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert rows[-1]["event"] == "pre_compact"
    assert rows[-1]["note"] == "precompact:manual"
    assert rows[-1]["chars"] == 0


def test_legacy_trigger_appends_without_rewriting_existing_note(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime.datetime(2026, 8, 24, 9, 5)
    monkeypatch.setattr(events, "_local_now", lambda: fixed)
    sessions = repo / "vault" / "Sessions"
    sessions.mkdir()
    note = sessions / "2026-08-24.md"
    note.write_text("existing evidence\n", encoding="utf-8")

    result, stdout = _run(repo, compaction_trigger="auto")

    text = note.read_text(encoding="utf-8")
    assert stdout == ""
    assert result.note == "precompact:auto"
    assert text.startswith("existing evidence\n")
    assert text.count("[compaction:auto]") == 1
    assert "tags: [session]" not in text


def test_malformed_trigger_is_bounded_to_unknown(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed = datetime.datetime(2026, 8, 24, 9, 7)
    monkeypatch.setattr(events, "_local_now", lambda: fixed)

    result, stdout = _run(repo, trigger="] injected", compaction_trigger="auto")

    text = (repo / "vault" / "Sessions" / "2026-08-24.md").read_text(
        encoding="utf-8"
    )
    assert stdout == ""
    assert result.note == "precompact:unknown"
    assert "[compaction:unknown]" in text
    assert "] injected" not in text


def test_missing_vault_and_write_error_are_fail_open(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (repo / "vault").rmdir()
    missing, missing_stdout = _run(repo, trigger="auto")
    assert missing_stdout == ""
    assert missing.note == "precompact:vault-unavailable"

    (repo / "vault").mkdir()

    def refuse(*_args: object) -> None:
        raise PermissionError("read-only vault")

    monkeypatch.setattr(events, "_append_compaction_marker", refuse)
    refused, refused_stdout = _run(repo, trigger="manual")
    assert refused_stdout == ""
    assert refused.note == "precompact:write-failed:PermissionError"


def test_concurrent_daily_note_creation_writes_one_header(tmp_path: Path) -> None:
    note = tmp_path / "Sessions" / "2026-08-23.md"
    header = "---\ndate: 2026-08-23\n---\n\n"

    def append(index: int) -> None:
        events._append_compaction_marker(note, header, f"- marker {index}\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(append, range(8)))

    text = note.read_text(encoding="utf-8")
    assert text.count("date: 2026-08-23") == 1
    assert sum(line.startswith("- marker ") for line in text.splitlines()) == 8
    # The section heading is created by whichever appender first finds it
    # missing, and that decision is a read-modify-write under the same lock.
    # This header carries no section, so all eight threads race for it and
    # must still produce exactly ONE heading.
    assert text.count(events.COMPACTION_SECTION) == 1
    assert not note.with_name(f".{note.name}.precompact.lock").exists()
