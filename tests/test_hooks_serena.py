"""Serena on every prompt (2026-09-06).

Owner order: "richte hooks so ein das wir konstant SERENA benutzen am besten
jeder prompt brauch ein serena hook". These tests pin the behaviour of the
Serena strand of the hooks package: the configured-root reading of
``--project-from-cwd``, the SERENA line on the session card, on EVERY turn and
on the subagent card, the usage tracking that turns the line from "load the
tools" into "N calls so far", the prompt-derived hints, the native-burst
advisory and the symbol-edit advisory.

Nothing here denies a read. AGENTS.md classes a guard that blocks reading or
measuring as a release-blocking defect, and the upstream ``serena-hooks
remind`` command (a deny after three greps) was measured and rejected for
exactly that reason -- see docs/superpowers/specs/2026-09-06-serena-hooks-design.md.

Every test builds its own throwaway git repository; Serena's reachability is
a monkeypatched seam so no test opens a socket.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest

from daedalus.hooks import __main__ as entry
from daedalus.hooks import _common, _tree, serena, tools

# --------------------------------------------------------------------------
# fixtures (same shape as tests/test_hooks_v2.py)
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


@pytest.fixture
def serena_repo(repo: Path, monkeypatch) -> Path:
    """A repository whose ``.mcp.json`` starts Serena with ``--project-from-cwd``
    (the general configuration adopted 2026-09-06) and whose Serena answers."""
    (repo / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "serena": {
                        "command": "serena",
                        "args": [
                            "start-mcp-server",
                            "--context",
                            "claude-code",
                            "--project-from-cwd",
                            "--open-web-dashboard",
                            "false",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: True)
    monkeypatch.delenv("DAEDALUS_SERENA_HOOK", raising=False)
    return repo


def payload(repo: Path, event: str, **extra) -> dict:
    base = {"session_id": "sess-serena", "cwd": str(repo), "hook_event_name": event}
    base.update(extra)
    return base


RECEIPT = entry.start_effect()


def run(event: str, data: dict) -> tuple[_common.HookResult, str]:
    out = io.StringIO()
    result = entry.dispatch(event, data, RECEIPT, stdout=out)
    return result, out.getvalue()


def state_of(repo: Path) -> dict:
    return _common.load_state(repo, "sess-serena")


# --------------------------------------------------------------------------
# configured root: --project-from-cwd is THIS tree
# --------------------------------------------------------------------------


def test_project_from_cwd_counts_as_this_tree(serena_repo: Path) -> None:
    """``--project-from-cwd`` roots Serena at the nearest .git/.serena ancestor
    of the cwd Claude Code launched it in -- the session's own tree. Before
    this the reader knew only ``--project <path>`` and reported "not
    configured" for the general form, so the write guard and the routing
    both fell open."""
    assert _tree.serena_configured_root(serena_repo) == serena_repo
    assert _tree.serena_root_mismatch(serena_repo) is None
    assert "configured serena root: this tree" in _tree.tree_facts(serena_repo).tree_line()


def test_project_arg_expands_environment_variables(repo: Path, monkeypatch) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(repo))
    (repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["--project", "${CLAUDE_PROJECT_DIR}"]}}}),
        encoding="utf-8",
    )
    assert _tree.serena_configured_root(repo) == repo
    assert _tree.serena_root_mismatch(repo) is None


def test_language_servers_read_from_project_yml(repo: Path) -> None:
    """The first Serena start on this tree auto-created ``.serena/project.yml``
    with ``language_servers: []`` (measured 2026-09-06): a blind index. The
    session card must be able to say so."""
    assert _tree.serena_language_servers(repo) is None  # no file
    d = repo / ".serena"
    d.mkdir()
    (d / "project.yml").write_text("project_name: repo\nlanguage_servers: []\n", encoding="utf-8")
    assert _tree.serena_language_servers(repo) == []
    (d / "project.yml").write_text(
        'project_name: repo\nlanguage_servers: ["python", "typescript", "rust"]\n', encoding="utf-8"
    )
    assert _tree.serena_language_servers(repo) == ["python", "typescript", "rust"]
    (d / "project.yml").write_text(
        "project_name: repo\nlanguage_servers:\n  - python\n  - rust\nencoding: utf-8\n", encoding="utf-8"
    )
    assert _tree.serena_language_servers(repo) == ["python", "rust"]


# --------------------------------------------------------------------------
# session card
# --------------------------------------------------------------------------


def test_session_card_carries_serena_line_with_load_instruction(serena_repo: Path) -> None:
    _, out = run("session", payload(serena_repo, "SessionStart", source="startup"))
    line = next(l for l in out.splitlines() if l.startswith("SERENA:"))
    assert "this tree" in line
    assert "ToolSearch" in line and "mcp__serena__find_symbol" in line
    assert len(line) <= serena.SESSION_LINE_CAP


def test_session_card_warns_about_a_blind_project_yml(serena_repo: Path) -> None:
    d = serena_repo / ".serena"
    d.mkdir()
    (d / "project.yml").write_text("project_name: repo\nlanguage_servers: []\n", encoding="utf-8")
    _, out = run("session", payload(serena_repo, "SessionStart", source="startup"))
    assert "language_servers" in out and "blind" in out
    (d / "project.yml").write_text('language_servers: ["python"]\n', encoding="utf-8")
    _, out2 = run("session", payload(serena_repo, "SessionStart", source="resume"))
    assert "blind" not in out2
    assert "python" in next(l for l in out2.splitlines() if l.startswith("SERENA:"))


# --------------------------------------------------------------------------
# the turn line: every prompt, adapting to what happened
# --------------------------------------------------------------------------


def test_turn_line_on_every_prompt_and_after_serena_use(serena_repo: Path) -> None:
    _, out = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="hi"))
    first = next(l for l in out.splitlines() if l.startswith("SERENA:"))
    assert "ToolSearch" in first, "tools are deferred: the first thing to say is how to load them"
    # a Serena call succeeded -> the line reports usage instead of the load instruction
    run(
        "post_tool",
        payload(
            serena_repo,
            "PostToolUse",
            tool_name="mcp__serena__find_symbol",
            tool_input={"name_path": "f"},
            tool_response={"ok": True},
        ),
    )
    _, out2 = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="hi again"))
    second = next(l for l in out2.splitlines() if l.startswith("SERENA:"))
    assert "1 call" in second and "find_symbol" in second
    assert "ToolSearch" not in second
    # still one line per prompt, still under its own cap
    _, out3 = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="third"))
    assert sum(1 for l in out3.splitlines() if l.startswith("SERENA:")) == 1
    assert all(len(l) <= serena.TURN_LINE_CAP for l in out3.splitlines() if l.startswith("SERENA:"))


def test_turn_line_comes_right_after_the_clock(serena_repo: Path) -> None:
    """Trimming drops from the END. A line the owner wants on every prompt has
    to sit where trimming never reaches it: second, behind the shift clock."""
    _, out = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="x"))
    lines = out.splitlines()
    assert lines[1].startswith("SERENA:"), lines


def test_tool_search_loading_serena_counts_as_loaded(serena_repo: Path) -> None:
    run(
        "post_tool",
        payload(
            serena_repo,
            "PostToolUse",
            tool_name="ToolSearch",
            tool_input={"query": "select:mcp__serena__find_symbol,mcp__serena__get_symbols_overview"},
            tool_response={"ok": True},
        ),
    )
    _, out = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="go"))
    line = next(l for l in out.splitlines() if l.startswith("SERENA:"))
    assert "ToolSearch" not in line and "loaded" in line


def test_turn_line_says_when_serena_is_down_or_elsewhere(serena_repo: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: False)
    _, out = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="x"))
    line = next(l for l in out.splitlines() if l.startswith("SERENA:"))
    assert "not answering" in line and "native" in line
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: True)
    other = tmp_path / "elsewhere"
    other.mkdir()
    (serena_repo / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"serena": {"args": ["--project", str(other)]}}}), encoding="utf-8"
    )
    _, out2 = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="x"))
    line2 = next(l for l in out2.splitlines() if l.startswith("SERENA:"))
    assert "!= this tree" in line2 and "denied" in line2
    (serena_repo / ".mcp.json").unlink()
    _, out3 = run("turn", payload(serena_repo, "UserPromptSubmit", prompt="x"))
    line3 = next(l for l in out3.splitlines() if l.startswith("SERENA:"))
    assert "not configured" in line3 and "--project-from-cwd" in line3


def test_prompt_hints_name_the_exact_serena_calls(serena_repo: Path) -> None:
    prompt = "please look at daedalus/a.py and fix pre_tool( so that MissingThing works"
    hints = serena.prompt_hints(prompt, serena_repo)
    assert 'get_symbols_overview("daedalus/a.py")' in hints
    assert 'find_symbol("pre_tool")' in hints
    assert 'find_symbol("MissingThing")' in hints
    # a path that does not exist in this tree is not suggested
    assert not any("nope.py" in h for h in serena.prompt_hints("see nope.py", serena_repo))
    # and the hints reach the turn line
    _, out = run("turn", payload(serena_repo, "UserPromptSubmit", prompt=prompt))
    line = next(l for l in out.splitlines() if l.startswith("SERENA:"))
    assert 'get_symbols_overview("daedalus/a.py")' in line
    assert len(line) <= serena.TURN_LINE_CAP


# --------------------------------------------------------------------------
# subagents get the line too
# --------------------------------------------------------------------------


def test_subagent_card_carries_the_serena_line(serena_repo: Path) -> None:
    _, out = run("subagent_start", payload(serena_repo, "SubagentStart", agent_id="a1", agent_type="argus"))
    ctx = json.loads(out)["hookSpecificOutput"]["additionalContext"]
    assert "SERENA:" in ctx and "mcp__serena__find_symbol" in ctx
    assert len(ctx) <= 600


# --------------------------------------------------------------------------
# native-burst advisory: an advice, never a deny
# --------------------------------------------------------------------------


def test_three_native_code_lookups_in_a_row_advise_once(serena_repo: Path, monkeypatch) -> None:
    clock = [1000.0]
    monkeypatch.setattr(serena, "_now", lambda: clock[0])
    grep = payload(serena_repo, "PreToolUse", tool_name="Grep", tool_input={"pattern": "TODO"})
    small = payload(
        serena_repo, "PreToolUse", tool_name="Read", tool_input={"file_path": str(serena_repo / "daedalus" / "a.py")}
    )
    _, o1 = run("pre_tool", grep)
    _, o2 = run("pre_tool", small)
    assert o1 == "" and o2 == "", "below the threshold nothing is said"
    r3, o3 = run("pre_tool", grep)
    spec = json.loads(o3)["hookSpecificOutput"]
    assert "permissionDecision" not in spec, "an advice, never a deny (AGENTS.md review rule)"
    assert "in a row" in spec["additionalContext"] and "find_symbol" in spec["additionalContext"]
    assert r3.note == "serena-burst-advise"
    # within the quiet window the counter keeps counting but says nothing
    for _ in range(3):
        _, o = run("pre_tool", grep)
        assert o == ""
    # a Serena call resets the burst
    run(
        "post_tool",
        payload(serena_repo, "PostToolUse", tool_name="mcp__serena__get_symbols_overview", tool_input={}, tool_response={}),
    )
    assert state_of(serena_repo)["serena"]["burst"] == 0
    # after the window a fresh burst is advised again
    clock[0] += serena.BURST_QUIET_S + 1
    for _ in range(2):
        run("pre_tool", grep)
    _, o7 = run("pre_tool", grep)
    assert "in a row" in json.loads(o7)["hookSpecificOutput"]["additionalContext"]


def test_burst_is_silent_when_serena_is_down_or_off(serena_repo: Path, monkeypatch) -> None:
    grep = payload(serena_repo, "PreToolUse", tool_name="Grep", tool_input={"pattern": "TODO"})
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: False)
    for _ in range(4):
        _, o = run("pre_tool", grep)
        assert o == ""
    monkeypatch.setattr(tools, "serena_is_reachable", lambda env=None: True)
    monkeypatch.setenv("DAEDALUS_SERENA_HOOK", "off")
    for _ in range(4):
        _, o = run("pre_tool", grep)
        assert o == ""


# --------------------------------------------------------------------------
# symbol-edit advisory on Edit/Write of a code file
# --------------------------------------------------------------------------


def test_edit_of_a_code_file_advises_symbol_editing_once(serena_repo: Path) -> None:
    target = serena_repo / "daedalus" / "a.py"
    call = payload(
        serena_repo, "PreToolUse", tool_name="Edit", tool_input={"file_path": str(target), "old_string": "x", "new_string": "y"}
    )
    r, out = run("pre_tool", call)
    spec = json.loads(out)["hookSpecificOutput"]
    assert "permissionDecision" not in spec
    assert "replace_symbol_body" in spec["additionalContext"]
    assert "daedalus/a.py" in spec["additionalContext"]
    assert r.note == "serena-edit-advise"
    _, out2 = run("pre_tool", call)
    assert out2 == "", "once per file per session"
    # not for docs, not for files that do not exist yet
    _, out3 = run("pre_tool", payload(serena_repo, "PreToolUse", tool_name="Edit", tool_input={"file_path": str(serena_repo / "docs" / "d.md")}))
    assert out3 == ""
    _, out4 = run("pre_tool", payload(serena_repo, "PreToolUse", tool_name="Write", tool_input={"file_path": str(serena_repo / "daedalus" / "new.py"), "content": ""}))
    assert out4 == ""


def test_serena_calls_are_counted_and_reset_the_burst(serena_repo: Path) -> None:
    for name in ("mcp__serena__find_symbol", "mcp__serena__replace_symbol_body"):
        r, out = run("post_tool", payload(serena_repo, "PostToolUse", tool_name=name, tool_input={}, tool_response={}))
        assert out == "" and r.note.startswith("serena-call:")
    s = state_of(serena_repo)["serena"]
    assert s["calls"] == 2 and s["last"] == "replace_symbol_body" and s["loaded"] is True
