"""Serena on every prompt (owner order 2026-09-06).

"richte hooks so ein das wir konstant SERENA benutzen am besten jeder prompt
brauch ein serena hook". This module is the text and the bookkeeping behind
that order; the wiring is in ``events`` (session card, turn line, subagent
card) and ``tools`` (advisories, usage tracking). Pure: no socket, no git, no
clock except the one seam ``_now`` so tests can drive the burst window.

What was measured before writing it (2026-09-06, this machine)
--------------------------------------------------------------
* ``.mcp.json`` started Serena with ``--project c:/Users/nukei/Desktop/agent_env``
  -- a directory that no longer exists. Activation failed and the server
  answered ``initialize`` after 43.5 s; Claude Code gives up at 30 s, so every
  session of the last days ran WITHOUT Serena and the routing hook fell open
  on ``serena-root-mismatch``.
* ``--project-from-cwd`` on this tree: ``initialize`` after 21.6-24.7 s. Of
  that, ``import serena.cli`` alone is 26.9 s under load (bare venv Python:
  3.5 s). The shim is innocent; the fix is ``MCP_TIMEOUT`` in settings, not a
  different launcher.
* Serena's first start auto-created ``.serena/project.yml`` with
  ``language_servers: []`` -- a project whose symbol tools are blind -- and its
  ignore walk entered ``.claude/worktrees`` (52,390 code files in 15 tree
  copies) because that path is excluded via ``.git/info/exclude``, which
  Serena does not read. Hence the tracked ``.serena/project.yml``.
* Serena's tools are DEFERRED in Claude Code: none of the ``mcp__serena__*``
  names is callable until a ``ToolSearch`` loads it. The most useful sentence
  on a fresh turn is therefore the exact ``ToolSearch`` call, and the line
  stops repeating it the moment a load or a call is observed.
* The upstream ``serena-hooks remind`` command answers three greps with a
  ``deny``. ``AGENTS.md`` classes a guard that blocks reading as a
  release-blocking defect, so its idea (a burst counter) is kept and its
  verdict (deny) is not: :data:`BURST_TEXT` is an advisory.

Budget: the turn line is capped at :data:`TURN_LINE_CAP` characters and sits
second in the turn output, behind the clock, where ``trim_lines`` (which drops
from the end) never reaches it. Prompt-derived hints are the first thing cut.
"""
from __future__ import annotations

import re
import time
from pathlib import Path

SESSION_LINE_CAP = 480
TURN_LINE_CAP = 480
SUBAGENT_LINE_CAP = 400
#: Native Grep / whole-file code Read calls in a row before the advisory.
BURST_THRESHOLD = 3
#: After one burst advisory, nothing more is said for this long.
BURST_QUIET_S = 120.0
HINT_LIMIT = 3

#: The tools worth loading first; ``ToolSearch`` takes a comma-separated
#: ``select:`` list. Read tools first, then the two edit tools that cover
#: most changes, then the whole-file fallback.
LOAD_TOOLS = (
    "get_symbols_overview",
    "find_symbol",
    "find_referencing_symbols",
    "replace_symbol_body",
    "insert_after_symbol",
    "replace_content",
)
CODE_SUFFIXES = frozenset({".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs"})
STARTUP_NOTE = "start is ~25 s of imports, MCP_TIMEOUT 120 s"
WORKFLOW = (
    "overview -> find_symbol(include_body) -> find_referencing_symbols; "
    "edit via replace_symbol_body/insert_after_symbol"
)
BURST_TEXT = (
    f"{BURST_THRESHOLD} native Grep/Read calls on code in a row without Serena. The "
    "language server answers these cheaper: get_symbols_overview(relative_path) for "
    "the file map, find_symbol(name_path, include_body=true) for one definition, "
    "find_referencing_symbols for call sites. Native tools stay allowed."
)

_now = time.time

