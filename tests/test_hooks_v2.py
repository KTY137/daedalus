# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Tests for the hooks package (``daedalus/hooks``), hooks v2 (2026-08-23).

Every test builds its own throwaway git repository so no assertion depends on
this checkout's state. Tests that need THIS machine's settings files are
skipped elsewhere.
"""
from __future__ import annotations

import io
import json
import multiprocessing
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.hooks import __main__ as entry
from daedalus.hooks import _common, _tree, events, tools

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "daedalus").mkdir()
    (r / "daedalus" / "a.py").write_text("x = 1\n", encoding="utf-8")
    (r / "docs").mkdir()
    (r / "docs" / "d.md").write_text("# d\n", encoding="utf-8")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "init")
    return r


def payload(repo: Path, event: str, **extra) -> dict:
    base = {"session_id": "sess-1", "cwd": str(repo), "hook_event_name": event}
    base.update(extra)
    return base


RECEIPT = entry.start_effect()  # the real boundary, once per test module


def run(event: str, data: dict) -> tuple[_common.HookResult, str]:
    out = io.StringIO()
    result = entry.dispatch(event, data, RECEIPT, stdout=out)
    return result, out.getvalue()


# --------------------------------------------------------------------------
# stdin decoding
# --------------------------------------------------------------------------


def test_read_payload_decodes_harness_bytes_as_utf8_not_console_encoding() -> None:
    expected = {
        "hook_event_name": "SessionStart",
        "cwd": "C:/München🚀",
        "session_id": "utf8",
    }
    wire = json.dumps(expected, ensure_ascii=False).encode("utf-8")
    windows_stdin = io.TextIOWrapper(io.BytesIO(wire), encoding="cp1252")

    assert _common.read_payload(windows_stdin) == expected
    assert _common.read_payload(io.StringIO(json.dumps(expected, ensure_ascii=False))) == expected
    assert _common.read_payload(io.BytesIO(wire)) == expected
    assert _common.read_payload(io.StringIO("")) == {}
    assert _common.read_payload(io.StringIO("[1, 2]")) == {}
    assert _common.read_payload(io.BytesIO(b"\xff")) == {}
    assert _common.read_payload(io.BytesIO(b"\xef\xbb\xbf" + wire)) == {}
    assert _common.read_payload(io.StringIO("{not-json")) == {}


def test_read_payload_utf8_subprocess_ignores_pythonioencoding() -> None:
    expected = {
        "hook_event_name": "SessionStart",
        "cwd": "C:/München🚀",
        "session_id": "utf8",
    }
    wire = json.dumps(expected, ensure_ascii=False).encode("utf-8")
    script = (
        "import json; "
        "from daedalus.hooks._common import read_payload; "
        "print(json.dumps(read_payload(), ensure_ascii=True, sort_keys=True))"
    )
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "cp1252"

    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=wire,
        capture_output=True,
        cwd=ROOT,
        env=env,
    )

    assert proc.returncode == 0, proc.stderr.decode("ascii", errors="replace")
    assert json.loads(proc.stdout.decode("ascii")) == expected


# --------------------------------------------------------------------------
# repository root and session id
# --------------------------------------------------------------------------


def test_repo_root_is_the_git_toplevel_of_the_payload_cwd(repo: Path) -> None:
    sub = repo / "daedalus"
    assert _common.repo_root({"cwd": str(sub)}, env={}) == repo.resolve()


def test_repo_root_falls_back_to_claude_project_dir_then_cwd(repo: Path, tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _common.repo_root({"cwd": str(plain)}, env={"CLAUDE_PROJECT_DIR": str(repo)}) == repo.resolve()
    assert _common.repo_root({"cwd": str(plain)}, env={}) == plain.resolve()


def test_repo_root_never_uses_the_package_location(repo: Path) -> None:
    # The archived-tree bug: hooks resolved from __file__. Given a foreign cwd
    # the answer must be that cwd's repo, not this checkout.
    assert _common.repo_root({"cwd": str(repo)}, env={}) != ROOT


@pytest.mark.parametrize("bad", ["../../x", "a/b", "", None, 5, "x" * 65, "..\\..\\evil"])
def test_session_id_is_sanitised_against_path_traversal(bad) -> None:
    assert _common.safe_session_id(bad) == "unknown"
    assert _common.safe_session_id("9f6dc8d1-191f-412c-ba99-83b0a520c9cc") == "9f6dc8d1-191f-412c-ba99-83b0a520c9cc"


# --------------------------------------------------------------------------
# state, locking, ledger
# --------------------------------------------------------------------------


def _bump(args) -> None:
    root, sid, n = args
    for _ in range(n):
        _common.update_state(Path(root), sid, lambda s: s.__setitem__("n", s.get("n", 0) + 1))


def test_update_state_is_atomic_under_eight_concurrent_processes(repo: Path) -> None:
    with multiprocessing.Pool(8) as pool:
        pool.map(_bump, [(str(repo), "race", 25)] * 8)
    assert _common.load_state(repo, "race")["n"] == 200


def test_update_state_survives_a_stale_lock(repo: Path) -> None:
    path = _common.state_path(repo, "s")
    path.parent.mkdir(parents=True)
    lock = path.with_name(path.name + ".lock")
    lock.write_text("dead")
    old = 1_000
    os.utime(lock, (old, old))
    state = _common.update_state(repo, "s", lambda s: s.__setitem__("k", 1))
    assert state == {"k": 1}
    assert not lock.exists()


def test_ledger_appends_and_rotates(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(_common, "LEDGER_MAX_BYTES", 200)
    for i in range(20):
        _common.ledger_append(repo, {"i": i, "pad": "x" * 30})
    d = _common.hooks_dir(repo)
    assert (d / "ledger.jsonl").exists()
    assert (d / "ledger.jsonl.1").exists()
    rows = [json.loads(l) for l in (d / "ledger.jsonl").read_text().splitlines()]
    assert rows[-1]["i"] == 19


def test_trim_drops_from_the_bottom_and_reports_it() -> None:
    text, trimmed = _common.trim_to_budget(["a" * 50, "b" * 50, "c" * 50], cap=110)
    assert text == "a" * 50 + "\n" + "b" * 50
    assert trimmed is True
    assert _common.trim_to_budget(["ok"], cap=10) == ("ok", False)


# --------------------------------------------------------------------------
# tree facts
# --------------------------------------------------------------------------


def test_serena_root_mismatch_reads_mcp_json(repo: Path, tmp_path: Path) -> None:
    assert _tree.serena_root_mismatch(repo) is None  # no .mcp.json: fail open
    other = tmp_path / "other"
    other.mkdir()
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["start", "--project", str(other)]}}})
    )
    assert _tree.serena_root_mismatch(repo) == other
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["start", f"--project={repo}"]}}})
    )
    assert _tree.serena_root_mismatch(repo) is None


def test_archived_tag_matches_head_or_branch_tail(repo: Path) -> None:
    assert _tree.archived_tag(repo) == ""
    _git(repo, "tag", "archive/checkpoint-x")
    assert _tree.archived_tag(repo) == "archive/checkpoint-x"
    _git(repo, "checkout", "-q", "-b", "checkpoint/checkpoint-x")
    (repo / "later.txt").write_text("later")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-q", "-m", "later")  # HEAD moved past the tag
    assert _tree.archived_tag(repo) == "archive/checkpoint-x"


def test_session_card_is_deterministic_and_ascii(repo: Path) -> None:
    (repo / ".claude" / "watchdog" / "docs").mkdir(parents=True)
    (repo / ".claude" / "watchdog" / "docs" / "sweeps.log").write_text(
        f"2026-08-23T11:46:52Z HEAD={_git(repo, 'rev-parse', '--short=8', 'HEAD')} changed=4 commit=x note=y\n"
    )
    a, out_a = run("session", payload(repo, "SessionStart", source="startup"))
    b, out_b = run("session", payload(repo, "SessionStart", source="compact"))
    strip = lambda s: re.sub(r"SHIFT: \[\d\d:\d\d\]", "SHIFT: [hh:mm]", s)
    assert strip(out_a) == strip(out_b)
    assert out_a.startswith("TREE: repo | main @")
    assert "DOCS: last mnemosyne sweep at" in out_a
    assert "HOOKS v2: silence = unchanged" in out_a
    assert all(ord(ch) < 128 for ch in out_a), out_a
    assert len(out_a) < 600


def test_dirty_summary_keeps_the_first_lines_leading_space(repo: Path) -> None:
    # " M daedalus/a.py" is the FIRST porcelain line; a strip() of the whole
    # output once turned it into "M daedalus/a.py" and the top dir into "aedalus".
    (repo / "daedalus" / "a.py").write_text("x = 2" + chr(10), encoding="utf-8")
    count, dirs = _tree.dirty_summary(repo)
    assert count == 1 and dirs == ("daedalus",)


def test_session_card_names_an_archived_tree(repo: Path) -> None:
    _git(repo, "tag", "archive/old-line")
    _, out = run("session", payload(repo, "SessionStart"))
    assert "ARCHIVED TREE (archive/old-line)" in out


# --------------------------------------------------------------------------
# turn
# --------------------------------------------------------------------------


def test_turn_is_silent_about_unchanged_architecture(repo: Path) -> None:
    # no architecture memory in a throwaway repo: no ARCH line at all
    _, out = run("turn", payload(repo, "UserPromptSubmit", user_input="x"))
    assert "ARCHITECTURE" not in out
    assert re.match(r"\[\d\d:\d\d\] no shift declared", out)


def test_crew_count_comes_from_subagent_lifecycle_and_targets_show_once(repo: Path) -> None:
    run("session", payload(repo, "SessionStart"))
    _, t1 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CREW: 0 subagents live (hook-tracked, min 4)" in t1
    assert "where work goes (shown once)" in t1
    run("subagent_start", payload(repo, "SubagentStart", agent_id="a1", agent_type="argus"))
    run("subagent_start", payload(repo, "SubagentStart", agent_id="a2", agent_type="kadmos"))
    _, t2 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CREW: 2 subagents live (hook-tracked, min 4): argus, kadmos" in t2
    assert "where work goes" not in t2
    run("subagent_stop", payload(repo, "SubagentStop", agent_id="a1", agent_type="argus"))
    _, t3 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CREW: 1 subagents live" in t3
    for aid in ("b1", "b2", "b3", "b4"):
        run("subagent_start", payload(repo, "SubagentStart", agent_id=aid, agent_type="x"))
    _, t4 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CREW: 5 subagents live" in t4  # changed -> shown
    _, t5 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CREW" not in t5  # at/above minimum and unchanged -> silence


def test_turn_never_scans_the_temp_tree(repo: Path, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(Path, "rglob", lambda self, *a, **k: calls.append(a) or iter(()))
    run("turn", payload(repo, "UserPromptSubmit"))
    assert calls == []


def test_changed_line_uses_fingerprints_not_edit_tracking(repo: Path) -> None:
    run("session", payload(repo, "SessionStart"))
    _, t0 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED" not in t0
    # an edit made by ANY process (here: plain write, i.e. a Serena/Bash write)
    (repo / "daedalus" / "a.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _, t1 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED since session start, no test run recorded: 1 source files -- daedalus/a.py" in t1
    # a docs edit is not a source change
    (repo / "docs" / "d.md").write_text("# dd\n")
    _, t2 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "1 source files" in t2
    # a successful test run records the fingerprint ...
    run("post_tool", payload(repo, "PostToolUse", tool_name="Bash", tool_input={"command": "python -m pytest tests/test_x.py -q"}))
    _, t3 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED" not in t3
    # ... and a later edit is reported against THAT run, naming the command
    (repo / "daedalus" / "b.py").write_text("z = 3\n", encoding="utf-8")
    _, t4 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED since last test run (" in t4 and "`python -m pytest tests/test_x.py -q`" in t4
    assert "daedalus/b.py" in t4


@pytest.mark.parametrize("command", ["pytest -q", "uv run pytest -q"])
def test_powershell_test_run_records_the_same_fingerprint_and_delta(repo: Path, command: str) -> None:
    run("session", payload(repo, "SessionStart"))
    (repo / "daedalus" / "a.py").write_text("x = 2\n", encoding="utf-8")
    result, out = run(
        "post_tool",
        payload(repo, "PostToolUse", tool_name="PowerShell", tool_input={"command": command}),
    )
    assert out == "" and result.note == "test-run-recorded"
    state = _common.load_state(repo, "sess-1")
    assert state["last_test"]["cmd"] == command
    assert state["last_test"]["fp"] == _tree.source_fingerprint(repo)

    (repo / "daedalus" / "b.py").write_text("z = 3\n", encoding="utf-8")
    _, turn = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED since last test run" in turn
    assert f"`{command}`" in turn and "daedalus/b.py" in turn


@pytest.mark.parametrize(
    "command,is_test",
    [
        ("pytest -q", True),
        ("python -m pytest tests -q", True),
        ("python3 -m unittest discover", True),
        ("uv run pytest -q", True),
        ("uv.exe run python -m pytest tests -q", True),
        ("cd C:/x && python -m pytest", True),
        ("cd C:/x; uv run pytest", True),
        ("echo pytest", False),
        ("echo uv run pytest", False),
        ("grep -rn pytest tests", False),
        ("uv runner pytest", False),
        ("uv run pytestx", False),
        ("pytest || true", True),  # a partial/guarded run is recorded WITH its command text
        ("git commit -m 'pytest fixed'", False),
        ('cd "C:/path with spaces" && pytest -q', True),
        ("cd 'x y'; py -m pytest", True),
        ("PYTEST tests", True),
        ("pytestx", False),
    ],
)
def test_test_command_recognition(command: str, is_test: bool) -> None:
    assert bool(tools.TEST_COMMAND.search(command)) is is_test


@pytest.mark.parametrize("tool_name", ["Bash", "PowerShell"])
def test_commit_triggers_the_docs_drift_reminder_only_on_real_commits(repo: Path, tool_name: str) -> None:
    def post(command: str) -> str:
        _, stdout = run(
            "post_tool",
            payload(repo, "PostToolUse", tool_name=tool_name, tool_input={"command": command}),
        )
        return stdout

    out = post("git commit -F msg.txt")
    assert json.loads(out)["hookSpecificOutput"]["additionalContext"].startswith("A commit just landed")
    assert post("git commit --dry-run") == ""
    assert post("git log --oneline") == ""


def test_post_tool_ignores_non_shell_tools_even_when_input_looks_like_a_test(repo: Path) -> None:
    result, out = run(
        "post_tool",
        payload(repo, "PostToolUse", tool_name="Read", tool_input={"command": "pytest -q"}),
    )
    assert out == "" and result.note == ""
    assert _common.load_state(repo, "sess-1") == {}


def test_config_change_is_reported_on_the_next_turn_once(repo: Path) -> None:
    run("config_change", payload(repo, "ConfigChange", config_source="user_settings", config_path="~/.claude/settings.json"))
    _, t1 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CONFIG changed during this session: user_settings (~/.claude/settings.json)" in t1
    _, t2 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CONFIG" not in t2


# --------------------------------------------------------------------------
# pre_tool: serena routing and the wrong-tree write guard
# --------------------------------------------------------------------------


def _serena_up(monkeypatch, up: bool) -> None:
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: up)


def test_routing_does_not_nudge_into_a_server_indexing_another_tree(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    """Reachability is not correctness.

    Cerberus/Momus 2026-08-25: the routing branch gated on serena_is_reachable
    alone, so a server rooted at a DIFFERENT tree was still declared in force
    and Grep/Read were steered into it. The answers would describe another
    repository. Fail open to the native tools instead.
    """
    _serena_up(monkeypatch, True)
    monkeypatch.setenv("DAEDALUS_SERENA_HOOK", "deny")
    call = payload(repo, "PreToolUse", tool_name="Grep", tool_input={"pattern": "def build_wave"})

    # same tree -> the routing rule applies as before
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["--project", str(repo)]}}})
    )
    _, out = run("pre_tool", call)
    assert out != "", "routing must still fire when the server indexes THIS tree"

    # other tree -> no nudge at all
    other = tmp_path / "dead_tree"
    other.mkdir()
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["--project", str(other)]}}})
    )
    _, out = run("pre_tool", call)
    assert out == "", "a mismatched root must not be routed into, not even as advice"


def test_serena_write_tool_is_denied_only_on_root_mismatch(repo: Path, tmp_path: Path, monkeypatch) -> None:
    _serena_up(monkeypatch, True)
    call = payload(repo, "PreToolUse", tool_name="mcp__serena__replace_symbol_body", tool_input={"name_path": "f"})
    _, out = run("pre_tool", call)
    assert out == ""  # no .mcp.json: fail open
    other = tmp_path / "archived"
    other.mkdir()
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"serena": {"args": ["--project", str(other)]}}}))
    _, out = run("pre_tool", call)
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "incident 2026-08-22" in decision["permissionDecisionReason"]
    # read tools pass even on mismatch
    _, out = run("pre_tool", payload(repo, "PreToolUse", tool_name="mcp__serena__find_symbol", tool_input={"name_path": "f"}))
    assert out == ""
    # the guard does not depend on the routing mode
    monkeypatch.setenv("DAEDALUS_SERENA_HOOK", "off")
    _, out = run("pre_tool", call)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_serena_advise_allows_the_read_and_nudges_once(repo: Path, monkeypatch) -> None:
    _serena_up(monkeypatch, True)
    monkeypatch.delenv("DAEDALUS_SERENA_HOOK", raising=False)
    big = repo / "daedalus" / "big.py"
    big.write_text("\n".join(f"x{i} = {i}" for i in range(200)), encoding="utf-8")
    call = payload(repo, "PreToolUse", tool_name="Read", tool_input={"file_path": str(big)})
    _, out = run("pre_tool", call)
    spec = json.loads(out)["hookSpecificOutput"]
    assert "permissionDecision" not in spec  # the Read proceeds
    assert "get_symbols_overview" in spec["additionalContext"]
    _, out2 = run("pre_tool", call)
    assert out2 == ""  # once per file per session
    # targeted reads and small files never nudge
    _, out3 = run("pre_tool", payload(repo, "PreToolUse", tool_name="Read", tool_input={"file_path": str(big), "offset": 1, "limit": 5}))
    assert out3 == ""
    _, out4 = run("pre_tool", payload(repo, "PreToolUse", tool_name="Read", tool_input={"file_path": str(repo / "daedalus" / "a.py")}))
    assert out4 == ""


def test_transcript_mentions_counts_tool_calls_not_tool_lists(tmp_path: Path) -> None:
    t = tmp_path / "transcript.jsonl"
    # the first user turn: deferred tool list + the prompt naming the file, one line
    first = json.dumps({"type": "user", "message": "tools: mcp__serena__find_symbol ... please read daedalus/spine/attempt.py"})
    t.write_text(first + chr(10), encoding="utf-8")
    assert tools.transcript_mentions(str(t), "attempt.py") is False
    call = json.dumps({"type": "assistant", "content": [{"type": "tool_use", "name": "mcp__serena__get_symbols_overview", "input": {"relative_path": "daedalus/spine/attempt.py"}}]})
    with t.open("a", encoding="utf-8") as fh:
        fh.write(call + chr(10))
    assert tools.transcript_mentions(str(t), "attempt.py") is True


def test_serena_deny_mode_restores_amendment_003(repo: Path, monkeypatch) -> None:
    _serena_up(monkeypatch, True)
    monkeypatch.setenv("DAEDALUS_SERENA_HOOK", "deny")
    _, out = run("pre_tool", payload(repo, "PreToolUse", tool_name="Grep", tool_input={"pattern": "def main"}))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_serena_routing_is_silent_when_serena_is_down(repo: Path, monkeypatch) -> None:
    _serena_up(monkeypatch, False)
    monkeypatch.setenv("DAEDALUS_SERENA_HOOK", "deny")
    r, out = run("pre_tool", payload(repo, "PreToolUse", tool_name="Grep", tool_input={"pattern": "class Foo"}))
    assert out == "" and r.note == "serena-unreachable"


# --------------------------------------------------------------------------
# subagents
# --------------------------------------------------------------------------


def test_subagent_start_hands_the_tree_card_to_the_subagent(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "archived"
    other.mkdir()
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"serena": {"args": ["--project", str(other)]}}}))
    _, out = run("subagent_start", payload(repo, "SubagentStart", agent_id="a9", agent_type="kadmos"))
    ctx = json.loads(out)["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SubagentStart"
    assert ctx["additionalContext"].startswith("TREE: repo | main @")
    assert "Serena WRITE tools denied" in ctx["additionalContext"]
    assert "Serena read tools only" in ctx["additionalContext"]


# --------------------------------------------------------------------------
# protocol: never break a turn
# --------------------------------------------------------------------------


def test_malformed_stdin_and_unknown_event_exit_zero_and_print_nothing(repo: Path) -> None:
    stale = _common.hooks_dir(ROOT) / "state-unknown.json"
    if stale.exists():
        stale.unlink()  # left by runs before the payload gate existed; this test owns the check
    for raw in ["", "not json", "[1,2]", "{\"cwd\": 5}", "{}"]:
        proc = subprocess.run(
            [sys.executable, "-m", "daedalus.hooks", "turn"], input=raw, capture_output=True, text=True, cwd=str(ROOT)
        )
        assert proc.returncode == 0, proc.stderr
        assert proc.stdout == "", (raw, proc.stdout)
    assert not (_common.hooks_dir(ROOT) / "state-unknown.json").exists()
    r, out = run("turn", {"cwd": str(repo)})  # no hook_event_name: not a harness call
    assert out == "" and r.note == "unusable-payload"
    assert not _common.state_path(repo, "unknown").exists()
    r, out = run("no_such_event", payload(repo, "X"))
    assert out == "" and r.note.startswith("unknown-event")


def test_dispatch_refuses_to_run_without_the_effect_receipt(repo: Path) -> None:
    with pytest.raises(PermissionError):
        entry.dispatch("turn", payload(repo, "UserPromptSubmit"), None, stdout=io.StringIO())

    class Forged:
        entrypoint_id = "cli.loop"

    with pytest.raises(PermissionError):
        entry.dispatch("turn", payload(repo, "UserPromptSubmit"), Forged(), stdout=io.StringIO())


def test_render_delta_confines_the_cursor_to_the_repository(repo: Path, tmp_path: Path) -> None:
    from daedalus import arch_memory

    outside = tmp_path / "elsewhere.shown"
    with pytest.raises(ValueError):
        arch_memory.render_delta(repo, shown_path=outside)
    assert not outside.exists()


def test_changed_detects_same_line_count_edits_after_a_test_run(repo: Path) -> None:
    run("session", payload(repo, "SessionStart"))
    (repo / "daedalus" / "a.py").write_text("x = 2" + chr(10), encoding="utf-8")
    run("post_tool", payload(repo, "PostToolUse", tool_name="Bash", tool_input={"command": "pytest -q"}))
    _, quiet = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED" not in quiet
    (repo / "daedalus" / "a.py").write_text("x = 3" + chr(10), encoding="utf-8")  # same numstat, new bytes
    _, loud = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CHANGED since last test run" in loud and "daedalus/a.py" in loud


def test_turn_is_quiet_before_the_watchdog_has_health_evidence(repo: Path) -> None:
    _, turn = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in turn
    assert "last_watchdog" not in _common.load_state(repo, "sess-1")

    health = repo / "runs" / "watchdog" / "health.json"
    health.parent.mkdir(parents=True)
    health.write_text(json.dumps({"anomalies": []}), encoding="utf-8")
    _, first_valid_clear = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in first_valid_clear
    assert _common.load_state(repo, "sess-1")["last_watchdog"] == []


def test_turn_shows_watchdog_anomalies_only_when_they_change(repo: Path) -> None:
    health = repo / "runs" / "watchdog" / "health.json"
    health.parent.mkdir(parents=True)
    health.write_text(json.dumps({"anomalies": [{"id": "docs_sweep_stale", "message": "m"}]}), encoding="utf-8")
    _, t1 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG: docs_sweep_stale (runs/watchdog/HEALTH.md)" in t1
    _, t2 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in t2

    health.unlink()
    _, missing = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in missing
    assert _common.load_state(repo, "sess-1")["last_watchdog"] == ["docs_sweep_stale"]

    health.write_text("{invalid", encoding="utf-8")
    _, invalid = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in invalid
    assert _common.load_state(repo, "sess-1")["last_watchdog"] == ["docs_sweep_stale"]

    health.write_bytes(b"{\"anomalies\":[\xff]}")
    _, invalid_utf8 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in invalid_utf8
    assert _common.load_state(repo, "sess-1")["last_watchdog"] == ["docs_sweep_stale"]

    health.write_text(json.dumps({"anomalies": []}), encoding="utf-8")
    _, t3 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG: all clear" in t3
    _, t4 = run("turn", payload(repo, "UserPromptSubmit"))
    assert "WATCHDOG" not in t4


def test_config_change_accepts_both_field_spellings(repo: Path) -> None:
    run("config_change", payload(repo, "ConfigChange", source="project_settings", file_path="x/.claude/settings.json"))
    _, t = run("turn", payload(repo, "UserPromptSubmit"))
    assert "CONFIG changed during this session: project_settings (x/.claude/settings.json)" in t


def _break_stale(args) -> int:
    root, sid = args
    try:
        _common.update_state(Path(root), sid, lambda s: s.__setitem__("n", s.get("n", 0) + 1))
        return 1
    except Exception:  # noqa: BLE001
        return 0


def test_concurrent_stale_lock_breaking_loses_no_update(repo: Path) -> None:
    path = _common.state_path(repo, "stale")
    path.parent.mkdir(parents=True)
    lock = path.with_name(path.name + ".lock")
    lock.write_text("dead")
    os.utime(lock, (1_000, 1_000))
    with multiprocessing.Pool(6) as pool:
        ok = sum(pool.map(_break_stale, [(str(repo), "stale")] * 6))
    assert ok == 6
    assert _common.load_state(repo, "stale")["n"] == 6
    assert not lock.exists()


def test_handler_exception_is_swallowed_into_the_ledger(repo: Path, monkeypatch) -> None:
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setitem(entry.HANDLERS, "turn", boom)
    r, out = run("turn", payload(repo, "UserPromptSubmit"))
    assert out == "" and r.note.startswith("error:RuntimeError")
    rows = [json.loads(l) for l in (_common.hooks_dir(repo) / "ledger.jsonl").read_text().splitlines()]
    assert rows[-1]["event"] == "turn" and "kaboom" in rows[-1]["note"]


def test_every_invocation_writes_a_ledger_row_with_chars_and_ms(repo: Path) -> None:
    run("session", payload(repo, "SessionStart"))
    run("turn", payload(repo, "UserPromptSubmit"))
    rows = [json.loads(l) for l in (_common.hooks_dir(repo) / "ledger.jsonl").read_text().splitlines()]
    assert [r["event"] for r in rows] == ["session", "turn"]
    assert all({"ts", "session", "prompt", "event", "chars", "ms", "note"} <= set(r) for r in rows)
    assert rows[0]["chars"] > 0


# --------------------------------------------------------------------------
# effect boundary and registration
# --------------------------------------------------------------------------


def test_hooks_entrypoint_is_registered_and_starts_centrally() -> None:
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, Effect, Wiring

    row = REGISTRY_BY_ID["daedalus.hooks"]
    assert row.wiring is Wiring.CENTRAL
    assert {Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS} <= set(row.effects)
    proc = subprocess.run(
        [sys.executable, "-m", "daedalus.hooks", "turn"], input="{}", capture_output=True, text=True, cwd=str(ROOT)
    )
    assert proc.returncode == 0 and "effect boundary" not in proc.stderr, proc.stderr


def test_project_settings_register_the_dispatcher_repo_relative() -> None:
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings["hooks"]
    commands = [h["command"] for entries in hooks.values() for e in entries for h in e["hooks"]]
    assert any("daedalus/hooks" in c and "${CLAUDE_PROJECT_DIR}" in c for c in commands)
    assert not any("agent_env/" in c or "agent_env\\" in c for c in commands)
    for required in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "SubagentStart", "SubagentStop"):
        assert required in hooks, required
    assert [entry.get("matcher") for entry in hooks["PostToolUse"]] == ["Bash|PowerShell"]
    assert "Stop" not in hooks  # v2 never blocks a stop and has nothing to say there


@pytest.mark.skipif(
    not (Path.home() / ".claude" / "settings.json").exists(), reason="this machine's user settings only"
)
def test_no_archived_tree_paths_in_the_effective_hook_union() -> None:
    """Codex W5: the user-settings migration is an acceptance gate, not a hope."""
    user = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
    commands = [
        h.get("command", "")
        for entries in (user.get("hooks") or {}).values()
        for e in entries
        for h in e.get("hooks", [])
    ]
    archived = [c for c in commands if "Desktop/agent_env/" in c.replace("\\", "/")]
    assert archived == [], archived
