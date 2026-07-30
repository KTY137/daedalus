#!/usr/bin/env python3
"""Project-local drift guard for the Daedalus master plan.

This is a deterministic consistency and workflow guard, not a sandbox or an
identity provider. Runtime effect enforcement remains a Gate 0 deliverable.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


PLAN_REL = "docs/IKARUS_ARIADNE_MASTER_PLAN.md"
LEDGER_REL = "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl"
SCHEMA = "daedalus-master-plan-amendment/1"
PLAN_ID = "daedalus-master-plan"

PROTECTED_PATHS = (
    PLAN_REL,
    LEDGER_REL,
    "AGENTS.md",
    "CLAUDE.md",
    ".gitattributes",
    ".agentenv/agentenv.json",
    ".agentenv/tool-allowances.json",
    ".claude/settings.json",
    ".codex/hooks.json",
    ".agents/skills/enforce-iron-plan/SKILL.md",
    ".agents/skills/enforce-iron-plan/agents/openai.yaml",
    "daedalus/config.py",
    "daedalus/kairos/gated_writes.py",
    "daedalus/sensitivity.py",
    "templates/agentenv.json",
    "tools/iron_plan_guard.py",
    "tools/iron_plan_hook_runner.py",
    ".githooks/pre-commit",
    ".githooks/commit-msg",
    ".github/CODEOWNERS",
    ".github/workflows/iron-plan.yml",
    "tests/test_iron_plan_guard.py",
)

LOCAL_PROTECTED_PATHS = (
    ".git/config",
    ".claude/settings.local.json",
    ".codex/config.toml",
)

PROTECTED_PATH_PREFIXES = (
    ".git/iron-plan-hook-state/",
)

ADOPTION_REQUIRED = frozenset(
    {
        PLAN_REL,
        LEDGER_REL,
        "AGENTS.md",
        "CLAUDE.md",
        ".gitattributes",
        ".agentenv/agentenv.json",
        ".claude/settings.json",
        ".codex/hooks.json",
        ".agents/skills/enforce-iron-plan/SKILL.md",
        ".agents/skills/enforce-iron-plan/agents/openai.yaml",
        "daedalus/config.py",
        "daedalus/kairos/gated_writes.py",
        "daedalus/sensitivity.py",
        "templates/agentenv.json",
        "tools/iron_plan_guard.py",
        "tools/iron_plan_hook_runner.py",
        ".githooks/pre-commit",
        ".githooks/commit-msg",
        ".github/CODEOWNERS",
        ".github/workflows/iron-plan.yml",
        "tests/test_iron_plan_guard.py",
    }
)

GOVERNED_PREFIXES = (
    "daedalus/",
    "apps/",
    "agents/",
    "configs/",
    "structcore-rs/",
    "docs/",
    "tests/",
    "tools/",
    ".agentenv/",
    ".agents/",
    ".claude/",
    ".codex/",
    ".githooks/",
    ".github/",
)

GOVERNED_FILES = {
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "pyproject.toml",
}

REQUIRED_HOOK_EVENTS = (
    "SessionStart",
    "UserPromptSubmit",
    "PreToolUse",
    "SubagentStart",
    "Stop",
)

CLAUDE_HOOK_COMMAND = (
    'python "$(git rev-parse --show-toplevel)/tools/iron_plan_hook_runner.py" '
    "|| exit 2"
)
CODEX_HOOK_COMMAND = (
    'python3 "$(git rev-parse --show-toplevel)/tools/iron_plan_hook_runner.py" '
    "|| exit 2"
)
CODEX_WINDOWS_HOOK_COMMAND = (
    'powershell.exe -NoProfile -Command "$repo = git rev-parse --show-toplevel; '
    "& python (Join-Path $repo 'tools/iron_plan_hook_runner.py'); "
    'if (-not $?) { exit 2 }; if ($LASTEXITCODE -ne 0) { exit 2 }"'
)

MUTATING_TOOL_NAMES = {
    "apply_patch",
    "create",
    "createdirectory",
    "create_directory",
    "delete",
    "edit",
    "multiedit",
    "notebookedit",
    "remove",
    "rename",
    "save",
    "write",
    "writefile",
    "write_text_file",
}

MUTATING_NAME_HINTS = (
    "write_file",
    "edit_file",
    "delete_file",
    "remove_file",
    "move_file",
    "rename_file",
    "create_file",
    "apply_patch",
    "append_file",
    "create_directory",
    "delete",
    "remove",
    "rename",
    "save_file",
    "write_text",
)

SHELL_NAME_HINTS = (
    "bash",
    "exec_command",
    "execute_command",
    "powershell",
    "run_command",
    "shell",
    "terminal",
)

READ_ONLY_NAME_HINTS = (
    "find",
    "get_",
    "inspect",
    "list",
    "read",
    "search",
    "stat",
    "view",
)

OPAQUE_INTERACTIVE_TOOLS = {
    "feed_chars",
    "send_input",
    "write_stdin",
}

MUTATING_SHELL = re.compile(
    r"""(?ix)
    (?:
        \b(?:rm|mv|cp|touch|truncate)\b |
        \b(?:sed|perl)\b[^\r\n]*\s-i(?:\s|$) |
        \btee\b |
        \bgit\s+(?:add|apply|am|checkout|cherry-pick|clean|commit|merge|mv|
                         pull|rebase|reset|restore|rm|stash|switch)\b |
        \b(?:set-content|add-content|out-file|remove-item|move-item|copy-item|
             rename-item|new-item|clear-content)\b |
        (?:^|[^\w])(?:>>|>)(?:[^\r\n]|$) |
        \b(?:write_text|write_bytes)\s*\( |
        \bopen\s*\([^,\r\n]+,\s*(?:mode\s*=\s*)?["'][^"']*[wax+][^"']*["'] |
        \.open\s*\(\s*(?:mode\s*=\s*)?["'][^"']*[wax+][^"']*["'] |
        \b(?:os\.)?(?:remove|unlink|rename|replace|mkdir|makedirs|rmdir)\s*\( |
        \bshutil\.(?:copy|copy2|copyfile|copytree|move|rmtree)\s*\( |
        \b(?:fs\.)?(?:writeFile|writeFileSync|appendFile|appendFileSync|
             rm|rmSync|unlink|unlinkSync|rename|renameSync|copyFile|
             copyFileSync|mkdir|mkdirSync)\s*\( |
        (?:\[[^\]\r\n]*(?:System\.)?IO\.(?:File|Directory)[^\]\r\n]*\]|
             \b(?:System\.)?IO\.(?:File|Directory)\b)
             ::\s*(?:Write|Append|Delete|Move|Copy|Create)[A-Za-z]*\s*\( |
        \b(?:del|erase|rmdir|rd|xcopy|robocopy|install|ln|chmod|attrib|icacls)\b |
        \bfind\b[^\r\n]*(?:-delete|-exec)\b |
        \b(?:tar|unzip|7z)\b[^\r\n]*(?:\s-x|\bx\b|\bextract\b)
    )
    """
)

HOOK_CONTROL_MUTATION = re.compile(
    r"""(?ix)
    (?:
        \bgit\b[^\r\n]*\s-c\s+core\.hooksPath\s*= |
        \bgit\s+config\b[^\r\n]*
        (?:
            --unset(?:-all)?\s+core\.hooksPath |
            core\.hooksPath(?:\s+|=)["']?[^\s;&|]+
        )
    )
    """
)

BROAD_REPOSITORY_MUTATION = re.compile(
    r"""(?ix)
    (?:
        \bgit\s+(?:apply|am|cherry-pick|clean|merge|pull|rebase|switch)\b |
        \bgit\s+reset\b[^\r\n]*--hard\b |
        \bgit\s+checkout\b[^\r\n]*\s--\s+\.(?:\s|$) |
        \bgit\s+checkout\b(?![^\r\n]*\s--\s) |
        \bgit\s+restore\b[^\r\n]*(?:\s|["'])\.(?:\s|["']|$) |
        \bgit\s+stash\s+(?:apply|pop)\b |
        \bgit\s+commit\b[^\r\n]*--no-verify\b
    )
    """
)

BROAD_FILESYSTEM_MUTATION = re.compile(
    r"""(?ix)
    (?:
        \b(?:rm|rmdir|rd|del|erase)\b[^\r\n;&|]*
            (?:^|\s)(?:\.\.?)(?:[\\/])?(?:\s|$) |
        \b(?:remove-item|move-item|rename-item)\b[^\r\n;&|]*
            (?:^|\s)(?:\.\.?)(?:[\\/])?(?:\s|$)
    )
    """
)

COMMAND_PATH_LIKE = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9_.-])
    (?:
        [A-Za-z]:[\\/] |
        (?:\.\.?[\\/])?
    )
    (?:[A-Za-z0-9_.-]+[\\/])+
    [A-Za-z0-9_.-]+
    (?![A-Za-z0-9_.-])
    """
)

COMMAND_GLOB_LIKE = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9_.-])
    (?:
        [A-Za-z]:[\\/] |
        (?:\.\.?[\\/])?
    )?
    (?:[A-Za-z0-9_.-]+[\\/])*
    [A-Za-z0-9_.\[\]?*-]*[*?\[][^\s'";&|)]*
    """
)

INTERACTIVE_COMMAND = re.compile(
    r"""(?ix)^\s*
    (?:
        (?:pwsh|powershell|cmd|bash|sh|zsh|fish)(?:\.exe)?\s* |
        (?:python|python3|py)(?:\.exe)?\s+(?:-[^\s]*i|-\s*i)\b |
        (?:node|irb|iex|jshell)(?:\.exe)?\s*
    )
    (?:$|[;&|])
    """
)

GIT_SEGMENT = re.compile(r"(?i)(?<![A-Za-z0-9_.-])git(?:\.exe)?\b([^;&|\r\n]*)")
SHELL_TOKEN = re.compile(r'''"(?:\\.|[^"])*"|'(?:\\.|[^'])*'|[^\s]+''')
HOOKS_ACTIVATION_COMMAND = re.compile(
    r"""(?ix)^\s*
    git(?:\.exe)?\s+config\s+--local\s+
    core\.hooksPath\s+["']?\.githooks["']?\s*
    $"""
)

PATCH_PATH = re.compile(
    r"^\*\*\* (?:Add|Update|Delete) File:\s*(.+?)\s*$|"
    r"^\*\*\* Move to:\s*(.+?)\s*$",
    re.MULTILINE,
)

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def repo_root(value: str | Path | None = None) -> Path:
    if value is not None:
        return Path(value).resolve()
    return Path(__file__).resolve().parents[1]


def normalized_text(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


def file_sha256(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return hashlib.sha256(normalized_text(text).encode("utf-8")).hexdigest()


def canonical_record_sha256(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key != "record_sha256"}
    encoded = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def parse_ledger_text(
    text: str, label: str = LEDGER_REL
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label}:{number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label}:{number}: record must be an object")
        records.append(value)
    return records


def read_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_REL
    return parse_ledger_text(path.read_text(encoding="utf-8"))


def parse_plan_header(text: str) -> tuple[int | None, str | None, str | None]:
    revision_match = re.search(r"(?m)^Revision:\s*(\d+)\s*$", text)
    version_match = re.search(r"(?m)^Version:\s*([^\s]+)\s*$", text)
    gate_match = re.search(r"(?m)^Active delivery gate:\s*(.+?)\s*$", text)
    return (
        int(revision_match.group(1)) if revision_match else None,
        version_match.group(1) if version_match else None,
        gate_match.group(1) if gate_match else None,
    )


def _load_json(path: Path, label: str, errors: list[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        errors.append(f"{label} is not valid readable JSON: {exc}")
        return None
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a JSON object")
        return None
    return value


def _read_utf8(path: Path, label: str, errors: list[str]) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        errors.append(f"{label} is not valid readable UTF-8: {exc}")
        return None


def _hook_has_guard(
    config: dict[str, Any], event: str, platform: str
) -> bool:
    entries = (config.get("hooks") or {}).get(event)
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            if hook.get("type") != "command" or hook.get("timeout") != 10:
                continue
            command = str(hook.get("command") or "")
            command_windows = str(hook.get("commandWindows") or "")
            if platform == "claude" and command == CLAUDE_HOOK_COMMAND:
                return True
            if (
                platform == "codex"
                and command == CODEX_HOOK_COMMAND
                and command_windows == CODEX_WINDOWS_HOOK_COMMAND
            ):
                return True
    return False


def _codex_hooks_disabled(text: str) -> bool:
    """Read the two local feature switches without requiring Python 3.11 TOML.

    The repository supports Python 3.10. This deliberately tiny reader only
    answers whether a plain boolean assignment inside ``[features]`` disables
    hooks; it does not pretend to be a general TOML parser.
    """

    in_features = False
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        section = re.fullmatch(r"\[([^\]]+)\]", line)
        if section:
            in_features = section.group(1).strip() == "features"
            continue
        if not in_features:
            continue
        match = re.fullmatch(r"(hooks|codex_hooks)\s*=\s*(true|false)", line, re.I)
        if match and match.group(2).casefold() == "false":
            return True
    return False


def _git_index_mode(root: Path, rel: str) -> str | None:
    proc = subprocess.run(
        ["git", "ls-files", "--stage", "--", rel],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.split(None, 1)[0]


def _python_tree(
    path: Path, label: str, errors: list[str]
) -> ast.Module | None:
    source = _read_utf8(path, label, errors)
    if source is None:
        return None
    try:
        return ast.parse(source, filename=label)
    except SyntaxError as exc:
        errors.append(f"{label} is not valid Python: {exc}")
        return None


def _literal_assignment(tree: ast.Module, name: str) -> Any:
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            try:
                return ast.literal_eval(node.value)
            except (ValueError, TypeError):
                return None
    return None


def _function_calls_name(tree: ast.Module, function: str, callee: str) -> bool:
    target = next(
        (
            node
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function
        ),
        None,
    )
    if target is None:
        return False
    return any(
        isinstance(node, ast.Call)
        and (
            isinstance(node.func, ast.Name)
            and node.func.id == callee
            or isinstance(node.func, ast.Attribute)
            and node.func.attr == callee
        )
        for node in ast.walk(target)
    )


def verify(root_value: str | Path | None = None) -> list[str]:
    root = repo_root(root_value)
    errors: list[str] = []

    for rel in PROTECTED_PATHS:
        if not (root / rel).is_file():
            errors.append(f"required policy artifact missing: {rel}")

    plan_path = root / PLAN_REL
    ledger_path = root / LEDGER_REL
    if not plan_path.is_file() or not ledger_path.is_file():
        return errors

    try:
        plan_text = plan_path.read_text(encoding="utf-8")
        plan_digest = file_sha256(plan_path)
    except (OSError, UnicodeError) as exc:
        errors.append(f"{PLAN_REL} is not valid UTF-8: {exc}")
        return errors

    revision, version, active_gate = parse_plan_header(plan_text)
    if revision is None:
        errors.append(f"{PLAN_REL} has no numeric Revision header")
    if version is None:
        errors.append(f"{PLAN_REL} has no Version header")
    if not active_gate or not active_gate.startswith("Gate "):
        errors.append(f"{PLAN_REL} has no valid Active delivery gate header")

    try:
        records = read_ledger(root)
    except (OSError, UnicodeError, ValueError) as exc:
        errors.append(str(exc))
        records = []

    if not records:
        errors.append(f"{LEDGER_REL} has no accepted records")
    previous: dict[str, Any] | None = None
    for index, record in enumerate(records, start=1):
        prefix = f"{LEDGER_REL} record {index}"
        if record.get("schema") != SCHEMA:
            errors.append(f"{prefix}: unexpected schema")
        if record.get("plan_id") != PLAN_ID:
            errors.append(f"{prefix}: unexpected plan_id")
        if record.get("status") != "accepted":
            errors.append(f"{prefix}: status must be accepted")
        if record.get("sequence") != index:
            errors.append(f"{prefix}: sequence must be {index}")
        actual_record_digest = canonical_record_sha256(record)
        if record.get("record_sha256") != actual_record_digest:
            errors.append(f"{prefix}: record_sha256 mismatch")
        for field in ("base_plan_sha256", "result_plan_sha256", "record_sha256"):
            if not SHA256.fullmatch(str(record.get(field) or "")):
                errors.append(f"{prefix}: {field} must be lowercase sha256")
        if not str(record.get("approval_ref") or "").strip():
            errors.append(f"{prefix}: approval_ref is required")
        base_revision = record.get("base_revision")
        result_revision = record.get("result_revision")
        if not isinstance(base_revision, int) or result_revision != base_revision + 1:
            errors.append(f"{prefix}: revision must increase by exactly one")
        if previous is None:
            if record.get("previous_record_sha256") is not None:
                errors.append(f"{prefix}: first previous_record_sha256 must be null")
        else:
            if record.get("previous_record_sha256") != previous.get("record_sha256"):
                errors.append(f"{prefix}: previous-record hash chain is broken")
            if record.get("base_plan_sha256") != previous.get("result_plan_sha256"):
                errors.append(f"{prefix}: plan digest chain is broken")
            if base_revision != previous.get("result_revision"):
                errors.append(f"{prefix}: plan revision chain is broken")
        previous = record

    if records:
        latest = records[-1]
        if latest.get("result_plan_sha256") != plan_digest:
            errors.append(
                f"{PLAN_REL} digest {plan_digest} does not match accepted ledger "
                f"digest {latest.get('result_plan_sha256')}"
            )
        if revision != latest.get("result_revision"):
            errors.append(f"{PLAN_REL} Revision does not match the ledger")
        if version != latest.get("version"):
            errors.append(f"{PLAN_REL} Version does not match the ledger")

    agents_path = root / "AGENTS.md"
    if agents_path.is_file():
        agents = _read_utf8(agents_path, "AGENTS.md", errors)
    else:
        agents = None
    if agents is not None:
        for needle in (PLAN_REL, "iron_plan_guard.py", "ALIGNED", "EXPERIMENT", "AMENDMENT"):
            if needle not in agents:
                errors.append(f"AGENTS.md does not reference {needle!r}")

    claude_path = root / "CLAUDE.md"
    if claude_path.is_file():
        raw_claude = _read_utf8(claude_path, "CLAUDE.md", errors)
        claude = normalized_text(raw_claude) if raw_claude is not None else None
    else:
        claude = None
    if claude is not None:
        for needle in ("@AGENTS.md", f"@{PLAN_REL}"):
            if needle not in claude:
                errors.append(f"CLAUDE.md does not import {needle!r}")

    skill_path = root / ".agents/skills/enforce-iron-plan/SKILL.md"
    if skill_path.is_file():
        skill = _read_utf8(
            skill_path, ".agents/skills/enforce-iron-plan/SKILL.md", errors
        )
    else:
        skill = None
    if skill is not None:
        if "[TODO" in skill or "TODO:" in skill:
            errors.append("enforce-iron-plan skill still contains a TODO placeholder")
        if PLAN_REL not in skill:
            errors.append(f"enforce-iron-plan skill does not reference {PLAN_REL}")

    for rel in (".claude/settings.json", ".codex/hooks.json"):
        path = root / rel
        if not path.is_file():
            continue
        config = _load_json(path, rel, errors)
        if config is None:
            continue
        if rel.startswith(".claude/") and config.get("disableAllHooks") is True:
            errors.append(f"{rel} disables all hooks")
        platform = "claude" if rel.startswith(".claude/") else "codex"
        for event in REQUIRED_HOOK_EVENTS:
            if not _hook_has_guard(config, event, platform):
                errors.append(f"{rel} has no Iron Plan guard for {event}")

    claude_local = root / ".claude/settings.local.json"
    if claude_local.is_file():
        local_config = _load_json(
            claude_local, ".claude/settings.local.json", errors
        )
        if local_config and local_config.get("disableAllHooks") is True:
            errors.append(".claude/settings.local.json disables all hooks")

    codex_config = root / ".codex/config.toml"
    if codex_config.is_file():
        codex_text = _read_utf8(codex_config, ".codex/config.toml", errors)
        if codex_text is not None and _codex_hooks_disabled(codex_text):
            errors.append(".codex/config.toml disables project hooks")

    agentenv_path = root / ".agentenv/agentenv.json"
    if agentenv_path.is_file():
        config = _load_json(agentenv_path, ".agentenv/agentenv.json", errors)
        if config is not None and config.get("write_wave_policy") != "never":
            errors.append(
                ".agentenv/agentenv.json write_wave_policy must be 'never'"
            )
        high_risk = (
            ((config or {}).get("policy") or {}).get("high_risk_paths") or []
        )
        for required in (
            PLAN_REL,
            LEDGER_REL,
            "AGENTS.md",
            "CLAUDE.md",
            "daedalus/config.py",
            "daedalus/kairos/gated_writes.py",
            "daedalus/sensitivity.py",
            "templates/agentenv.json",
            "tools/iron_plan_guard.py",
            "tools/iron_plan_hook_runner.py",
            "tests/test_iron_plan_guard.py",
            ".claude/settings.json",
            ".codex/",
            ".agents/skills/enforce-iron-plan/",
            ".githooks/",
            ".github/",
            ".gitattributes",
        ):
            if required not in high_risk:
                errors.append(
                    f".agentenv/agentenv.json high_risk_paths lacks {required}"
                )

    config_tree = _python_tree(root / "daedalus/config.py", "daedalus/config.py", errors)
    if config_tree is not None:
        if _literal_assignment(config_tree, "WRITE_WAVE_POLICY_LEVELS") != ("never",):
            errors.append(
                "daedalus/config.py must expose only the sealed 'never' "
                "write-wave policy"
            )
        starter = _literal_assignment(config_tree, "STARTER")
        if not isinstance(starter, dict) or starter.get("write_wave_policy") != "never":
            errors.append("daedalus/config.py STARTER must disable auto-promotion")

    gated_tree = _python_tree(
        root / "daedalus/kairos/gated_writes.py",
        "daedalus/kairos/gated_writes.py",
        errors,
    )
    if gated_tree is not None:
        if _literal_assignment(gated_tree, "AUTO_PROMOTE_LEVELS") != ("never",):
            errors.append(
                "daedalus/kairos/gated_writes.py exposes automatic promotion"
            )
        if _function_calls_name(gated_tree, "run_write_wave", "promote_candidates"):
            errors.append(
                "run_write_wave must not call promote_candidates automatically"
            )

    template_path = root / "templates/agentenv.json"
    if template_path.is_file():
        template = _load_json(template_path, "templates/agentenv.json", errors)
        if template is not None and template.get("write_wave_policy") != "never":
            errors.append("templates/agentenv.json arms automatic promotion")

    for rel in (".githooks/pre-commit", ".githooks/commit-msg"):
        path = root / rel
        if path.is_file():
            hook_text = _read_utf8(path, rel, errors)
            if hook_text is not None and "iron_plan_guard.py" not in hook_text:
                errors.append(f"{rel} does not invoke iron_plan_guard.py")
        mode = _git_index_mode(root, rel)
        if mode is not None and mode != "100755":
            errors.append(
                f"{rel} is staged/tracked with mode {mode}, not executable "
                "(run: git add --chmod=+x .githooks/pre-commit "
                ".githooks/commit-msg)"
            )

    attributes_path = root / ".gitattributes"
    if attributes_path.is_file():
        attributes = _read_utf8(attributes_path, ".gitattributes", errors)
        if attributes is not None and ".githooks/* text eol=lf" not in attributes:
            errors.append(".gitattributes does not pin Git hook line endings")

    runner_path = root / "tools/iron_plan_hook_runner.py"
    if runner_path.is_file():
        runner = _read_utf8(runner_path, "tools/iron_plan_hook_runner.py", errors)
        if runner is not None:
            for needle in ("iron_plan_guard.py", "timeout=8", "return 2"):
                if needle not in runner:
                    errors.append(
                        "tools/iron_plan_hook_runner.py lacks fail-closed "
                        f"contract marker {needle!r}"
                    )

    codeowners_path = root / ".github/CODEOWNERS"
    if codeowners_path.is_file():
        codeowners = _read_utf8(codeowners_path, ".github/CODEOWNERS", errors)
        if codeowners is not None:
            owned_patterns: list[str] = []
            for raw_line in codeowners.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                fields = line.split()
                if len(fields) >= 2 and "@KTY137" in fields[1:]:
                    owned_patterns.append(fields[0].lstrip("/"))
            for rel in PROTECTED_PATHS:
                covered = any(
                    rel.startswith(pattern)
                    if pattern.endswith("/")
                    else rel == pattern
                    for pattern in owned_patterns
                )
                if not covered:
                    errors.append(
                        f".github/CODEOWNERS lacks @KTY137 coverage for {rel}"
                    )

    workflow_path = root / ".github/workflows/iron-plan.yml"
    if workflow_path.is_file():
        workflow = _read_utf8(
            workflow_path, ".github/workflows/iron-plan.yml", errors
        )
        if workflow is not None:
            for needle in (
                "fetch-depth: 0",
                "iron_plan_guard.py verify",
                "iron_plan_guard.py verify-base",
                "tests.test_iron_plan_guard",
            ):
                if needle not in workflow:
                    errors.append(
                        ".github/workflows/iron-plan.yml lacks "
                        f"contract marker {needle!r}"
                    )

    if not os.environ.get("CI") and (root / ".git").exists():
        hooks_path = subprocess.run(
            ["git", "config", "--local", "--get", "core.hooksPath"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        configured = hooks_path.stdout.strip().replace("\\", "/")
        if hooks_path.returncode != 0 or configured != ".githooks":
            errors.append(
                "local core.hooksPath is not .githooks "
                "(run: git config --local core.hooksPath .githooks)"
            )

    return errors


def _windows_local_alias(value: str) -> str:
    """Collapse common Windows aliases for this machine before Path.resolve."""

    candidate = value.replace("\\", "/")
    lowered = candidate.casefold()
    if lowered.startswith("//?/unc/"):
        candidate = "//" + candidate[8:]
    elif lowered.startswith("//?/") or lowered.startswith("//./"):
        candidate = candidate[4:]

    admin = re.match(r"^//([^/]+)/([A-Za-z])\$(?:/(.*))?$", candidate)
    if admin:
        host = admin.group(1).casefold()
        local_hosts = {
            ".",
            "127.0.0.1",
            "localhost",
            str(os.environ.get("COMPUTERNAME") or "").casefold(),
        }
        if host in local_hosts:
            suffix = admin.group(3) or ""
            candidate = f"{admin.group(2)}:/{suffix}"
    return candidate


def normalize_repo_path(value: str, root: Path) -> str:
    candidate = value.strip().strip("\"'`<>")
    if not candidate:
        return ""
    if candidate.casefold().startswith("file:"):
        parsed = urlparse(candidate)
        if parsed.scheme.casefold() == "file":
            candidate = unquote(parsed.path)
            if os.name == "nt" and re.match(r"^/[A-Za-z]:/", candidate):
                candidate = candidate[1:]
            if parsed.netloc and parsed.netloc.casefold() not in {"", "localhost"}:
                candidate = f"//{parsed.netloc}/{candidate.lstrip('/')}"
    if os.name == "nt":
        candidate = _windows_local_alias(candidate)
    else:
        candidate = candidate.replace("\\", "/")
    try:
        resolved_root = root.resolve(strict=False)
        path = Path(candidate)
        resolved = (
            path.resolve(strict=False)
            if path.is_absolute()
            else (resolved_root / path).resolve(strict=False)
        )
        candidate = resolved.relative_to(resolved_root).as_posix()
    except (OSError, ValueError):
        candidate = os.path.normpath(candidate).replace("\\", "/")
    return candidate.rstrip("/")


def _path_equal(left: str, right: str) -> bool:
    if os.name == "nt":
        return left.casefold() == right.casefold()
    return left == right


def _path_under(value: str, prefix: str) -> bool:
    normalized_prefix = prefix.rstrip("/")
    return _path_equal(value, normalized_prefix) or (
        value.casefold().startswith(normalized_prefix.casefold() + "/")
        if os.name == "nt"
        else value.startswith(normalized_prefix + "/")
    )


def _same_existing_path(value: str, target: Path) -> bool:
    try:
        raw = value.strip().strip("\"'`<>")
        if os.name == "nt":
            raw = _windows_local_alias(raw)
        return target.exists() and Path(raw).exists() and os.path.samefile(raw, target)
    except (OSError, ValueError):
        return False


def is_protected_path(value: str, root: Path) -> bool:
    normalized = normalize_repo_path(value, root)
    if any(
        _path_equal(normalized, protected)
        for protected in (*PROTECTED_PATHS, *LOCAL_PROTECTED_PATHS)
    ):
        return True
    if any(_path_under(normalized, prefix) for prefix in PROTECTED_PATH_PREFIXES):
        return True
    return any(
        _same_existing_path(value, root / protected)
        for protected in (*PROTECTED_PATHS, *LOCAL_PROTECTED_PATHS)
    )


def is_governed_path(value: str, root: Path) -> bool:
    normalized = normalize_repo_path(value, root)
    if normalized == "":
        return True
    if (
        normalized == ".."
        or normalized.startswith("../")
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
    ):
        return False
    comparable = normalized.casefold() if os.name == "nt" else normalized
    files = {item.casefold() if os.name == "nt" else item for item in GOVERNED_FILES}
    if comparable in files:
        return True
    prefixes = (
        tuple(item.casefold() for item in GOVERNED_PREFIXES)
        if os.name == "nt"
        else GOVERNED_PREFIXES
    )
    if comparable.startswith(prefixes):
        return True
    # Repo governance is default-on. Prefixes above remain documentation and
    # fast paths, but a newly minted top-level directory must not silently
    # escape the evidence handoff.
    return True


def _walk_path_values(value: Any, parent_key: str = "") -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key).casefold()
            yield from _walk_path_values(child, key_text)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_path_values(child, parent_key)
    elif isinstance(value, str) and (
        "path" in parent_key
        or "file" in parent_key
        or "uri" in parent_key
        or parent_key in {"destination", "source", "target"}
    ):
        yield value


def _walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield value


def patch_paths(tool_input: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for value in _walk_strings(tool_input):
        if "*** " not in value:
            continue
        for match in PATCH_PATH.finditer(value):
            found.append(match.group(1) or match.group(2))
    return found


def target_paths(tool_input: dict[str, Any]) -> list[str]:
    values = list(_walk_path_values(tool_input))
    values.extend(patch_paths(tool_input))
    return list(dict.fromkeys(values))


def command_paths(command: str) -> list[str]:
    """Extract path-shaped command fragments for canonical traversal checks."""

    return list(dict.fromkeys(match.group(0) for match in COMMAND_PATH_LIKE.finditer(command)))


def command_globs(command: str) -> list[str]:
    return list(
        dict.fromkeys(match.group(0) for match in COMMAND_GLOB_LIKE.finditer(command))
    )


def protected_parent_paths() -> tuple[str, ...]:
    parents: set[str] = set()
    for rel in (
        *PROTECTED_PATHS,
        *LOCAL_PROTECTED_PATHS,
        *PROTECTED_PATH_PREFIXES,
    ):
        parts = rel.split("/")[:-1]
        for end in range(1, len(parts) + 1):
            parents.add("/".join(parts[:end]))
    return tuple(sorted(parents, key=lambda item: (-item.count("/"), item)))


def _standalone_path_in_command(command: str, path: str) -> bool:
    normalized = command.replace("\\", "/")
    flags = re.IGNORECASE if os.name == "nt" else 0
    pattern = (
        r"(?<![A-Za-z0-9_.-])(?:\./)?"
        + re.escape(path)
        + r"/?(?:\*+)?(?![A-Za-z0-9_./*-])"
    )
    return re.search(pattern, normalized, flags) is not None


def _normalize_repo_glob(value: str, root: Path) -> str:
    candidate = value.strip().strip("\"'`<>").replace("\\", "/")
    if os.name == "nt":
        candidate = _windows_local_alias(candidate)
    root_text = root.resolve(strict=False).as_posix().rstrip("/")
    candidate_cmp = candidate.casefold() if os.name == "nt" else candidate
    root_cmp = root_text.casefold() if os.name == "nt" else root_text
    if candidate_cmp == root_cmp:
        return ""
    if candidate_cmp.startswith(root_cmp + "/"):
        candidate = candidate[len(root_text) + 1 :]
    while candidate.startswith("./"):
        candidate = candidate[2:]
    return os.path.normpath(candidate).replace("\\", "/").rstrip("/")


def protected_glob_targets(command: str, root: Path) -> list[str]:
    found: list[str] = []
    protected_values = (*PROTECTED_PATHS, *LOCAL_PROTECTED_PATHS)
    for raw_pattern in command_globs(command):
        pattern = _normalize_repo_glob(raw_pattern, root)
        pattern_cmp = pattern.casefold() if os.name == "nt" else pattern
        for protected in protected_values:
            protected_cmp = protected.casefold() if os.name == "nt" else protected
            if fnmatch.fnmatchcase(protected_cmp, pattern_cmp):
                found.append(protected)
        for prefix in PROTECTED_PATH_PREFIXES:
            prefix_cmp = prefix.casefold() if os.name == "nt" else prefix
            if (
                fnmatch.fnmatchcase(prefix_cmp.rstrip("/"), pattern_cmp)
                or fnmatch.fnmatchcase(prefix_cmp + "__probe__", pattern_cmp)
            ):
                found.append(f"<directory: {prefix.rstrip('/')}>")
    return list(dict.fromkeys(found))


def shell_command(tool_input: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script", "_command", "code"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value
    return ""


def _unquote_shell_token(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def git_invocations(command: str) -> list[tuple[str, list[str], str]]:
    """Return Git subcommands after skipping common global Git options."""

    calls: list[tuple[str, list[str], str]] = []
    options_with_value = {
        "-c",
        "-C",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
    no_value_options = {
        "--bare",
        "--html-path",
        "--info-path",
        "--literal-pathspecs",
        "--no-lazy-fetch",
        "--no-optional-locks",
        "--no-pager",
        "--no-replace-objects",
        "--paginate",
        "--version",
    }
    for match in GIT_SEGMENT.finditer(command):
        body = match.group(1)
        tokens = [_unquote_shell_token(item) for item in SHELL_TOKEN.findall(body)]
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token in options_with_value:
                index += 2
                continue
            if any(token.startswith(option + "=") for option in options_with_value):
                index += 1
                continue
            if token in no_value_options:
                index += 1
                continue
            if token.startswith("-"):
                index += 1
                continue
            calls.append((token.casefold(), tokens[index + 1 :], body))
            break
    return calls


def _git_config_is_mutating(args: list[str]) -> bool:
    lowered = [item.casefold() for item in args]
    if any(
        item
        in {
            "--add",
            "--remove-section",
            "--rename-section",
            "--replace-all",
            "--unset",
            "--unset-all",
        }
        for item in lowered
    ):
        return True
    if any(
        item
        in {
            "--get",
            "--get-all",
            "--get-regexp",
            "--get-urlmatch",
            "--list",
            "-l",
        }
        for item in lowered
    ):
        return False
    scope_flags = {
        "--blob",
        "--file",
        "--global",
        "--local",
        "--system",
        "--worktree",
        "-f",
    }
    positional: list[str] = []
    skip_value = False
    for item in args:
        lowered_item = item.casefold()
        if skip_value:
            skip_value = False
            continue
        if lowered_item in {"--file", "--blob", "-f"}:
            skip_value = True
            continue
        if lowered_item in scope_flags or lowered_item.startswith("--type="):
            continue
        if lowered_item.startswith("-"):
            continue
        positional.append(item)
    return len(positional) >= 2


def git_command_is_mutating(command: str) -> bool:
    mutating = {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "merge",
        "mv",
        "pull",
        "rebase",
        "reset",
        "restore",
        "rm",
        "stash",
        "switch",
        "update-index",
    }
    for subcommand, args, _ in git_invocations(command):
        if subcommand == "config":
            if _git_config_is_mutating(args):
                return True
        elif subcommand in mutating:
            return True
    return False


def git_command_controls_hooks(command: str) -> bool:
    for subcommand, args, body in git_invocations(command):
        combined = " ".join(args).casefold()
        if subcommand == "config" and _git_config_is_mutating(args):
            if "core.hookspath" in combined:
                return True
        if "core.hookspath" in body.casefold() and re.search(
            r"(?i)(?:^|\s)-c(?:\s+|=)?core\.hooksPath", body
        ):
            return True
    return False


def is_exact_hooks_activation(command: str) -> bool:
    return HOOKS_ACTIVATION_COMMAND.fullmatch(command) is not None


def git_command_is_broad_policy_mutation(command: str) -> bool:
    broad = {
        "am",
        "apply",
        "cherry-pick",
        "clean",
        "merge",
        "pull",
        "rebase",
        "switch",
        "update-index",
    }
    for subcommand, args, _ in git_invocations(command):
        lowered = [item.casefold() for item in args]
        joined = " ".join(lowered)
        broad_pathspec = any(
            item in {":/", ":\\", "*", "**"}
            or item.startswith((":(top", ":(glob", ":(icase", ":(attr"))
            or any(marker in item for marker in ("*", "?", "["))
            for item in lowered
        )
        if subcommand in broad:
            return True
        if subcommand == "reset" and "--hard" in lowered:
            return True
        if subcommand == "checkout":
            if (
                "--" not in lowered
                or re.search(r"(?:^|\s)--\s+\.(?:\s|$)", joined)
                or broad_pathspec
            ):
                return True
        if subcommand == "restore" and (
            any(item in {".", "./"} for item in lowered) or broad_pathspec
        ):
            return True
        if subcommand == "stash" and any(
            item in {"apply", "pop"} for item in lowered
        ):
            return True
        if subcommand == "commit" and any(
            item == "-n" or item == "--no-verify" for item in lowered
        ):
            return True
    return False


def is_mutating_tool(tool_name: str, tool_input: dict[str, Any]) -> bool:
    lowered = tool_name.casefold()
    leaf = re.split(r"[:./\\]+", lowered)[-1]
    if leaf in OPAQUE_INTERACTIVE_TOOLS or any(
        lowered.endswith("__" + item) for item in OPAQUE_INTERACTIVE_TOOLS
    ):
        return True
    if leaf in MUTATING_TOOL_NAMES or lowered in MUTATING_TOOL_NAMES:
        return True
    if any(hint in lowered for hint in MUTATING_NAME_HINTS):
        return True
    if any(hint in lowered for hint in SHELL_NAME_HINTS) or leaf in {
        "exec",
        "run",
    }:
        command = shell_command(tool_input)
        return bool(
            tool_input.get("tty") is True
            or INTERACTIVE_COMMAND.search(command)
            or MUTATING_SHELL.search(command)
            or HOOK_CONTROL_MUTATION.search(command)
            or git_command_is_mutating(command)
        )
    if target_paths(tool_input) and any(
        key in tool_input
        for key in (
            "body",
            "content",
            "data",
            "edits",
            "new_string",
            "patch",
            "value",
        )
    ):
        return True
    if target_paths(tool_input) and not any(
        hint in lowered for hint in READ_ONLY_NAME_HINTS
    ):
        return True
    return False


def protected_targets(
    tool_name: str, tool_input: dict[str, Any], root: Path
) -> list[str]:
    if not is_mutating_tool(tool_name, tool_input):
        return []
    lowered_name = tool_name.casefold()
    leaf = re.split(r"[:./\\]+", lowered_name)[-1]
    if (
        leaf in OPAQUE_INTERACTIVE_TOOLS
        or any(lowered_name.endswith("__" + item) for item in OPAQUE_INTERACTIVE_TOOLS)
        or tool_input.get("tty") is True
        or INTERACTIVE_COMMAND.search(shell_command(tool_input))
    ):
        return ["<opaque interactive process>"]
    found = [
        normalize_repo_path(path, root)
        for path in target_paths(tool_input)
        if is_protected_path(path, root)
    ]
    raw_command = shell_command(tool_input)
    for path in command_paths(raw_command):
        if is_protected_path(path, root):
            found.append(normalize_repo_path(path, root))
    command = raw_command.replace("\\", "/")
    command_cmp = command.casefold() if os.name == "nt" else command
    for protected in (*PROTECTED_PATHS, *LOCAL_PROTECTED_PATHS):
        protected_cmp = protected.casefold() if os.name == "nt" else protected
        if protected_cmp in command_cmp:
            found.append(protected)
    if command:
        found.extend(protected_glob_targets(command, root))
    hooks_activation = is_exact_hooks_activation(raw_command)
    if command and any(
        (
            BROAD_REPOSITORY_MUTATION.search(command),
            BROAD_FILESYSTEM_MUTATION.search(command),
            HOOK_CONTROL_MUTATION.search(command) and not hooks_activation,
            git_command_controls_hooks(command) and not hooks_activation,
            git_command_is_broad_policy_mutation(command),
        )
    ):
        found.append("<repository policy bundle>")
    for subcommand, args, _ in git_invocations(command):
        if (
            subcommand == "config"
            and _git_config_is_mutating(args)
            and not hooks_activation
            and not any(item.casefold() in {"--global", "--system"} for item in args)
        ):
            found.append(".git/config")
    if command:
        for path in command_paths(raw_command):
            if normalize_repo_path(path, root) == "":
                found.append("<repository policy bundle>")
        for parent in protected_parent_paths():
            if hooks_activation and parent == ".githooks":
                continue
            if _standalone_path_in_command(command, parent):
                found.append(f"<directory: {parent}>")
    return list(dict.fromkeys(found))


def governed_targets(
    tool_name: str, tool_input: dict[str, Any], root: Path
) -> list[str]:
    if not is_mutating_tool(tool_name, tool_input):
        return []
    found = [
        normalize_repo_path(path, root)
        for path in target_paths(tool_input)
        if is_governed_path(path, root)
    ]
    raw_command = shell_command(tool_input)
    for path in command_paths(raw_command):
        if is_governed_path(path, root):
            found.append(normalize_repo_path(path, root))
    command = raw_command.replace("\\", "/")
    command_cmp = command.casefold() if os.name == "nt" else command
    for prefix in (*GOVERNED_PREFIXES, *GOVERNED_FILES):
        prefix_cmp = prefix.casefold() if os.name == "nt" else prefix
        if prefix_cmp in command_cmp:
            found.append(prefix)
    if command:
        found.append("<shell effect>")
    return list(dict.fromkeys(found))


def accepted_amendment_tokens(root: Path) -> set[str]:
    tokens: set[str] = set()
    plan = root / PLAN_REL
    if plan.is_file():
        try:
            tokens.add(file_sha256(plan))
        except (OSError, UnicodeError):
            pass
    ledger = root / LEDGER_REL
    if ledger.is_file():
        try:
            records = read_ledger(root)
            if records:
                tokens.add(str(records[-1].get("result_plan_sha256") or ""))
        except (OSError, UnicodeError, ValueError):
            pass
    head = git_show(root, f"HEAD:{PLAN_REL}", check=False)
    if head is not None:
        tokens.add(
            hashlib.sha256(normalized_text(head).encode("utf-8")).hexdigest()
        )
    return {token for token in tokens if SHA256.fullmatch(token)}


def amendment_unlocked(root: Path) -> bool:
    supplied = os.environ.get("DAEDALUS_IRON_PLAN_AMENDMENT", "").strip()
    return bool(supplied and supplied in accepted_amendment_tokens(root))


def hook_context(root: Path, errors: list[str] | None = None) -> str:
    digest = "unknown"
    revision: int | None = None
    gate = "unknown"
    try:
        digest = file_sha256(root / PLAN_REL)
        revision, _, gate = parse_plan_header(
            (root / PLAN_REL).read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError):
        pass
    base = (
        f"IRON PLAN ACTIVE — {PLAN_ID} revision {revision}, {gate}, "
        f"sha256 {digest}. Read {PLAN_REL}. Classify work as ALIGNED, "
        "EXPERIMENT, or AMENDMENT. Hard invariants MUST NOT drift silently. "
        "This workflow guard protects policy artifacts; it does not prove "
        "architectural semantics or sandbox filesystem effects. Research "
        "priors may be challenged only read-only or in a frozen, isolated, "
        "measured experiment."
    )
    if errors:
        return base + " POLICY VERIFY FAILED: " + " | ".join(errors[:4])
    return base


def _json_output(value: dict[str, Any]) -> None:
    # Lifecycle hooks are byte pipes. ASCII-only JSON avoids inheriting a
    # Windows console code page that disagrees with the fail-closed runner's
    # UTF-8 decoder.
    json.dump(value, sys.stdout, ensure_ascii=True)


def _hook_additional(event: str, context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }


def _hook_deny(event: str, reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _git_path(root: Path, name: str) -> Path | None:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-path", name],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    value = Path(proc.stdout.strip())
    return value if value.is_absolute() else root / value


def _state_path(root: Path, payload: dict[str, Any]) -> Path | None:
    session = str(
        payload.get("session_id") or payload.get("sessionId") or ""
    ).strip()
    if not session:
        return None
    directory = _git_path(root, "iron-plan-hook-state")
    if directory is None:
        return None
    key = hashlib.sha256(session.encode("utf-8")).hexdigest()[:24]
    return directory / f"{key}.json"


def mark_session_write(
    root: Path, payload: dict[str, Any], tool_name: str, targets: list[str]
) -> bool:
    path = _state_path(root, payload)
    if path is None:
        return False
    temporary = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(
            json.dumps({"tool": tool_name, "targets": targets}, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return True
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def clear_session_write(root: Path, payload: dict[str, Any]) -> None:
    path = _state_path(root, payload)
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return


def session_has_write(root: Path, payload: dict[str, Any]) -> bool:
    path = _state_path(root, payload)
    return bool(path and path.is_file())


def handoff_errors(message: str, active_gate: str | None) -> list[str]:
    errors: list[str] = []
    plan_match = re.search(
        r"(?m)^Iron Plan:\s*(ALIGNED|EXPERIMENT|AMENDMENT)\s*$",
        message,
    )
    if not plan_match:
        errors.append("Iron Plan: ALIGNED|EXPERIMENT|AMENDMENT")

    expected_gate_match = re.match(r"^Gate\s+([0-5])\b", active_gate or "")
    expected_gate = expected_gate_match.group(1) if expected_gate_match else None
    gate_match = re.search(r"(?m)^Iron Gate:\s*([0-5])\s*$", message)
    if expected_gate is None:
        errors.append("a parseable active gate in the canonical plan")
    elif not gate_match or gate_match.group(1) != expected_gate:
        errors.append(f"Iron Gate: {expected_gate}")

    evidence_match = re.search(r"(?m)^Evidence:\s*(.*?)\s*$", message)
    evidence = evidence_match.group(1).strip() if evidence_match else ""
    placeholders = {
        "",
        "n/a",
        "na",
        "none",
        "nothing",
        "tbd",
        "todo",
        "unknown",
        "tests",
        "tests pass",
        "green",
        "passed",
    }
    if evidence.casefold() in placeholders or len(evidence) < 12:
        errors.append("Evidence: <specific inspected behavior/artifact>")
    return errors


def hook(root_value: str | Path | None = None) -> int:
    root = repo_root(root_value)
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"Iron Plan hook received invalid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("Iron Plan hook payload must be a JSON object", file=sys.stderr)
        return 2

    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    raw_input = payload.get("tool_input") or payload.get("toolInput") or {}
    tool_input = raw_input if isinstance(raw_input, dict) else {}
    errors = verify(root)
    context = hook_context(root, errors)

    if event == "PreToolUse":
        mutating = is_mutating_tool(tool_name, tool_input)
        protected = protected_targets(tool_name, tool_input, root)
        unlocked = amendment_unlocked(root) if protected else False
        activation = is_exact_hooks_activation(shell_command(tool_input))
        activation_repairs_only_error = bool(errors) and all(
            error.startswith("local core.hooksPath is not .githooks")
            for error in errors
        )
        if (
            mutating
            and errors
            and not (protected and unlocked)
            and not (activation and activation_repairs_only_error)
        ):
            _json_output(
                _hook_deny(
                    event,
                    "Iron Plan verification is broken; effectful tools fail closed. "
                    + " | ".join(errors[:4]),
                )
            )
            return 0
        if protected and not unlocked:
            _json_output(
                _hook_deny(
                    event,
                    "Protected Iron Plan artifact(s) cannot change in ordinary work: "
                    + ", ".join(protected)
                    + ". Follow the owner-approved amendment protocol.",
                )
            )
            return 0
        governed = governed_targets(tool_name, tool_input, root)
        if mutating and governed:
            if not mark_session_write(root, payload, tool_name, governed):
                _json_output(
                    _hook_deny(
                        event,
                        "Cannot durably record Iron Plan evidence debt for this "
                        "governed effect; the tool fails closed.",
                    )
                )
                return 0
        _json_output(_hook_additional(event, context))
        return 0

    if event == "Stop":
        message = str(
            payload.get("last_assistant_message")
            or payload.get("lastAssistantMessage")
            or ""
        )
        if payload.get("stop_hook_active"):
            # Claude sets this on the continuation caused by a blocking Stop
            # hook. Never block recursively. Clear the evidence debt only when
            # the corrective continuation now carries a valid handoff.
            if not errors and session_has_write(root, payload):
                plan_text = (root / PLAN_REL).read_text(encoding="utf-8")
                _, _, active_gate = parse_plan_header(plan_text)
                if not handoff_errors(message, active_gate):
                    clear_session_write(root, payload)
            return 0
        if errors:
            _json_output(
                {
                    "decision": "block",
                    "reason": "Iron Plan verification failed. Repair or report: "
                    + " | ".join(errors[:4]),
                }
            )
            return 0
        if session_has_write(root, payload):
            _, _, active_gate = parse_plan_header(
                (root / PLAN_REL).read_text(encoding="utf-8")
            )
            invalid = handoff_errors(message, active_gate)
            if invalid:
                _json_output(
                    {
                        "decision": "block",
                        "reason": "Complete the governed-change handoff with valid "
                        + ", ".join(invalid),
                    }
                )
                return 0
            clear_session_write(root, payload)
        return 0

    _json_output(_hook_additional(event or "SessionStart", context))
    return 0


def git_run(
    root: Path, args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git command failed")
    return proc


def git_show(root: Path, spec: str, *, check: bool = True) -> str | None:
    proc = git_run(root, ["show", spec], check=False)
    if proc.returncode != 0:
        if check:
            raise RuntimeError(proc.stderr.strip() or f"cannot read {spec}")
        return None
    return proc.stdout


def staged_paths(root: Path) -> list[str]:
    proc = git_run(
        root,
        [
            "diff",
            "--cached",
            "--name-only",
            "--no-renames",
            "--diff-filter=ACMRTD",
        ],
    )
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def _head_plan_digest(root: Path) -> str | None:
    value = git_show(root, f"HEAD:{PLAN_REL}", check=False)
    if value is None:
        return None
    return hashlib.sha256(normalized_text(value).encode("utf-8")).hexdigest()


def _head_ledger(root: Path) -> list[dict[str, Any]]:
    value = git_show(root, f"HEAD:{LEDGER_REL}", check=False)
    if value is None:
        return []
    records: list[dict[str, Any]] = []
    for line in value.splitlines():
        if line.strip():
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
    return records


def verify_base(
    base_ref: str,
    root_value: str | Path | None = None,
    current_ref: str = "HEAD",
) -> list[str]:
    """Verify append-only policy evolution between two Git revisions.

    This is intended for CI. Local hook checks can be bypassed. It becomes an
    independent trust anchor only where the remote check and protected owner
    review are actually configured as required.
    """

    root = repo_root(root_value)
    errors = verify(root)
    base_plan = git_show(root, f"{base_ref}:{PLAN_REL}", check=False)
    current_plan = git_show(root, f"{current_ref}:{PLAN_REL}", check=False)
    if base_plan is None:
        errors.append(f"{base_ref} does not contain {PLAN_REL}")
        return errors
    if current_plan is None:
        errors.append(f"{current_ref} does not contain {PLAN_REL}")
        return errors

    base_ledger_text = git_show(root, f"{base_ref}:{LEDGER_REL}", check=False)
    current_ledger_text = git_show(root, f"{current_ref}:{LEDGER_REL}", check=False)
    if current_ledger_text is None:
        errors.append(f"{current_ref} does not contain {LEDGER_REL}")
        return errors

    try:
        base_records = (
            parse_ledger_text(base_ledger_text, f"{base_ref}:{LEDGER_REL}")
            if base_ledger_text is not None
            else []
        )
        current_records = parse_ledger_text(
            current_ledger_text, f"{current_ref}:{LEDGER_REL}"
        )
    except ValueError as exc:
        errors.append(str(exc))
        return errors

    diff = git_run(
        root,
        [
            "diff",
            "--name-only",
            "--no-renames",
            "--diff-filter=ACMRTD",
            base_ref,
            current_ref,
        ],
        check=False,
    )
    if diff.returncode != 0:
        errors.append(
            f"cannot compare {base_ref}..{current_ref}: "
            + (diff.stderr.strip() or "git diff failed")
        )
        return errors
    changed = {
        line.strip().replace("\\", "/")
        for line in diff.stdout.splitlines()
        if line.strip()
    }
    protected_changed = changed.intersection(PROTECTED_PATHS)
    base_digest = hashlib.sha256(
        normalized_text(base_plan).encode("utf-8")
    ).hexdigest()
    current_digest = hashlib.sha256(
        normalized_text(current_plan).encode("utf-8")
    ).hexdigest()

    if not base_records:
        missing = sorted(ADOPTION_REQUIRED.difference(changed))
        if missing:
            errors.append(
                "initial adoption does not change the complete policy bundle: "
                + ", ".join(missing)
            )
        if len(current_records) != 1:
            errors.append("initial adoption must create exactly one ledger record")
            return errors
        first = current_records[0]
        if first.get("base_plan_sha256") != base_digest:
            errors.append("initial adoption base digest does not match base revision")
        if first.get("result_plan_sha256") != current_digest:
            errors.append("initial adoption result digest does not match current plan")
        return errors

    if current_records[: len(base_records)] != base_records:
        errors.append("accepted amendment history was rewritten or reordered")
        return errors

    if not protected_changed:
        if len(current_records) != len(base_records):
            errors.append("ledger changed without a protected policy change")
        if current_digest != base_digest:
            errors.append("plan changed without appearing in the protected diff")
        return errors

    if not {PLAN_REL, LEDGER_REL}.issubset(protected_changed):
        errors.append(
            "protected policy changes must include plan and ledger atomically"
        )
    if len(current_records) != len(base_records) + 1:
        errors.append("protected policy change must append exactly one record")
        return errors
    latest = current_records[-1]
    previous = base_records[-1]
    if latest.get("previous_record_sha256") != previous.get("record_sha256"):
        errors.append("new amendment does not extend the previous record hash")
    if latest.get("base_plan_sha256") != base_digest:
        errors.append("new amendment base digest does not match the base plan")
    if latest.get("result_plan_sha256") != current_digest:
        errors.append("new amendment result digest does not match the current plan")
    return errors


def pre_commit(root_value: str | Path | None = None) -> int:
    root = repo_root(root_value)
    errors = verify(root)
    if errors:
        for error in errors:
            print(f"IRON PLAN ERROR: {error}", file=sys.stderr)
        return 1

    staged = set(staged_paths(root))
    governed = {path for path in staged if is_governed_path(path, root)}
    if not governed:
        return 0

    protected = staged.intersection(PROTECTED_PATHS)

    for rel in PROTECTED_PATHS:
        unstaged = git_run(root, ["diff", "--quiet", "--", rel], check=False)
        if unstaged.returncode != 0:
            print(
                f"IRON PLAN ERROR: protected path has unstaged changes: {rel}",
                file=sys.stderr,
            )
            return 1

    current_records = read_ledger(root)
    head_records = _head_ledger(root)
    head_digest = _head_plan_digest(root)

    if not head_records:
        missing = sorted(ADOPTION_REQUIRED.difference(staged))
        if missing:
            print(
                "IRON PLAN ERROR: initial adoption must stage the complete policy "
                "bundle; missing: " + ", ".join(missing),
                file=sys.stderr,
            )
            return 1
        first = current_records[0]
        if len(current_records) != 1 or first.get("sequence") != 1:
            print("IRON PLAN ERROR: initial ledger must contain one record", file=sys.stderr)
            return 1
        if head_digest and first.get("base_plan_sha256") != head_digest:
            print(
                "IRON PLAN ERROR: adoption base digest does not match HEAD plan",
                file=sys.stderr,
            )
            return 1
        return 0

    if not protected:
        return 0

    supplied = os.environ.get("DAEDALUS_IRON_PLAN_AMENDMENT", "").strip()
    if not head_digest or supplied != head_digest:
        print(
            "IRON PLAN ERROR: protected changes require "
            "DAEDALUS_IRON_PLAN_AMENDMENT=<HEAD plan sha256>",
            file=sys.stderr,
        )
        return 1
    if not {PLAN_REL, LEDGER_REL}.issubset(staged):
        print(
            "IRON PLAN ERROR: an amendment must stage plan and ledger atomically",
            file=sys.stderr,
        )
        return 1
    if len(current_records) != len(head_records) + 1:
        print(
            "IRON PLAN ERROR: append exactly one accepted amendment record",
            file=sys.stderr,
        )
        return 1
    latest = current_records[-1]
    previous = head_records[-1]
    if latest.get("previous_record_sha256") != previous.get("record_sha256"):
        print("IRON PLAN ERROR: amendment record chain mismatch", file=sys.stderr)
        return 1
    if latest.get("base_plan_sha256") != head_digest:
        print("IRON PLAN ERROR: amendment base digest mismatch", file=sys.stderr)
        return 1
    return 0


def commit_msg(path: str, root_value: str | Path | None = None) -> int:
    root = repo_root(root_value)
    staged = staged_paths(root)
    if not any(is_governed_path(path_value, root) for path_value in staged):
        return 0
    try:
        message = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"IRON PLAN ERROR: cannot read commit message: {exc}", file=sys.stderr)
        return 1
    plan_match = re.search(
        r"(?im)^Iron-Plan:\s*(aligned|experiment|amendment|adoption)\s*$",
        message,
    )
    gate_match = re.search(r"(?im)^Iron-Gate:\s*([0-5])\s*$", message)
    if not plan_match or not gate_match:
        print(
            "IRON PLAN ERROR: governed commits require trailers "
            "'Iron-Plan: aligned|experiment|amendment|adoption' and "
            "'Iron-Gate: 0..5'",
            file=sys.stderr,
        )
        return 1
    plan_text = _read_utf8(root / PLAN_REL, PLAN_REL, [])
    _, _, active_gate = parse_plan_header(plan_text or "")
    expected_match = re.match(r"^Gate\s+([0-5])\b", active_gate or "")
    if not expected_match or gate_match.group(1) != expected_match.group(1):
        print(
            "IRON PLAN ERROR: Iron-Gate trailer must match the canonical "
            f"active gate ({expected_match.group(1) if expected_match else 'unknown'})",
            file=sys.stderr,
        )
        return 1
    protected = set(staged).intersection(PROTECTED_PATHS)
    if protected and plan_match.group(1).casefold() not in {"amendment", "adoption"}:
        print(
            "IRON PLAN ERROR: protected policy changes must be labelled amendment "
            "or adoption",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", help="override repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("verify")
    subparsers.add_parser("hook")
    subparsers.add_parser("pre-commit")
    base_parser = subparsers.add_parser("verify-base")
    base_parser.add_argument("base_ref")
    base_parser.add_argument("--current-ref", default="HEAD")
    commit_parser = subparsers.add_parser("commit-msg")
    commit_parser.add_argument("message_file")
    args = parser.parse_args(argv)
    root = repo_root(args.repo_root)

    if args.command == "verify":
        errors = verify(root)
        if errors:
            for error in errors:
                print(f"IRON PLAN ERROR: {error}", file=sys.stderr)
            return 1
        digest = file_sha256(root / PLAN_REL)
        revision, _, gate = parse_plan_header(
            (root / PLAN_REL).read_text(encoding="utf-8")
        )
        print(f"Iron Plan OK: revision {revision}, {gate}, sha256 {digest}")
        return 0
    if args.command == "hook":
        return hook(root)
    if args.command == "pre-commit":
        return pre_commit(root)
    if args.command == "verify-base":
        errors = verify_base(args.base_ref, root, args.current_ref)
        if errors:
            for error in errors:
                print(f"IRON PLAN ERROR: {error}", file=sys.stderr)
            return 1
        print(f"Iron Plan history OK: {args.base_ref}..{args.current_ref}")
        return 0
    if args.command == "commit-msg":
        return commit_msg(args.message_file, root)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
