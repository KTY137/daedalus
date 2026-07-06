"""CLI-first, API-ready runtime registry.

Daedalus orchestration should depend on runtime capabilities, not on random
subprocess calls scattered through the app. This registry exposes a stable
status/test surface for CLIs today and API providers later.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any

from .env import load_env
from .providers.ollama import DEFAULT_HOST, DEFAULT_MODEL


@dataclass(frozen=True)
class RuntimeSpec:
    id: str
    label: str
    mode: str
    command: str = ""
    env_key: str = ""
    local: bool = False
    trusted_with_ip: bool = False
    can_write: bool = False
    agentic: bool = False
    notes: str = ""


RUNTIMES: tuple[RuntimeSpec, ...] = (
    RuntimeSpec(
        id="claude_code_cli",
        label="Claude Code CLI",
        mode="cli",
        command="claude",
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Primary frontier runtime. Uses existing Claude Code CLI authentication.",
    ),
    RuntimeSpec(
        id="codex_cli",
        label="Codex CLI",
        mode="cli",
        command="codex",
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Codex participates through AGENTS.md and the Daedalus file bus when CLI auth is available.",
    ),
    RuntimeSpec(
        id="ollama_http",
        label="Ollama HTTP",
        mode="local_http",
        local=True,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Preferred local model interface; no API key required.",
    ),
    RuntimeSpec(
        id="ollama_cli",
        label="Ollama CLI",
        mode="cli",
        command="ollama",
        local=True,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        notes="Fallback local model interface.",
    ),
    RuntimeSpec(
        id="anthropic_api",
        label="Anthropic API",
        mode="api",
        env_key="ANTHROPIC_API_KEY",
        trusted_with_ip=True,
        can_write=False,
        agentic=False,
        notes="API-ready future slot; not required when Claude Code CLI is authenticated.",
    ),
    RuntimeSpec(
        id="openai_api",
        label="OpenAI API",
        mode="api",
        env_key="OPENAI_API_KEY",
        trusted_with_ip=False,
        can_write=False,
        agentic=False,
        notes="API-ready future slot; Codex CLI can be used first.",
    ),
)


def _run_version(command: str) -> tuple[bool, str, str]:
    path = shutil.which(command)
    if not path:
        return False, "", f"{command} not found on PATH"
    try:
        completed = subprocess.run(
            [command, "--version"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, path, str(exc)
    output = (completed.stdout or completed.stderr or "").strip()
    ok = completed.returncode == 0
    return ok, path, output or f"exit {completed.returncode}"


def _ollama_http_status() -> dict[str, Any]:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    want = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        models = [m.get("model") or m.get("name") for m in payload.get("models", [])]
        stem = want.split(":")[0]
        return {
            "available": True,
            "auth_status": "local",
            "command_path": "",
            "version": "",
            "endpoint": host,
            "models": models,
            "selected_model": want,
            "model_present": any(stem in (m or "") for m in models),
            "last_error": "",
        }
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError) as exc:
        return {
            "available": False,
            "auth_status": "local_unreachable",
            "command_path": "",
            "version": "",
            "endpoint": host,
            "models": [],
            "selected_model": want,
            "model_present": False,
            "last_error": str(exc),
        }


def runtime_status(runtime_id: str) -> dict[str, Any]:
    load_env()
    spec = next((r for r in RUNTIMES if r.id == runtime_id), None)
    if spec is None:
        raise KeyError(f"unknown runtime '{runtime_id}'")
    base = asdict(spec)
    if spec.id == "ollama_http":
        return {**base, **_ollama_http_status()}
    if spec.mode == "cli":
        ok, path, detail = _run_version(spec.command)
        return {
            **base,
            "available": ok,
            "auth_status": "cli_detected" if ok else "unavailable",
            "command_path": path,
            "version": detail if ok else "",
            "models": [],
            "selected_model": "",
            "model_present": False,
            "last_error": "" if ok else detail,
        }
    configured = bool(os.environ.get(spec.env_key)) if spec.env_key else False
    return {
        **base,
        "available": configured,
        "auth_status": "configured" if configured else "not_configured",
        "command_path": "",
        "version": "",
        "models": [],
        "selected_model": "",
        "model_present": False,
        "last_error": "" if configured else f"{spec.env_key} is not set",
    }


def all_status() -> dict[str, Any]:
    rows = []
    for spec in RUNTIMES:
        try:
            rows.append(runtime_status(spec.id))
        except Exception as exc:
            rows.append({**asdict(spec), "available": False, "auth_status": "error", "last_error": str(exc)})
    return {"runtimes": rows}


def test_runtime(runtime_id: str) -> dict[str, Any]:
    """Safe readiness test; no paid LLM prompt is sent."""
    row = runtime_status(runtime_id)
    return {
        "runtime": runtime_id,
        "ok": bool(row.get("available")),
        "mode": row.get("mode"),
        "detail": row.get("version") or row.get("last_error") or row.get("endpoint") or row.get("auth_status"),
    }
