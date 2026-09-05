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
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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


_WINDOWS_BATCH_SUFFIXES = (".cmd", ".bat")


def _runtime_platform() -> str:
    """Return the process platform through a narrow, testable observation seam."""
    return os.name


def claude_command_for_spawn(
    resolved: str | None = None,
    *,
    platform_name: str | None = None,
) -> str:
    """Return the resolved Claude executable iff argv can reach it as data.

    Claude Code may be installed as an npm ``.cmd``/``.bat`` shim on Windows.
    Python's ``shell=False`` does not turn such a batch file into a native
    executable: Windows invokes ``cmd.exe`` and the command interpreter reparses
    every argv element. Caller-controlled prompt/model text must therefore never
    cross that relay. This is the single admission rule shared by readiness and
    the live Claude subprocess boundary.
    """

    path = resolved or shutil.which("claude")
    if not path:
        raise RuntimeError("Claude executable could not be resolved before spawn")
    platform = _runtime_platform() if platform_name is None else platform_name
    if platform == "nt" and path.casefold().endswith(_WINDOWS_BATCH_SUFFIXES):
        raise RuntimeError(
            "Claude execution refused: Windows .cmd/.bat launchers reparse argv"
        )
    return path


def _run_version(
    command: str,
    *,
    refuse_windows_batch_shim: bool = False,
) -> tuple[bool, str, str]:
    path = shutil.which(command)
    if not path:
        return False, "", f"{command} not found on PATH"
    if refuse_windows_batch_shim:
        try:
            claude_command_for_spawn(path, platform_name=_runtime_platform())
        except RuntimeError as exc:
            return False, path, str(exc)
    try:
        completed = subprocess.run(
            # Spawn the RESOLVED path, not the bare name: npm ships `codex` as a
            # .CMD shim on Windows and CreateProcess cannot launch it by name
            # (WinError 2), so this probe reported codex as unavailable even
            # with the CLI installed and logged in. `claude`/`ollama` are real
            # .EXEs, which is why only codex was affected. Same lesson is
            # already encoded in providers/codex_cli.py and doctor.py.
            [path, "--version"],
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
        # Claude's live provider path intentionally refuses Windows .cmd/.bat
        # shims because cmd.exe reparses caller-controlled argv even with
        # shell=False. The readiness surface must describe that executable
        # reality rather than merely proving that `claude --version` can run.
        # Other CLI providers retain their own transport policy here.
        ok, path, detail = _run_version(
            spec.command,
            refuse_windows_batch_shim=(spec.id == "claude_code_cli"),
        )
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


# --------------------------------------------------------------------------- #
# THE CACHE, AND WHY IT MUST CARRY WHEN IT MEASURED (owner decision 2026-08-27) #
# --------------------------------------------------------------------------- #
# runtime_status launches each CLI to read its --version, so /api/runtimes/status
# is slow BY CONSTRUCTION and grows with use: MEASURED 16.6s under load, 28.0s on
# a quiet box, 36.1s after the Playwright suite (docs/design/handoffs-2026-08-26).
# The owner's ruling is to cache the probe rather than relaunch every CLI on every
# poll -- but a cached reading that reports "erreichbar" for a CLI that broke a
# minute ago is the exact lie this codebase forbids. So the contract is: every
# CACHED row carries `measured_at` (when the probe actually ran) and
# `measured_age_s`, and the surface shows it. The uncached path -- the direct
# callers in tests and elsewhere -- is byte-identical to before; the field
# appears only when a caller opts into the cache.
#
# Concurrent cache misses for the SAME runtime are single-flight. Without that,
# two browser polls arriving in one scheduler tick both miss, both drop the cache
# lock, and both spawn the same slow CLI `--version` probe. The cache then reduces
# steady-state work but amplifies a cold/expired edge into N identical processes.
# Runtime-specific probe locks coalesce only that duplicate work: two DIFFERENT
# runtimes still probe in parallel, and TTL=0 still means sequential calls never
# reuse a result.
_STATUS_CACHE_TTL_S = float(os.environ.get("DAEDALUS_RUNTIME_STATUS_TTL_S", "30"))
_status_cache_lock = threading.Lock()
#: runtime_id -> (monotonic_at, measured_at_iso, row) for the last probe.
_status_cache: dict[str, tuple[float, str, dict[str, Any]]] = {}
#: Stable per-runtime single-flight locks. Protected by ``_status_cache_lock``
#: only while looking up/creating a lock; the expensive probe never holds the
#: global cache lock.
_status_probe_locks: dict[str, threading.Lock] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reset_status_cache() -> None:
    """Drop every cached probe. For tests and for a deliberate refresh."""
    with _status_cache_lock:
        _status_cache.clear()


def _fresh_cached_row(runtime_id: str, ttl: float, now_mono: float) -> dict[str, Any] | None:
    """Return one stamped fresh row while holding no slow-operation lock."""
    with _status_cache_lock:
        entry = _status_cache.get(runtime_id)
        if entry is None or (now_mono - entry[0]) >= ttl:
            return None
        mono_at, iso_at, row = entry
        return {
            **row,
            "measured_at": iso_at,
            "measured_age_s": round(now_mono - mono_at, 3),
        }


def _runtime_probe_lock(runtime_id: str) -> threading.Lock:
    """Get the single-flight lock for one runtime without serialising others."""
    with _status_cache_lock:
        lock = _status_probe_locks.get(runtime_id)
        if lock is None:
            lock = threading.Lock()
            _status_probe_locks[runtime_id] = lock
        return lock


def cached_runtime_status(
    runtime_id: str, *, ttl_s: float | None = None
) -> dict[str, Any]:
    """`runtime_status` behind a per-runtime TTL cache, stamped with when the
    probe ran.

    A fresh hit returns immediately. On a miss/expiry, exactly one caller probes
    a given runtime; concurrent callers for that same runtime wait for the probe
    and then consume its newly cached row. Different runtimes use different
    single-flight locks, so a slow Claude probe does not block Ollama/Codex.
    """
    ttl = _STATUS_CACHE_TTL_S if ttl_s is None else float(ttl_s)
    cached = _fresh_cached_row(runtime_id, ttl, time.monotonic())
    if cached is not None:
        return cached

    # Do not hold `_status_cache_lock` while waiting or probing. The per-runtime
    # lock only coalesces duplicate work for this runtime; unrelated status
    # probes remain concurrent.
    probe_lock = _runtime_probe_lock(runtime_id)
    with probe_lock:
        # Double-check after waiting: the leader may have populated the cache
        # while this caller was blocked on the single-flight lock.
        cached = _fresh_cached_row(runtime_id, ttl, time.monotonic())
        if cached is not None:
            return cached

        try:
            row = runtime_status(runtime_id)
        except Exception as exc:  # noqa: BLE001 - a probe failure is a row, not a raise
            spec = next((r for r in RUNTIMES if r.id == runtime_id), None)
            base = asdict(spec) if spec is not None else {"id": runtime_id}
            row = {**base, "available": False, "auth_status": "error", "last_error": str(exc)}
        iso_at = _now_iso()
        measured_mono = time.monotonic()
        with _status_cache_lock:
            _status_cache[runtime_id] = (measured_mono, iso_at, row)
        return {**row, "measured_at": iso_at, "measured_age_s": 0.0}


def all_status(*, use_cache: bool = False, ttl_s: float | None = None) -> dict[str, Any]:
    rows = []
    for spec in RUNTIMES:
        if use_cache:
            rows.append(cached_runtime_status(spec.id, ttl_s=ttl_s))
            continue
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