_PATH = re.compile(r"(?<![\w/\\])((?:[\w.-]+[/\\])*[\w.-]+\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|rs))\b")
_CALL = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]{3,})\s*\(")
_CAMEL = re.compile(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
_STOP = frozenset({"print", "None", "True", "False", "self", "http", "https", "ToolSearch", "select", "python"})


def load_instruction() -> str:
    return 'ToolSearch "select:' + ",".join(f"mcp__serena__{t}" for t in LOAD_TOOLS) + '"'


def slot(state: dict) -> dict:
    """The Serena bookkeeping inside the session state, created on demand."""
    s = state.get("serena")
    if not isinstance(s, dict):
        s = {"loaded": False, "calls": 0, "last": "", "burst": 0, "nudged_at": 0.0}
        state["serena"] = s
    return s


def note_serena_call(state: dict, tool_name: str) -> str:
    """A Serena tool call succeeded: count it, remember it, reset the burst."""
    short = tool_name[len("mcp__serena__"):] if tool_name.startswith("mcp__serena__") else tool_name
    s = slot(state)
    s["loaded"] = True
    s["calls"] = int(s.get("calls", 0)) + 1
    s["last"] = short
    s["burst"] = 0
    return short


def note_tool_search(state: dict, tool_input: object) -> bool:
    """A ``ToolSearch`` that names Serena loaded its tools."""
    query = tool_input.get("query") if isinstance(tool_input, dict) else None
    if not isinstance(query, str) or "serena" not in query.lower():
        return False
    slot(state)["loaded"] = True
    return True


def burst_update(state: dict, now: float) -> bool:
    """One native code lookup happened. True when the advisory fires now."""
    s = slot(state)
    s["burst"] = int(s.get("burst", 0)) + 1
    if s["burst"] < BURST_THRESHOLD:
        return False
    if now - float(s.get("nudged_at", 0.0)) < BURST_QUIET_S:
        return False
    s["burst"] = 0
    s["nudged_at"] = now
    return True


def burst_reset(state: dict) -> None:
    """A Serena advisory of any kind was just given; the burst starts over."""
    slot(state)["burst"] = 0


def relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.name


def edit_nudge(tool_input: dict, root: Path) -> tuple[str, str] | None:
    """(key, text) for an Edit/Write of an EXISTING code file, else None."""
    raw = tool_input.get("file_path")
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    if path.suffix.lower() not in CODE_SUFFIXES or not path.is_file():
        return None
    rel = relative(path, root)
    return (
        f"edit:{rel}",
        f"Serena edits {rel} at symbol level: find_symbol(name_path, relative_path={rel!r}, "
        "include_body=true) then replace_symbol_body / insert_after_symbol / "
        "insert_before_symbol -- no exact old_string, the rest of the file stays "
        "untouched. Edit stays allowed.",
    )


def prompt_hints(prompt: str, root: Path) -> list[str]:
    """Concrete Serena calls suggested by the prompt: an overview for every
    code path that exists in this tree, ``find_symbol`` for call-shaped and
    CamelCase identifiers. At most :data:`HINT_LIMIT`, paths first."""
    hints: list[str] = []
    seen: set[str] = set()
    for m in _PATH.finditer(prompt):
        rel = m.group(1).replace("\\", "/")
        if rel in seen:
            continue
        try:
            exists = (root / rel).is_file()
        except OSError:
            exists = False
        if exists:
            seen.add(rel)
            hints.append(f'get_symbols_overview("{rel}")')
    for rx in (_CALL, _CAMEL):
        for m in rx.finditer(prompt):
            name = m.group(1)
            if name in seen or name in _STOP:
                continue
            seen.add(name)
            hints.append(f'find_symbol("{name}")')
    return hints[:HINT_LIMIT]


def _body(state: dict, *, reachable: bool, configured: bool, mismatch: object) -> str:
    if not configured:
        return (
            "not configured in .mcp.json -> serena start-mcp-server --context claude-code "
            "--project-from-cwd"
        )
    if mismatch:
        return (
            f"configured root {mismatch} != this tree -> answers describe another tree, "
            "WRITE tools denied; native tools here"
        )
    if not reachable:
        return (
            f"server not answering yet ({STARTUP_NOTE}) -- native tools until it answers, "
            "then load and prefer Serena"
        )
    s = slot(state)
    if not s.get("loaded"):
        return f"up, tools not loaded -> {load_instruction()} first; then {WORKFLOW}"
    n = int(s.get("calls", 0))
    last = s.get("last") or "-"
    return f"loaded, {n} call{'s' if n != 1 else ''} so far (last {last}) -- {WORKFLOW}"


def turn_line(
    root: Path,
    state: dict,
    prompt: object,
    *,
    reachable: bool,
    configured: bool,
    mismatch: object,
) -> str:
    """The one SERENA line of a turn, hints included while they fit."""
    line = "SERENA: " + _body(state, reachable=reachable, configured=configured, mismatch=mismatch)
    usable = configured and not mismatch and reachable
    hints = prompt_hints(prompt, root) if usable and isinstance(prompt, str) else []
    while hints:
        extra = "; try " + ", ".join(hints)
        if len(line) + len(extra) <= TURN_LINE_CAP:
            line += extra
            break
        hints = hints[:-1]
    return line[:TURN_LINE_CAP]


def subagent_line(*, reachable: bool, configured: bool, mismatch: object) -> str:
    """A subagent starts with an empty context: it has loaded nothing."""
    fresh: dict = {}
    return ("SERENA: " + _body(fresh, reachable=reachable, configured=configured, mismatch=mismatch))[
        :SUBAGENT_LINE_CAP
    ]


def session_line(
    state: dict,
    *,
    reachable: bool,
    configured: bool,
    mismatch: object,
    language_servers: list[str] | None,
    index_cached: bool,
) -> str:
    """The SERENA line of the session card: root, server, project health,
    index, and either the load instruction or the usage so far."""
    if not configured:
        return "SERENA: " + _body(state, reachable=reachable, configured=False, mismatch=None)
    parts = [f"root {mismatch} != this tree (WRITE tools denied)" if mismatch else "root this tree"]
    parts.append("up" if reachable else f"not answering yet ({STARTUP_NOTE})")
    if language_servers is None:
        parts.append("no .serena/project.yml here (a first start auto-creates a BLIND one; use the tracked file)")
    elif not language_servers:
        parts.append("project.yml language_servers EMPTY -> symbol tools blind; set [python, typescript, rust]")
    else:
        parts.append("project.yml " + ",".join(language_servers))
    parts.append("index cache present" if index_cached else "no index cache yet (serena project index warms it)")
    s = slot(state)
    if s.get("loaded"):
        parts.append(f"{int(s.get('calls', 0))} calls this session")
    else:
        parts.append("load: " + load_instruction())
    return ("SERENA: " + " | ".join(parts))[:SESSION_LINE_CAP]
