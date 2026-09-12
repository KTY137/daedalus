"""Builder agents: the hands the Chef puts to work inside one workspace.

Two real lanes today -- Claude Code (``claude -p``) and the OpenAI Codex CLI
(``codex exec``) -- plus an injectable ``callable`` lane for tests. A builder
receives the workspace, an objective and a prompt; it returns a report with
the exit status, the model's final text and the files it changed.

Owner decision 2026-09-12: these spawns are NOT routed through the sealed
Claude runtime bundle (``daedalus.providers.claude_cli``) and do not claim
containment. The kitchen records ``containment: "deferred"`` in every evidence
packet so nobody mistakes this lane for the Gate-0 isolation path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_TIMEOUT_S = 1800
DEFAULT_CHAIN = ("ollama", "claude", "codex")
_ENV_BLOCKLIST = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


from .report import BuilderReport, BuilderUnavailable

BuilderFn = Callable[[Path, str, int], BuilderReport]
LaneFn = Callable[..., BuilderReport]


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in _ENV_BLOCKLIST:
        env.pop(key, None)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _snapshot(workspace: Path) -> dict[str, tuple[int, int]]:
    seen: dict[str, tuple[int, int]] = {}
    for path in workspace.rglob("*"):
        if any(part in {".git", "node_modules", "__pycache__", ".venv", "dist"} for part in path.parts):
            continue
        if path.is_file():
            try:
                stat = path.stat()
            except OSError:
                continue
            seen[path.relative_to(workspace).as_posix()] = (stat.st_mtime_ns, stat.st_size)
    return seen


def _changed(before: dict[str, tuple[int, int]], after: dict[str, tuple[int, int]]) -> list[str]:
    return sorted(path for path, sig in after.items() if before.get(path) != sig)


def _which(*names: str) -> str | None:
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None


def claude_available() -> bool:
    return _which("claude", "claude.exe", "claude.cmd") is not None


def codex_available() -> bool:
    if _which("codex", "codex.exe", "codex.cmd"):
        return True
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "node" / "codex.cmd"
    return local.is_file()


def _run(cmd: list[str], *, cwd: Path, prompt: str, timeout_s: int) -> tuple[int | None, str, str, float]:
    started = time.time()
    try:
        completed = subprocess.run(cmd, cwd=str(cwd), input=prompt, text=True, capture_output=True,
                                   encoding="utf-8", errors="replace", timeout=timeout_s, env=_clean_env(), check=False)
        return completed.returncode, completed.stdout or "", completed.stderr or "", time.time() - started
    except subprocess.TimeoutExpired as exc:
        return None, (exc.stdout or "") if isinstance(exc.stdout, str) else "", "timeout", time.time() - started


def _claude_result_text(stdout: str) -> str:
    stdout = stdout.strip()
    try:
        payload = json.loads(stdout)
    except ValueError:
        for line in reversed(stdout.splitlines()):
            try:
                frame = json.loads(line)
            except ValueError:
                continue
            if isinstance(frame, dict) and frame.get("type") == "result":
                return str(frame.get("result") or "")
        return stdout[-4000:]
    if isinstance(payload, dict):
        return str(payload.get("result") or payload.get("text") or stdout[-4000:])
    return stdout[-4000:]


def claude_builder(workspace: Path, prompt: str, timeout_s: int = DEFAULT_TIMEOUT_S, context: dict[str, Any] | None = None) -> BuilderReport:
    command = _which("claude", "claude.exe", "claude.cmd")
    if not command:
        raise BuilderUnavailable("claude CLI not found")
    model = os.environ.get("DAEDALUS_KITCHEN_CLAUDE_MODEL", "sonnet")
    cmd = [command, "-p", "--output-format", "json", "--permission-mode", "bypassPermissions",
           "--model", model, "--max-turns", os.environ.get("DAEDALUS_KITCHEN_CLAUDE_TURNS", "80")]
    before = _snapshot(workspace)
    code, out, err, seconds = _run(cmd, cwd=workspace, prompt=prompt, timeout_s=timeout_s)
    changed = _changed(before, _snapshot(workspace))
    text = _claude_result_text(out)
    ok = code == 0 and bool(changed) and "error" not in text.lower()[:40]
    return BuilderReport("claude", ok, code, seconds, text or err[-2000:], changed, out, err, model)


def codex_builder(workspace: Path, prompt: str, timeout_s: int = DEFAULT_TIMEOUT_S, context: dict[str, Any] | None = None) -> BuilderReport:
    command = _which("codex", "codex.exe", "codex.cmd")
    if not command:
        local = Path(os.environ.get("LOCALAPPDATA", "")) / "hermes" / "node" / "codex.cmd"
        command = str(local) if local.is_file() else None
    if not command:
        raise BuilderUnavailable("codex CLI not found")
    sandbox = "danger-full-access" if os.environ.get("DAEDALUS_KITCHEN_CODEX_FULL_ACCESS") == "1" else "workspace-write"
    cmd = [command, "exec", "--cd", str(workspace), "--sandbox", sandbox, "--skip-git-repo-check", "--color", "never"]
    model = os.environ.get("DAEDALUS_KITCHEN_CODEX_MODEL") or os.environ.get("CODEX_MODEL")
    if model:
        cmd += ["--model", model]
    cmd.append("-")
    before = _snapshot(workspace)
    code, out, err, seconds = _run(cmd, cwd=workspace, prompt=prompt, timeout_s=timeout_s)
    changed = _changed(before, _snapshot(workspace))
    ok = code == 0 and bool(changed)
    return BuilderReport("codex", ok, code, seconds, out[-4000:] or err[-2000:], changed, out, err, model)


def _ollama_available() -> bool:
    from .souschef import ollama_available
    return ollama_available()


def _ollama_builder(workspace: Path, prompt: str, timeout_s: int = DEFAULT_TIMEOUT_S,
                    context: dict[str, Any] | None = None) -> BuilderReport:
    from .souschef import ollama_builder
    return ollama_builder(workspace, prompt, timeout_s, context)


LANES: dict[str, tuple[Callable[[], bool], LaneFn]] = {
    "claude": (claude_available, claude_builder),
    "codex": (codex_available, codex_builder),
    "ollama": (_ollama_available, _ollama_builder),
}


def configured_chain() -> tuple[str, ...]:
    raw = os.environ.get("DAEDALUS_KITCHEN_BUILDERS", ",".join(DEFAULT_CHAIN))
    chain = tuple(part.strip() for part in raw.split(",") if part.strip())
    return chain or DEFAULT_CHAIN


def available_lanes(chain: tuple[str, ...] | None = None) -> list[str]:
    result = []
    for lane in chain or configured_chain():
        probe = LANES.get(lane)
        if probe and probe[0]():
            result.append(lane)
    return result


def run_builder(workspace: Path, prompt: str, *, chain: tuple[str, ...] | None = None,
                timeout_s: int = DEFAULT_TIMEOUT_S, builder: BuilderFn | None = None,
                log: Callable[[str], None] | None = None, context: dict[str, Any] | None = None) -> BuilderReport:
    """Run the first available lane; fall through on unavailability or failure."""
    if builder is not None:
        return builder(workspace, prompt, timeout_s)
    lanes = chain or configured_chain()
    last: BuilderReport | None = None
    for lane in lanes:
        entry = LANES.get(lane)
        if entry is None:
            continue
        probe, run = entry
        if not probe():
            if log:
                log(f"builder lane {lane}: unavailable")
            continue
        if log:
            log(f"builder lane {lane}: started")
        report = run(workspace, prompt, timeout_s, {**(context or {}), "log": log})
        if log:
            log(f"builder lane {lane}: exit={report.exit_code} changed={len(report.changed_files)} ok={report.ok}")
        if report.ok:
            return report
        last = report
    if last is not None:
        return last
    raise BuilderUnavailable("no builder lane available (install Claude Code or Codex CLI, or set DAEDALUS_KITCHEN_BUILDERS)")


__all__ = ["BuilderReport", "BuilderUnavailable", "run_builder", "available_lanes", "configured_chain",
           "claude_builder", "codex_builder", "DEFAULT_TIMEOUT_S", "LANES"]
